# GraphRAG Query-Time Retrieval — `retrieval/` package

## Context

Knowledge-graph construction (`extraction/`, `graph/`) is done: raw text →
LangGraph-orchestrated LLM extraction → schema-validated entities/relationships →
Neo4j, with a native vector `embedding` property + per-label vector index on
every node (11 indexes, `gemini-embedding-001`, 3072-dim, cosine). Nothing
answers a question yet. This plan builds the query-time half: a LangGraph
pipeline that takes a natural-language question, finds an entry point in the
existing graph via the existing embeddings, has an LLM write a scoped Cypher
query, validates it, executes it, and synthesizes an answer from the
resulting evidence — falling back to flat vector search over free text when
graph retrieval isn't confident or comes up empty. This is `retrieval/` from
CLAUDE.md §7, previously just a proposed, unbuilt directory.

**Verification against CLAUDE.md** (the user asked for this explicitly):
- §5/§6/CLAUDE.md's Cypher-LLM doc is followed as authoritative for the
  five-check validator, the Cypher-gen prompt shape, and fallback triggers.
- §8's known gaps are closed by design, not left open: the read-only denylist
  gap (`LOAD CSV`, `CALL`, `apoc.*`/`dbms.*`) is fixed by rejecting `CALL`
  and `LOAD CSV` outright (schema-only queries never need them); the
  permission-path shorthand is not used — the real path
  `(Developer|Team)-[:HAS_PERMISSION]->(Permission)<-[:PROTECTED_BY]-(Repository)`
  is what few-shot examples and the coverage mapping use.
- §8's **reranker-position item is explicitly unresolved and flagged
  "settle before building retrieval/."** Per your answer: **skipped for this
  implementation** — the multi-factor confidence check (similarity + margin +
  type match) substitutes for it, and the LangGraph design leaves an
  explicit node slot (`rerank_candidates`, currently a no-op passthrough)
  so a reranker can be dropped in later without restructuring the graph.
- §9 lists LangGraph as deferred "until the agent phase starts" — but
  `extraction/graph.py` **already** builds and runs a real LangGraph
  `StateGraph` (with a retry loop) today. This is a doc/reality mismatch,
  not a blocker: this plan follows the codebase's actual established
  pattern (LangGraph for stateful, branching pipelines) rather than the
  stale doc text. Worth a one-line CLAUDE.md §9 correction at some point,
  not part of this plan's scope.
- LangChain stays "structured output only" per §6 — no LangChain
  orchestration, no `ChatGoogleGenerativeAI`/`langchain_openai` (unused,
  aspirational deps per the research). All LLM calls go through the same
  pooled-Gemini pattern already in production use.

## Proposed architecture

```
START
  → extract_query            (LLM: entities/relationships/intent/search terms)
  → retrieve_entry_points     (embed search terms, query typed vector index(es))
  → check_confidence          (pure scoring, no LLM)
      ├─ low  → fallback_search
      └─ high → generate_cypher
                   → validate_cypher
                       ├─ invalid, retries left → generate_cypher (with error feedback)
                       ├─ invalid, no retries    → fallback_search
                       └─ valid                  → execute_graph_query
                                                      → check_results
                                                          ├─ empty → fallback_search
                                                          └─ rows  → assemble_evidence
  → (assemble_evidence | fallback_search) → synthesize_answer → END
```

This matches the user's target shape, plus one addition already precedented
by `extraction/graph.py`: a **Cypher retry loop** (generate → validate →
regenerate-with-feedback, capped at `MAX_CYPHER_ATTEMPTS = 2`), mirroring
extraction's `MAX_ATTEMPTS = 2` retry-on-schema-violation pattern. This is
explicitly one of the "later" extensions the user asked to not have to
rewrite the architecture for (item 12) — building it in now costs almost
nothing since the loop shape already exists as precedent.

## LangGraph state design

`retrieval/state.py`, mirroring `extraction/graph.py`'s `ExtractionState`
(plain `TypedDict`, no checkpointer — stateless per-request, same as
extraction):

