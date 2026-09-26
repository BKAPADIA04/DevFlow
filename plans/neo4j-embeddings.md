# Neo4j Embeddings — Phase 2 (vector-embedded text on graph nodes)

## Context

Phase 1 (`graph/connection.py`, `graph/constraints.py`, `graph/loader.py`,
`graph/cli.py`, `graph/seed.py`) writes entities/relationships into Neo4j
as plain nodes/edges — no vector data. CLAUDE.md §2 requires knowledge
graph construction to also write "vector-embedded text (Neo4j's native
vector index, not a separate store)" onto those same nodes. This plan
covers only that: giving every node an embedding at write time and a
queryable vector index per label. It does **not** touch query-time
retrieval (entry-point search, Cypher generation, the fallback path) —
that's `retrieval/`, explicitly deferred to a later phase per CLAUDE.md
§7, and nothing here blocks it.

**Model choice**: Gemini `text-embedding-004` (768-dim), via a new
`embed_content` method on the existing `helper/gemini_key_pool.py`
`GeminiKeyPool` — reuses the same round-robin/rate-limit-failover
infra `extraction/llm.py` already relies on, no new provider/key setup.

**Sparse-text entities**: all 11 entity types get an embedding, not just
the ones with obvious free text (File, PullRequest, Commit, Incident,
Review). Repository, Developer, Team, CIRun, Deployment, and Permission
each get a short synthesized sentence built from their properties, so
typed entry-point search (per `MDs/DevFlow-Workflow-1.md`) has something
to match against for every entity type, not just five of eleven.

**Caching**: Neo4j itself is the cache — `docker-compose.yml` already
gives it a named volume (`neo4j_data`), so once a node's `embedding`
property is written it survives container restarts on its own, with no
separate cache file needed. The loader checks Neo4j for an existing
embedding on each entity id before calling the API, and only embeds the
ones that are actually new. Re-running `graph/seed.py` (or `graph/cli.py`
against overlapping text) after the first load makes zero embedding API
calls, as long as the volume isn't wiped (`docker compose down -v`).

## Implementation

### 1. `helper/gemini_key_pool.py` — add `embed_content`

New method alongside `generate_content`, same rotation/cooldown-on-429
behavior, calling `client.models.embed_content(model=..., contents=...)`
(the `google-genai` client supports batching a list of strings in one
call, so one API call embeds an entire `ExtractionResult`'s worth of
entities rather than one call per entity):

```python
def embed_content(self, *, model: str, contents: list[str], **kwargs: Any):
    """Calls embedContent, rotating to the next key on 429/5xx errors."""
    last_error: Exception | None = None
    attempts = len(self._states) * 2

    for _ in range(attempts):
        state = self._next_state()
        if not state.is_available():
            time.sleep(max(0.0, state.cooldown_until - time.monotonic()))

        client = self._client_for(state.key)
        try:
            response = client.models.embed_content(
                model=model, contents=contents, **kwargs
            )
        except errors.APIError as exc:
            last_error = exc
            if exc.code == 429 or exc.code >= 500:
                state.mark_rate_limited()
                continue
            raise
        else:
            state.mark_success()
            return response

    raise RuntimeError(
        f"All {len(self._states)} Gemini API keys are rate-limited or failing"
    ) from last_error
```

Pulled out the shared retry loop into a small helper if it ends up
duplicated 1:1 with `generate_content` — judgment call at implementation
time, not load-bearing for this plan.

### 2. `graph/embeddings.py` (new)

Two responsibilities: build the embedding text for an entity, and batch
that text through the pool.

