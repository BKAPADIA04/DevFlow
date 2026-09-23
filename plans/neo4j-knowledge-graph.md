# Neo4j Knowledge Graph — Phase 1 (entities & relationships, via Docker)

## Context

DevFlow now has a working extraction pipeline (`extraction/schema.py`,
`extraction/graph.py`, `extraction/llm.py`, `extraction/cli.py`,
`extraction/prompts.py`) that turns raw text (PR descriptions, commit
messages, incident notes, etc.) into schema-validated entities and
relationships (an `ExtractionResult` of `ExtractedEntity` /
`ExtractedRelationship`), locked to the 11 entity types / 18 relationship
types / 27 edges defined in `MDs/DevFlow-Relationships.md`. That result
currently just prints as JSON — nothing persists it.

The next step (this plan) is to stand up a real Neo4j graph database via
Docker and write a loader that takes the extraction pipeline's output and
turns it into actual nodes and edges — i.e. "make a knowledge graph of the
entities and relationships." A later, separate phase will add Neo4j's
native vector index for embeddings (explicitly out of scope here — this
plan does not touch that, but nothing in it blocks adding it later).

Environment already confirmed: no `graph/`, `data/`, or `docker/` folder
exists yet; no Docker config exists yet; `requirements.txt` has no Neo4j
driver; `.env` has no Neo4j vars yet; Docker Desktop + Compose v2 are
installed and working on this machine; `MDs/DevFlow-TechStack.md` gives no
concrete Neo4j config (image, ports, env vars) — all of that is decided
fresh here.

**Loader-level decision on the known ID-format doc inconsistency**
(CLAUDE.md §8 — the schema doc's own ID examples disagree with its own
sample data): the loader does not attempt to normalize or enforce any
particular ID string shape. It treats whatever `id` (or `hash`, for
`Commit`) string the extraction pipeline actually produced as the
authoritative `MERGE` key, verbatim. That's a loader-level pragmatic
choice, not a fix to the doc inconsistency itself.

## Implementation

### 1. Docker — `docker-compose.yml` (repo root)

Neo4j Community Edition, pinned to `neo4j:5.26.0-community` (current 5.x
LTS line — reproducible, avoids the bigger jump in `neo4j:latest`, which
now tracks calendar-versioned 2025.x releases).

```yaml
services:
  neo4j:
    image: neo4j:5.26.0-community
    container_name: devflow-neo4j
    ports:
      - "7474:7474"   # Browser HTTP
      - "7687:7687"   # Bolt
    environment:
      NEO4J_AUTH: ${NEO4J_USER}/${NEO4J_PASSWORD}
      NEO4J_PLUGINS: "[]"          # no APOC in Phase 1
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    healthcheck:
      test: ["CMD-SHELL", "wget -O /dev/null -q http://localhost:7474 || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 10

volumes:
  neo4j_data:
  neo4j_logs:
```

Compose auto-loads `.env` from the repo root and substitutes
`${NEO4J_USER}`/`${NEO4J_PASSWORD}` — no secrets in the compose file
itself. Named volumes (not a bind-mounted `data/` folder) keep DB storage
out of the repo tree and avoid colliding with `data/` as proposed
elsewhere for sample entity JSON.

**Add to `.env`** (append, don't replace):

```text
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<pick 8+ chars — Neo4j 5 rejects the plaintext default>
```

### 2. `graph/` package

```text
graph/
├── __init__.py
├── connection.py     # driver singleton
├── constraints.py    # uniqueness constraints, derived from extraction/schema.py
├── loader.py          # ExtractionResult -> Neo4j writes
└── cli.py             # extract(text) -> load_extraction_result(...)
```

No `graph/schema.py` — deliberately not recreated. `EntityType`,
`RelationType`, `ALLOWED_EDGES`, and `ID_FIELD_BY_TYPE` already live in
`extraction/schema.py` and are imported directly, so the loader can never
drift from the same locked schema the extractor validates against.

**`graph/connection.py`** — mirrors `extraction/llm.py`'s pattern (loads
`.env` at import time, one lazy singleton), using the official `neo4j`
driver directly (not a LangChain wrapper), consistent with CLAUDE.md §6
("LangChain used narrowly... only for structured output"):