```python
class RetrievalState(TypedDict):
    question: str

    # extract_query
    extraction: QueryExtraction | None      # see models.py below

    # retrieve_entry_points / check_confidence
    candidates: list[EntryPointCandidate]
    entry_point: EntryPointCandidate | None
    confidence: float
    route: Literal["graph", "fallback"] | None

    # generate_cypher / validate_cypher
    cypher: str | None
    cypher_attempt: int
    cypher_error: str | None                # fed back into the retry prompt

    # execute_graph_query / check_results
    raw_records: list[dict] | None

    # assemble_evidence / fallback_search
    evidence: EvidenceBundle | None

    # synthesize_answer
    answer: AnswerResult | None
```

## Pydantic models — `retrieval/models.py`

```python
class QueryExtraction(BaseModel):
    entities: list[str]                       # raw mentions, e.g. "src/auth.py"
    entity_types: list[EntityType] = []       # inferred, optional — may be empty
    relationships: list[str] = []             # free-text relation hints
    intent: str                               # one of the 10 coverage-table intents
    search_terms: list[str]                   # what to embed for entry-point search

class EntryPointCandidate(BaseModel):
    node_id: str
    node_type: EntityType
    score: float                              # cosine similarity from Neo4j
    properties: dict[str, str]

class EvidenceItem(BaseModel):
    node_id: str
    node_type: EntityType
    properties: dict[str, str]

class EvidencePath(BaseModel):
    nodes: list[EvidenceItem]
    relationships: list[tuple[str, RelationType, str]]  # (source_id, rel, target_id)

class EvidenceBundle(BaseModel):
    source: Literal["graph_traversal", "fallback_text_search"]
    entry_point: EvidenceItem | None
    paths: list[EvidencePath]
    text_snippets: list[str]                  # description/root_cause/message/comment pulls
    confidence: float
    cypher_used: str | None

class AnswerResult(BaseModel):
    answer: str
    source: Literal["graph_traversal", "fallback_text_search"]
    has_sufficient_evidence: bool
    cited_entity_ids: list[str]
```

`entities`/`relationships` as free-text (not forced into `EntityType`/
`RelationType` at extraction time) matches the reality that the question's
own phrasing rarely names a type explicitly — type inference is
best-effort (`entity_types` can be empty), and `check_confidence` handles
the "type unknown" case by searching multiple indexes (see below) rather
than requiring the LLM to guess correctly. `QueryExtraction.intent` is a
free string, not a locked enum — validated loosely against the 10
coverage-table intent names in the prompt, not hard-enforced in code, so
a novel question phrasing doesn't get rejected outright the way a
Cypher validation failure would.

## Node responsibilities

**`extract_query`** (`retrieval/nodes/extract.py`) — LLM call via
`extraction.llm.get_llm().with_structured_output(QueryExtraction)`. System
prompt built the same way `extraction/prompts.py` builds its schema
vocabulary block (see "shared schema-text" refactor below), listing the 11
entity types and asking for best-effort type inference, plus a short
instruction on what "intent" and "search_terms" mean, seeded with the 10
coverage-table question-type names as guidance (not a hard enum). On LLM
failure, returns a degraded `QueryExtraction(entities=[], intent="unknown",
search_terms=[question])` rather than raising — routes downstream into a
low-confidence/fallback path automatically instead of crashing the request.

**`retrieve_entry_points`** (`retrieval/nodes/entry_points.py`) — embeds
`extraction.search_terms` (joined) via `graph.embeddings.embed_texts` (the
**existing** embedding pipeline — no second embedding model/index is
created, satisfying requirement 4 directly). Determines which per-label
vector indexes to query:
- If `extraction.entity_types` is non-empty, query only those labels'
  indexes (`{label.lower()}_embedding_index`, the exact naming scheme
  `graph/constraints.py` already uses).
- If empty, query **all 11** indexes (cheap: one `db.index.vector.queryNodes`
  call per label, top-3 each) and merge.
Returns up to ~10 `EntryPointCandidate`s across whichever indexes were hit,
sorted by score.

**`check_confidence`** (`retrieval/nodes/confidence.py`) — pure Python, no
LLM/DB call. Scoring combines: top-1 cosine score, the margin to the
runner-up (`score_1 - score_2`, defends against ambiguous ties across
different node types), and a small bonus if `entry_point.node_type` is in
`extraction.entity_types` (when non-empty). Accept if
`top_score >= 0.75 and margin >= 0.05`, or unconditionally if
`top_score >= 0.90`. These two thresholds are named constants at the top of
the module — **flagged for empirical tuning once real query traffic
exists**, not asserted as correct now. Sets `route = "graph"` or
`"fallback"` accordingly; this is the reranker's designated future slot —
a `rerank_candidates` node would sit between `retrieve_entry_points` and
this node, re-scoring `candidates` before the same threshold logic runs
unchanged.