```python
EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIMENSIONS = 768

def build_embedding_text(entity: ExtractedEntity) -> str:
    """One text template per EntityType, reading from entity.properties."""
    props = {p.key: p.value for p in entity.properties}
    match entity.type:
        case EntityType.FILE:
            return props.get("path", entity.id)
        case EntityType.PULL_REQUEST:
            return f"{props.get('title', '')}. {props.get('description', '')}"
        case EntityType.COMMIT:
            return props.get("message", entity.id)
        case EntityType.INCIDENT:
            return (
                f"{props.get('severity', '')} incident: "
                f"{props.get('root_cause', '')}. {props.get('resolution', '')}"
            )
        case EntityType.REVIEW:
            return f"{props.get('result', '')} review: {props.get('comment', '')}"
        case EntityType.REPOSITORY:
            return f"repository {props.get('name', entity.id)}"
        case EntityType.DEVELOPER:
            return f"developer {props.get('name', entity.id)}"
        case EntityType.TEAM:
            return f"team {props.get('name', entity.id)}"
        case EntityType.CI_RUN:
            return f"CI run, status {props.get('status', 'unknown')}"
        case EntityType.DEPLOYMENT:
            return (
                f"deployment to {props.get('environment', 'unknown')}, "
                f"artifact {props.get('artifact_id', entity.id)}"
            )
        case EntityType.PERMISSION:
            return (
                f"{props.get('role_name', '')} permission: "
                f"{props.get('grants', '')}"
            )

def embed_texts(texts: list[str]) -> list[list[float]]:
    """One batched embedContent call for N texts, via the shared pool."""
    response = _get_pool().embed_content(model=EMBEDDING_MODEL, contents=texts)
    return [e.values for e in response.embeddings]
```

Every branch is exhaustive over `EntityType` (11 cases) so a 12th entity
type added later fails loudly (`match` with no default + a trailing
`assert_never`, or an explicit `raise ValueError` in a `case _:`) instead
of silently getting an empty embedding.

### 3. `graph/loader.py` — set `embedding`, skipping entities already embedded

`load_extraction_result` currently merges all entities, then all
relationships. It gains a lookup step before embedding: ask Neo4j which
of the incoming entity ids already have a stored `embedding`, and only
call the API for the ones that don't. This is the caching mechanism —
Neo4j's own data is the source of truth, so a second run over the same
(or overlapping) entities costs zero embedding calls:

```python
def _fetch_existing_embeddings(
    session: Session, entities: list[ExtractedEntity]
) -> dict[str, list[float]]:
    found: dict[str, list[float]] = {}
    by_type: dict[EntityType, list[str]] = defaultdict(list)
    for e in entities:
        by_type[e.type].append(e.id)

    for entity_type, ids in by_type.items():
        label = entity_type.value
        id_field = ID_FIELD_BY_TYPE[entity_type]
        query = (
            f"MATCH (n:{label}) WHERE n.{id_field} IN $ids "
            f"AND n.embedding IS NOT NULL "
            f"RETURN n.{id_field} AS id, n.embedding AS embedding"
        )
        for row in session.run(query, ids=ids):
            found[row["id"]] = row["embedding"]
    return found


def load_extraction_result(result: ExtractionResult) -> None:
    driver = get_driver()
    with driver.session() as session:
        existing = _fetch_existing_embeddings(session, result.entities)
        missing = [e for e in result.entities if e.id not in existing]
        texts = [build_embedding_text(e) for e in missing]
        vectors = embed_texts(texts) if texts else []
        embeddings = existing | {e.id: v for e, v in zip(missing, vectors)}

        for entity in result.entities:
            _merge_entity(session, entity, embeddings[entity.id])
        ...
```

`_merge_entity` gains an `embedding: list[float]` param and folds it into
the same `SET n += $props` write (Neo4j stores a `list[float]` node
property natively — this is exactly what `db.index.vector.queryNodes`
reads). Every entity still gets its non-embedding properties refreshed
on every run (unchanged `MERGE ... SET n += $props` behavior); only the
`embedding` computation itself is skipped when one already exists.

This is a size/freshness tradeoff worth stating plainly: if an entity's
underlying text changes later (e.g. a PR description gets edited) but
its id doesn't, the stored embedding goes stale and nothing here
re-embeds it automatically. Out of scope for this plan — a future
`--force-reembed` flag or a text-hash check (store a `embedding_source`
hash alongside `embedding`, re-embed when the hash no longer matches)
would close that gap if it turns out to matter.

### 4. `graph/constraints.py` — add `ensure_vector_indexes`

One vector index per entity label, named and created the same
schema-driven way the uniqueness constraints already are (loop over
`EntityType`, never a hand-kept label list):