```python
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_DRIVER: Driver | None = None


def get_driver() -> Driver:
    global _DRIVER
    if _DRIVER is None:
        _DRIVER = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
        )
    return _DRIVER


def close_driver() -> None:
    global _DRIVER
    if _DRIVER is not None:
        _DRIVER.close()
        _DRIVER = None
```

**`graph/constraints.py`** — one uniqueness constraint per entity label,
derived straight from `EntityType` + `ID_FIELD_BY_TYPE` (no hand-kept
label list):

```python
from extraction.schema import ID_FIELD_BY_TYPE, EntityType
from graph.connection import get_driver

_CONSTRAINT_TEMPLATE = (
    "CREATE CONSTRAINT {name} IF NOT EXISTS "
    "FOR (n:{label}) REQUIRE n.{field} IS UNIQUE"
)


def ensure_constraints() -> None:
    driver = get_driver()
    driver.verify_connectivity()
    with driver.session() as session:
        for entity_type in EntityType:
            label = entity_type.value
            field = ID_FIELD_BY_TYPE[entity_type]
            name = f"{label.lower()}_{field}_unique"
            session.run(_CONSTRAINT_TEMPLATE.format(name=name, label=label, field=field))
```

`label`/`field` are enum-sourced, never user input, so the f-string into
Cypher here is safe templating, not an injection risk. `IF NOT EXISTS`
makes this idempotent — safe to call every run.

**`graph/loader.py`** — the core piece.

- **Idempotency**: every write is `MERGE` keyed on label + id field.
  Re-running the same (or overlapping) `ExtractionResult` never
  duplicates nodes/relationships.
- **Properties**: `list[EntityProperty]` → flat `dict[str, str]` via
  `{p.key: p.value for p in entity.properties}`, then `SET n += $props`
  (merges into existing properties rather than replacing the node).
- **Relationship type in Cypher**: Neo4j requires the relationship type
  as a literal in the query, not a bound parameter. Since APOC is out of
  scope for Phase 1, the loader groups `ExtractedRelationship`s by
  `(relation, source_type, target_type)` — necessary because some
  relation types (e.g. `CONTAINS`) appear with more than one
  source/target pair in the locked 27 edges — and runs one query per
  group with the label/relation substituted from the enum (same
  safety argument as constraints.py).
- **Batching**: one `session.run()` per entity; relationships batched
  with `UNWIND` *within* each `(relation, source_type, target_type)`
  group (not full multi-entity batching) — correctness/readability over
  performance for this MVP, since each `ExtractionResult` comes from a
  single paragraph of text and is small. Easy to extend to full
  `UNWIND`-batched entity writes later if bulk seeding is ever added.

Node merge (per entity):

```cypher
MERGE (n:{label} {{{id_field}: $id}})
SET n += $props
```

Relationship merge (per `(relation, source_type, target_type)` group):

```cypher
UNWIND $rows AS row
MATCH (src:{source_label} {{{source_id_field}: row.source_id}})
MATCH (tgt:{target_label} {{{target_id_field}: row.target_id}})
MERGE (src)-[r:{relation}]->(tgt)
```

Top-level:

```python
def load_extraction_result(result: ExtractionResult) -> None:
    driver = get_driver()
    with driver.session() as session:
        for entity in result.entities:
            _merge_entity(session, entity)
        by_group: dict[tuple, list[ExtractedRelationship]] = defaultdict(list)
        for rel in result.relationships:
            by_group[(rel.relation, rel.source_type, rel.target_type)].append(rel)
        for (relation, source_type, target_type), rels in by_group.items():
            _merge_relationships(session, relation, source_type, target_type, rels)
```

Entities are all merged before any relationship pass, so `MATCH` can
always find both endpoints extracted in the same call. A relationship
whose endpoint wasn't extracted as an entity simply matches nothing and
silently creates no edge — acceptable for Phase 1.

**`graph/cli.py`** — chains extraction → constraints → load, reusing
`extraction.cli._read_input` (argv text / file path / interactive
prompt) rather than duplicating it:

```python
"""
Usage:
    python -m graph.cli "some PR description or incident text"
    python -m graph.cli path/to/text_file.txt
    python -m graph.cli            # prompts for input interactively
"""
import json
import sys

from extraction.cli import _read_input
from extraction.graph import extract
from graph.constraints import ensure_constraints
from graph.loader import load_extraction_result


def main() -> None:
    text = _read_input(sys.argv[1:])
    if not text:
        print("No input text provided.")
        return

    result = extract(text)
    print(json.dumps(result.model_dump(mode="json"), indent=2))

    ensure_constraints()
    load_extraction_result(result)
    print(
        f"Loaded {len(result.entities)} entities and "
        f"{len(result.relationships)} relationships into Neo4j."
    )


if __name__ == "__main__":
    main()
```

### 3. `requirements.txt`

Add one line: `neo4j` (official driver). Leave `langchain-chroma` /
`pgvector` alone — out of scope for this plan even though they look like
stale leftovers from an earlier vector-store design.

### 4. Visualization — Neo4j Browser (no new tooling needed)

The `docker-compose.yml` in §1 already exposes port `7474`, which is
Neo4j's built-in web UI ("Neo4j Browser") — it renders query results as
an interactive node/edge graph out of the box, so no extra dependency,
service, or code is needed to visualize what the loader writes.

After `docker compose up -d`:

1. Open `http://localhost:7474` in a browser.
2. Log in with `NEO4J_USER` / `NEO4J_PASSWORD` from `.env`.
3. Run a Cypher query and it renders as a graph automatically, e.g.:

   ```cypher
   MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 200
   ```

   or scoped to what one `graph/cli.py` run just loaded, e.g. everything
   touching a given `PullRequest`:

   ```cypher
   MATCH (pr:PullRequest {id: "PR-142"})-[*1..2]-(connected)
   RETURN pr, connected
   ```

Nodes are color-coded by label and relationships are drawn as directed,
labeled edges automatically — no configuration required. This covers
"visualize the graph" for Phase 1; if a project-embedded visualization
(e.g. rendered inside an internal dashboard rather than opening Neo4j
Browser separately) is wanted later, that would be a small addition on
top of the `neo4j` driver already in place (e.g. a `graph/export.py` that
dumps a subgraph to a JSON/D3 format for a custom front end) — not
needed for this phase, since Browser already covers it for free.

## Verification (automated checks; see §4 above for interactive visualization)

1. `docker compose up -d` then `docker compose ps` — confirm the
   `devflow-neo4j` service is healthy.
2. `python -m graph.constraints` — should run without error (creates the
   11 uniqueness constraints).
3. `python -m graph.cli "Maria (dev-maria) opened PR-142 'Fix token
   refresh bug' against repo-devflow-core, targeting main, containing
   commit commit-a1b2c3d which modifies src/auth.py. Dan (dev-dan)
   reviewed it and requested changes (REV-501). CI run CI-901 tested
   commit-a1b2c3d and failed. It was still deployed as DEPLOY-034 to
   production, and later caused incident INC-089 (severity SEV2)."` —
   prints the extracted JSON, then a "Loaded N entities and M
   relationships" line.
4. Verify via the driver directly (small ad hoc script or `python -c`
   using `graph.connection.get_driver()`):

   ```python
   from graph.connection import get_driver
   driver = get_driver()
   with driver.session() as session:
       print(session.run(
           "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY label"
       ).data())
       print(session.run(
           "MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS n ORDER BY rel"
       ).data())
   ```

   Expect labels like `Repository`, `Commit`, `PullRequest`, `Developer`
   (x2), `Review`, `CIRun`, `Deployment`, `Incident`, and relationship
   types like `CONTAINS`, `CREATES`, `AUTHORED`, `MODIFIES`, `PERFORMS`,
   `RECEIVES`, `TRIGGERS` (x2), `RELATED_TO`, `TESTS`, `MAY_CAUSE`.
5. Re-run step 3 unchanged, re-check step 4 — counts must be identical,
   not doubled. This is the concrete proof `MERGE` (not `CREATE`) is
   working as intended.

## Summary of new/changed files

- `plans/neo4j-knowledge-graph.md` (this file)
- `docker-compose.yml` (new, repo root)
- `.env` (edit — add `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`)
- `graph/__init__.py`, `graph/connection.py`, `graph/constraints.py`,
  `graph/loader.py`, `graph/cli.py` (new)
- `requirements.txt` (edit — add `neo4j`)

## Explicitly out of scope (Phase 2, later)

Neo4j's native vector index for embeddings. Nothing in this plan blocks
adding a `graph/vector_index.py` module later.