**`generate_cypher`** (`retrieval/nodes/cypher_generation.py`) — LLM call
building the exact prompt shape from `MDs/DevFlow-Cypher-LLM.md` §3: fixed
schema vocabulary (11 labels, 18 relationship types, generated from
`extraction/schema.py` via the shared helper, not hand-copied), the
resolved `entry_point` (type + id), `extraction.intent`, and the original
question for context the doc's own template doesn't include but which
helps the LLM pick the right traversal shape from the coverage table. Two
prompt-shape changes from the doc, both deliberate hardening, called out
explicitly:
1. **Few-shot examples included from the first version**, not treated as
   later polish — three examples drawn directly from the coverage table,
   covering the three traversal shapes closest to the user's example
   queries (incident root-cause, deployment/incident connectivity,
   permission reasoning via the *real* path, not the shorthand).
2. **The entry point id is never inlined as a literal** in the generated
   Cypher. The prompt instructs the LLM to always anchor with
   `MATCH (n:{Label} {id_field: $entry_id})`, and `$entry_id` is bound as
   a driver parameter at execution time — stricter than the doc's own
   "safe because it comes from our search" rationale, since the LLM
   never even sees the raw id as a string to potentially mangle.
On retry (`cypher_attempt > 0`), the previous `cypher_error` (the specific
validator failure reason) is appended to the prompt, mirroring
`extraction/prompts.py`'s `RETRY_SUFFIX_TEMPLATE` pattern for retry
feedback.

**`validate_cypher`** (`retrieval/cypher_validator.py`) — the five checks
from `DevFlow-Cypher-LLM.md` §4, each closing a specific CLAUDE.md §8 gap:
1. *Read-only*: regex-strip string literals, then whole-keyword match
   (word boundaries, case-insensitive) against `CREATE|MERGE|DELETE|SET|
   REMOVE|DROP`. Additionally, **outright reject `CALL` and `LOAD CSV`**
   regardless of context — closes the exact gap CLAUDE.md §8 names
   (`apoc.*`/`dbms.*` procedure calls, `LOAD CSV`) by removing the
   category entirely rather than trying to denylist every dangerous
   procedure name.