```python
_VECTOR_INDEX_TEMPLATE = (
    "CREATE VECTOR INDEX {name} IF NOT EXISTS "
    "FOR (n:{label}) ON (n.embedding) "
    "OPTIONS {{indexConfig: {{"
    "`vector.dimensions`: {dimensions}, "
    "`vector.similarity_function`: 'cosine'}}}}"
)

def ensure_vector_indexes() -> None:
    driver = get_driver()
    with driver.session() as session:
        for entity_type in EntityType:
            label = entity_type.value
            name = f"{label.lower()}_embedding_index"
            session.run(_VECTOR_INDEX_TEMPLATE.format(
                name=name, label=label, dimensions=EMBEDDING_DIMENSIONS,
            ))
```

Called from `graph/cli.py` and `graph/seed.py` right next to the existing
`ensure_constraints()` call (both are idempotent `IF NOT EXISTS` setup
calls that belong together) — or folded into `ensure_constraints()`
itself under one `ensure_schema()` name; small naming call at
implementation time, doesn't change behavior either way.

### 5. `graph/seed.py` — no change needed beyond calling `ensure_vector_indexes`

Because the caching lives in `graph/loader.py` (§3) against Neo4j itself,
`graph/seed.py` needs no new file and no new logic — it already calls
`load_extraction_result(result)` unchanged. The only edit is adding the
`ensure_vector_indexes()` call alongside its existing
`ensure_constraints()` call. First `python -m graph.seed` run against an
empty database makes one batched embedding API call for all 19 seed
entities; every run after that — including repeated runs while iterating,
or a plain container restart — reads all 19 embeddings back from Neo4j
and makes zero embedding API calls, since the `neo4j_data` volume already
persisted them. A real cache miss only happens again after
`docker compose down -v` (volume wiped) or `data/seed_graph.json` gaining
a genuinely new entity id.

### 6. `requirements.txt` / `.env`

No changes — `google-genai` is already a transitive dependency of the
existing pool, and embeddings use the same `GEMINI_API_KEYS` /
`GEMINI_API_KEY_N` vars already configured for extraction.

## Verification

1. `python -m graph.constraints` (or wherever `ensure_vector_indexes`
   ends up called from) — confirm via
   `SHOW INDEXES YIELD name, type WHERE type = 'VECTOR'` that all 11
   indexes exist.
2. `python -m graph.seed` — re-load the seed dataset; confirm every node
   now has a 768-length `embedding` property:
   `MATCH (n) WHERE n.embedding IS NULL RETURN labels(n), count(*)` →
   empty result.
3. Direct vector search sanity check — embed a throwaway string via
   `graph.embeddings.embed_texts(["auth token refresh bug"])` and run
   `CALL db.index.vector.queryNodes('pullrequest_embedding_index', 3, $vec)
   YIELD node, score RETURN node.id, score` — confirm `PR-142` (the
   token-refresh PR in the seed data) ranks near the top.
4. Re-run `python -m graph.seed` a second time — confirm node/edge counts
   are unchanged (Phase 1's idempotency guarantee) and every embedding
   vector is byte-for-byte identical to before (not recomputed).
5. Cache check — after step 2 has populated all 19 embeddings, temporarily
   break the embedding API (e.g. blank out the Gemini keys in `.env`) and
   re-run `python -m graph.seed` — it must still succeed, since
   `_fetch_existing_embeddings` finds all 19 ids already embedded and the
   API is never called. Restart the Neo4j container
   (`docker compose restart neo4j`, not `down -v`) first to confirm this
   holds across restarts, not just within one process.
6. Cache-miss check — add one new entity to `data/seed_graph.json`,
   restore the Gemini keys, and re-run: confirm only the new entity
   triggers an embedding call (check via a log line or a breakpoint in
   `embed_texts`) while the other 19 are read back from Neo4j unchanged.

## Summary of new/changed files

- `helper/gemini_key_pool.py` (edit — add `embed_content`)
- `graph/embeddings.py` (new)
- `graph/loader.py` (edit — look up existing embeddings in Neo4j first,
  batch-embed only the missing entities, set `embedding` per node)
- `graph/constraints.py` (edit — add `ensure_vector_indexes`)
- `graph/cli.py`, `graph/seed.py` (edit — call `ensure_vector_indexes`)

## Out of scope

Query-time retrieval: entry-point search, Cypher generation/validation,
the flat-text fallback search, and the reranker (`retrieval/`, deferred
per CLAUDE.md §7/§9, and still has the open reranker-position question
from CLAUDE.md §8). This plan only makes the vectors exist and be
queryable — nothing here decides how they're queried at answer time.