2. *Schema whitelist*: regex-extract every `:Label` and `[:REL_TYPE]`
   token; reject if any isn't one of the 11 `EntityType`/18 `RelationType`
   values. (Full-triple validation against `ALLOWED_EDGES` for every hop
   in a multi-hop path is not attempted — flagged as a known limitation,
   not a silent gap, since path patterns don't map 1:1 to single triples.)
3. *Executability*: `session.run("EXPLAIN " + query, entry_id=..., ...)` —
   any exception is a validation failure with the exception message
   captured as `cypher_error` for the retry prompt.
4. *Resource limits*: reject unbounded variable-length paths (regex for
   `\*` inside a relationship pattern with no upper bound, e.g. `-[*]-` or
   `-[:REL*]-` without `..N`); execute with the Neo4j driver's per-query
   timeout (`session.run(query, ..., timeout=5)`); cap rows read from the
   result to 200 regardless of what the query would otherwise return.
5. *Parameter safety*: enforced structurally by construction (see
   `generate_cypher` above) — `$entry_id` is always a bound parameter, so
   there's nothing left for this check to verify beyond confirming the
   query actually references `$entry_id` somewhere.
Returns `(is_valid: bool, error: str | None)`.

**`execute_graph_query`** (`retrieval/nodes/execute.py`) — runs the
validated query with `entry_id`/`entry_label` bound, via
`graph.connection.get_driver()` (the existing singleton — no new driver
setup). Catches Neo4j driver exceptions (timeout, connection errors) and
treats them identically to "empty results" downstream rather than
propagating.

**`check_results`** — pure routing: `raw_records` empty → fallback,
otherwise → `assemble_evidence`.

**`assemble_evidence`** (`retrieval/evidence.py`) — converts raw Neo4j
records (nodes + relationships from the `OPTIONAL MATCH` pattern the
Cypher used) into `EvidencePath`s, pulling every node's full property
dict (so free-text fields — PR `description`, `root_cause`/`resolution`,
commit `message`, review `comment` — travel with the structured facts,
not just IDs, satisfying requirement 9) and formatting a compact string
(node/relationship bullet list + text snippets) for the synthesis prompt,
the same "connected PATH, not a flat fact list" shape `DevFlow-Workflow-1.md`
step 7 specifies.

**`fallback_search`** (`retrieval/fallback.py`) — flat vector search
reusing the **same existing indexes**, not a new flat index: embeds
`extraction.search_terms`, queries the free-text-bearing indexes
specifically (`pullrequest`, `commit`, `incident`, `review` — the four
`build_embedding_text` branches with real prose per `graph/embeddings.py`),
merges by score, takes top ~5, wraps as an `EvidenceBundle(source=
"fallback_text_search", confidence=<top score>)`. This satisfies "the
system should support the existing fallback to flat text/vector search"
without standing up Chroma/pgvector (both present in `requirements.txt`
but unused — confirmed via research; not touched by this plan).

**`synthesize_answer`** (`retrieval/synthesize.py`) — LLM call via
`extraction.llm.get_llm().with_structured_output(AnswerResult)`, strict
prompt: "answer using only the evidence below; if it's insufficient, set
`has_sufficient_evidence=false` and say so explicitly — never guess,"
directly implementing requirement 11 and `DevFlow-Workflow-1.md` step 8.
`source` is copied from the evidence bundle so every answer is tagged
graph-traversal vs. fallback, per CLAUDE.md §5's transparency requirement.

## Conditional edges / routing functions

All routing functions are plain, testable Python (no LLM), following
`extraction/graph.py`'s `_route_after_validate` pattern exactly:

```python
def _route_after_confidence(state) -> str:
    return "graph" if state["route"] == "graph" else "fallback"

def _route_after_validate(state) -> str:
    if state["cypher"] is not None:                 # validator marked it valid
        return "execute"
    if state["cypher_attempt"] < MAX_CYPHER_ATTEMPTS:
        return "retry"
    return "fallback"

def _route_after_results(state) -> str:
    return "assemble" if state["raw_records"] else "fallback"
```

## Shared schema-text refactor (small, cross-cutting)

`extraction/prompts.py` currently builds its `_EDGE_LINES`/entity-type list
privately, inline. Pulled out into `extraction/schema_text.py`
(`EDGE_LINES: str`, `ENTITY_TYPES_LINE: str`, `ID_FIELD_LINES: str`,
computed once at import from `extraction/schema.py` — identical values,
just relocated so `retrieval/prompts.py` can import the same constants
instead of recomputing/duplicating the vocabulary block. `extraction/prompts.py`
updated to import from here instead of building its own; behavior
unchanged, verified by re-running the existing extraction smoke test
(`python -m graph.cli "..."`) unchanged.

## Files to create / modify

New:
- `retrieval/__init__.py`
- `retrieval/state.py` — `RetrievalState` TypedDict
- `retrieval/models.py` — Pydantic models above
- `retrieval/prompts.py` — extraction/cypher-gen/synthesis prompts + the
  3 few-shot Cypher examples
- `retrieval/nodes/__init__.py`, `extract.py`, `entry_points.py`,
  `confidence.py`, `cypher_generation.py`, `execute.py`
- `retrieval/cypher_validator.py` — the 5-check validator
- `retrieval/evidence.py` — evidence assembly
- `retrieval/fallback.py` — flat vector fallback
- `retrieval/synthesize.py` — final answer node
- `retrieval/graph.py` — `RetrievalState`, node registration, conditional
  edges, `build_retrieval_graph()` + `answer_question(question: str) ->
  AnswerResult`, `@traceable`-wrapped like `extraction.graph.extract`
- `retrieval/cli.py` — `python -m retrieval.cli "question"`, mirrors
  `graph/cli.py`/`extraction/cli.py`'s `_read_input` pattern
- `extraction/schema_text.py` — shared vocabulary-text helper (see above)
- `tests/__init__.py`, `tests/test_retrieval_routing.py`,
  `tests/test_entry_points.py`, `tests/test_cypher_validator.py`,
  `tests/test_evidence.py`, `tests/test_retrieval_e2e.py` — first real use
  of the `tests/` directory CLAUDE.md §7 already proposes

Modified:
- `extraction/prompts.py` — import vocabulary blocks from
  `extraction/schema_text.py` instead of building them inline

No changes to `graph/embeddings.py`, `graph/loader.py`, `graph/constraints.py`,
`graph/connection.py`, `helper/gemini_key_pool.py`, or `.env` — everything
retrieval needs (driver singleton, embedding function, index names, pooled
LLM factory) already exists and is reused as-is, per your answer on LLM
factory reuse.

## Testing strategy

- **Routing unit tests** (`test_retrieval_routing.py`): call
  `_route_after_confidence`/`_route_after_validate`/`_route_after_results`
  directly with hand-built `RetrievalState` dicts covering every branch
  (high/low confidence, valid/invalid-with-retries/invalid-exhausted,
  empty/non-empty records) — no LLM, no DB, pure logic.
- **Confidence scoring** (`test_entry_points.py`): feed hand-built
  candidate lists (clear winner, close tie, single low-score candidate,
  empty list) into the scoring function and assert accept/reject at the
  threshold boundaries.
- **Cypher validator** (`test_cypher_validator.py`): table-driven — one
  case per check, including the exact gaps CLAUDE.md §8 names (`LOAD CSV`,
  a bare `CALL apoc.load.json(...)`, an invented relationship like
  `DEPENDS_ON`, an unbounded `-[*]-`, a query missing `$entry_id`, a
  syntactically broken query) plus a handful of known-good queries (the
  three few-shot examples) that must all pass.
- **Evidence assembly** (`test_evidence.py`): feed a hand-built Neo4j
  record shape (nodes + rels as the driver would return them) and assert
  the resulting `EvidenceBundle` preserves every free-text property.
- **End-to-end** (`test_retrieval_e2e.py`), against the seeded dataset
  already loaded in the running Neo4j container from prior work: the
  user's three example queries —
  1. *"Which developer was involved in the PR that introduced the change
     related to incident INC-089?"* → expect `dev-maria` cited, via
     Incident ← Deployment ← Commit ← Developer / PullRequest CREATES.
  2. *"What incidents are connected to repo-devflow-core through
     deployments or CI failures?"* → expect `INC-089` cited.
  3. *"Who has permission to modify repo-devflow-core and what team are
     they part of?"* → expect the real
     `HAS_PERMISSION`→`Permission`←`PROTECTED_BY` path used (not the
     shorthand), `team-platform` cited.
  These make real Gemini + real Neo4j calls (consistent with how
  `graph/seed.py`/`graph/cli.py` were verified earlier in this project —
  no mocking infra exists yet for the pooled Gemini client) and assert on
  `answer.source` and `answer.cited_entity_ids`, not exact wording.

## Error handling / fallback summary

Every failure mode routes to `fallback_search` or a bounded retry, never a
raised exception reaching the caller: extraction LLM failure → degraded
extraction → low confidence → fallback; zero vector candidates → confidence
0 → fallback; Cypher generation/validation failure → retry once, then
fallback; Neo4j execution error/timeout → treated as empty results →
fallback; fallback itself finding nothing → synthesis explicitly reports
insufficient evidence rather than guessing (requirement 11).

## Assumptions, ambiguities, and open decisions

- **Confidence thresholds (0.75/0.05/0.90) are placeholder constants**,
  not derived from real eval data — no ground-truth query set exists yet
  to tune against. Flagged in-code as needing calibration once there's
  usage to measure against.
- **Multi-hop Cypher validation is type/relationship-whitelist only**,
  not full-path-against-`ALLOWED_EDGES` checking — a syntactically valid
  query using only real labels/relationships but chaining them in a
  triple that isn't actually one of the 27 locked edges would still pass
  validation and simply return nothing at execution (routes to fallback
  via `check_results`, so it fails safe, just not at the validation
  stage where the doc's failure-mode table implies it should).
- **Intent is a free string, not a locked enum** — deliberate (question
  phrasing is too varied to force into 10 buckets reliably), but means
  "intent" is advisory context for the Cypher-gen prompt, not something
  the router branches on directly.
- **No new tests/ conventions exist yet** — this plan's test files are the
  first inhabitants of that directory; pytest config/fixtures (e.g. a
  shared Neo4j-session fixture) are being introduced here, not following
  an established local pattern.
- **The CLAUDE.md §9 LangGraph-deferred text vs. `extraction/graph.py`'s
  actual LangGraph usage is a real inconsistency** worth a doc fix at
  some point — not addressed by this plan beyond noting it, since editing
  locked spec docs wasn't asked for.
