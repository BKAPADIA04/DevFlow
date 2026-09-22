# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## 1. Project overview

DevFlow is a GraphRAG-powered engineering intelligence agent for a PR/code-review
platform. It traces risk, ownership, and incidents through a live Neo4j knowledge
graph built from GitHub/GitLab/CI/incident data, answering questions like "who
should review this file" or "what could break if I change this" by traversing
real relationships between commits, PRs, reviews, deployments, and incidents —
rather than guessing from text similarity alone. The repo is currently at the
design stage: no application code exists yet, only locked specs in `MDs/` that
all future implementation (ingestion, graph loader, retrieval, MCP tools) must
conform to.

## 2. Architecture summary

Two pipelines, built once but run at different times:

- **Knowledge graph construction** (offline/batch): raw artifacts from
  GitHub/GitLab/CI/incident sources → LangChain + LLM entity/relationship
  extraction → Pydantic validation → entity resolution → written into Neo4j as
  both graph nodes/edges and vector-embedded text (Neo4j's native vector index,
  not a separate store).
- **Query-time retrieval + answering** (online, per-request): a question comes
  in → an LLM extracts entities + intent → a typed embedding search finds the
  graph entry-point node → **the LLM generates the Cypher query itself**,
  scoped to the locked schema → the query passes a strict validation layer →
  Neo4j executes it → results are assembled into an evidence path → a final
  LLM call synthesizes the answer from that evidence only. A reranker sits
  somewhere in this path; where exactly is unresolved (§8). If entry-point
  search or Cypher generation/validation fails at any point, the system falls
  back to flat embedding search over free text (PR descriptions, incident
  notes, commit messages) so a question is never met with a hard failure.

Full detail: `MDs/DevFlow-TechStack.md` (architecture diagrams),
`MDs/DevFlow-Cypher-LLM.md` (retrieval internals), `MDs/DevFlow-Workflow-1.md`
(worked end-to-end traces, including the fallback path).

## 3. Graph schema

**11 entity types, no others**: Repository, Commit, File, PullRequest,
Developer, Team, Review, CIRun, Deployment, Incident, Permission.

Several previously-considered entities (Branch, WebhookEvent, Artifact,
TestResult, Approval/ChangeRequest, Issue, Environment, Role) were
deliberately merged into properties on these 11 nodes rather than kept as
separate nodes/edges, because they added graph hops without adding reasoning
value — see the "What got merged into properties" table in
`MDs/DevFlow-Relationships.md` before ever reintroducing one of those as a
first-class entity.

**Relationships**, by source entity (full per-entity property schema, ID
fields, and one worked example of every edge live in
`MDs/DevFlow-Relationships.md` — not reproduced here):

| From | Relationships → To |
| --- | --- |
| Repository | CONTAINS → Commit, File, PullRequest · PROTECTED_BY → Permission |
| Developer | OWNS → Repository · CREATES → PullRequest · AUTHORED → Commit · PERFORMS → Review · BELONGS_TO → Team · HAS_PERMISSION → Permission |
| Team | OWNS → Repository, File · HAS_PERMISSION → Permission |
| PullRequest | MODIFIES → File · CONTAINS → Commit · RECEIVES → Review · TRIGGERS → CIRun, Deployment · RELATED_TO → Incident |
| Commit | PARENT_OF → Commit · MODIFIES → File · DEPLOYED_AS → Deployment |
| File | OWNED_BY → Developer, Team · REQUIRES_REVIEW_FROM → Team |
| CIRun | TESTS → Commit |
| Deployment | MAY_CAUSE → Incident |

That's 27 directed edges over 18 distinct relationship types. Two details
that bite when writing Cypher or the loader: `Commit` is keyed by `hash`,
every other node by `id`; and `Team OWNS File` / `File OWNED_BY Team` are
both real edges, so the loader must write both directions.

Do not make ad hoc additions to the entity/relationship set without first
updating `MDs/DevFlow-Relationships.md` — it is the locked reference every
future phase (data generation, graph loader, MCP tools) builds against. Any
schema change should also be checked against that file's coverage table,
which maps all 10 target question types (PR risk analysis, finding
reviewers, code ownership, historical PR analysis, CI failure investigation,
deployment impact analysis, incident root-cause, permission/approval
reasoning, finding similar past changes, impact of a proposed change) to a
concrete traversal path, so no question type silently becomes unanswerable.

## 4. Tech stack

| Layer | Technology |
| --- | --- |
| Language | Python 3.12+ |
| LLM Framework | LangChain (structured output only — see §6) |
| Workflow Orchestration | LangGraph *(deferred — see §9)* |
| LLM | OpenAI / Claude / Gemini API |
| Graph Database | Neo4j Community Edition |
| Graph Retrieval | Cypher + Neo4j Graph Queries |
| Vector Search | Neo4j native Vector Index (same DB, no separate vector store) |
| Embeddings | OpenAI / Gemini Embeddings API |
| Reranking | Cross-Encoder / Cohere Rerank |
| Knowledge Extraction | LangChain Structured Output + Pydantic |
| Entity Resolution | Semantic Search + Metadata Filtering + Reranking |
| Retrieval Style | Hybrid Graph + Vector Retrieval |
| API | FastAPI |
| Testing | Pytest |
| Containerization | Docker |
| MCP | MCP Server *(deferred — see §9)* |
| Version Control | Git + GitHub |

This is the v2 stack (cloud LLM + LangChain), a full switch from an earlier
local-only (Ollama) design. Detail and rationale: `MDs/DevFlow-TechStack.md`.

## 5. Retrieval strategy

Cypher queries are **LLM-generated per question, not fixed pre-written
functions**. The LLM is given, as its only allowed vocabulary, the 11 node
labels and 18 distinct relationship types from the locked schema — it
cannot reference anything else. The generated query then passes a five-check
validation layer, in order, before it may touch Neo4j:

1. **Read-only check** — reject any write keyword (`CREATE`, `MERGE`,
   `DELETE`, `SET`, `REMOVE`, `DROP`, write subqueries, APOC write procs).
   Match whole keywords outside string literals, not substrings — a naive
   match on `CREATE` rejects every query that reads `created_at`. The spec's
   denylist also has gaps (§8).
2. **Schema whitelist check** — every node label must be one of the 11 and
   every relationship type one of the 18.
3. **Syntax/executability check** — must pass Neo4j `EXPLAIN`.
4. **Resource limits** — query timeout (~5s), result size cap, reject
   unbounded variable-length paths.
5. **Parameter safety** — the starting entity id comes from our own
   entry-point search, never raw user text, so the LLM only supplies query
   *structure*, not untrusted string values.

Any failed check routes straight to the fallback: flat embedding search over
free text (PR descriptions, incident notes, commit messages). The fallback
also triggers if entry-point search itself can't find a confident graph node
for the question, or if a validated query executes but returns no results.
Every answer is tagged with its source (`graph traversal` vs
`fallback text search`) for transparency and evals. Full detail, including
the generation prompt template and failure-mode table:
`MDs/DevFlow-Cypher-LLM.md`; full request trace with worked examples:
`MDs/DevFlow-Workflow-1.md`.

## 6. Key design decisions and why

- **LLM-generated Cypher over fixed query functions (for now)**: trades some
  reliability for the ability to answer novel questions from day one without
  anticipating every question shape up front, and mirrors a validated,
  production-proven design (the LinkedIn GraphRAG paper). This is treated as
  a reversible decision — if evals show generation is unreliable for common
  question types, fixed functions can be reintroduced as the first-choice
  path with generation kept only as a fallback for novel questions.
- **Schema-constrained generation matters more than it looks**: giving the
  LLM the exact allowed label/relationship vocabulary up front is what makes
  generation *safe by design*, not just safe-by-validation — it sharply cuts
  how often the LLM invents a plausible but nonexistent relationship (e.g.
  `DEPENDS_ON`), which directly reduces the fallback rate.
- **Cloud LLM over local**: removes the local-model reliability risk
  specifically flagged for precise structured Cypher generation — frontier
  models are simply better at this than local models were.
- **LangChain used narrowly**: only for structured output (Pydantic-typed
  extraction), *not* as a tool-calling/agent orchestration framework yet —
  that distinction matters and shouldn't be assumed away when writing code.
- **Neo4j native vector index over a separate vector store**: removes an
  entire piece of infrastructure (Chroma/FAISS) with no loss of capability.
- **Reranker reinstated**: with a cloud LLM/embedding API already in the
  loop, the added latency/cost of reranking is proportionally smaller, and it
  improves entry-point accuracy.
- **Foreign-key-style properties kept alongside graph edges** (e.g.
  `Commit.author_id`, `Deployment.commit_hash`): intentional duplication —
  edges are what the query layer traverses, ID properties are what the
  loader script uses to build those edges and what supports direct lookups
  without a full traversal. Keep both when adding new entities/fields.

## 7. File structure

Proposed (not yet built) project layout, derived from the schema, stack, and
retrieval docs — see `MDs/DevFlow-FileStr-Potential.md` for the full tree and
rationale notes:

- `docs/` — the design docs currently living in `MDs/` at the repo root.
- `data/` — flat JSON entity records (`entities/`) and raw source text
  (`source_text/`) used to seed/build the graph.
- `graph/` — schema definition, Neo4j connection, the loader script, and
  vector index setup.
- `extraction/` — the knowledge-graph-construction pipeline: structured LLM
  extraction, entity resolution, edge writing.
- `retrieval/` — the query-time pipeline: entity/intent extraction,
  entry-point search, Cypher generation, the validator, graph traversal,
  fallback text search, and reranking. No fixed-function query files (e.g. a
  `get_blast_radius.py`) — that approach was explicitly replaced by
  LLM-generated Cypher.
- `synthesis/` — evidence assembly and final LLM answer synthesis.
- `api/` — FastAPI app and routes.
- `scripts/` — one-off tooling, e.g. seeding sample data.
- `tests/` — Pytest suite, one file per major pipeline stage.

## 8. Known open items / inconsistencies

- **Workflow-1 vs Cypher-LLM (retrieval approach)**: `MDs/DevFlow-Workflow-1.md`
  still describes an older fixed-function routing approach (step 4a routes to
  a hardcoded `get_blast_radius()` call). `MDs/DevFlow-Cypher-LLM.md`
  describes the current, superseding approach: the LLM generates the Cypher
  itself. **Treat `DevFlow-Cypher-LLM.md` as authoritative for retrieval
  logic wherever the two disagree** — `Workflow-1` is otherwise still useful
  for the overall flow shape (entity/intent extraction → entry-point search →
  confidence check → traversal → evidence assembly → synthesis) and the
  fallback-triggering logic, which are unchanged.
- **Local-LLM framing is stale in both flow/retrieval docs**: `Workflow-1`
  and `Cypher-LLM` were written assuming a local LLM (e.g. `Workflow-1`
  frames every LLM call as "local LLM"; `Cypher-LLM` §8 discusses "local
  model consideration" as a hard task for a local model). The stack has since
  moved to a cloud LLM API (`MDs/DevFlow-TechStack.md`). The mitigations
  described there (few-shot examples, retry-once-on-failure) are still good
  practice, just less critical than originally framed.
- **ID conventions disagree**: the schema gives `File.id` as
  `repo-devflow-core:src/auth.py` and keys `Commit` by `hash` (`a1b2c3d`), but
  the sample data and every Cypher example use `file-auth` and
  `commit-a1b2c3d`. Pick one before writing the loader and seed data —
  entry-point search and generated Cypher both depend on it.
- **Reranker position and "hybrid" retrieval are undefined**: the TechStack
  query-time diagram runs graph and vector retrieval in parallel and reranks
  the merged results, while its rationale says the reranker improves
  entry-point accuracy. Workflow-1 and Cypher-LLM use vector search only for
  entry-point lookup and the fallback, with no reranker. Settle this before
  building `retrieval/`.
- **Read-only denylist has gaps**: check 1 doesn't block `LOAD CSV` (fetches
  URLs, reads files) or read-typed procedure calls (`apoc.load.*`, `dbms.*`),
  and none of the other checks would catch them. The user's question does
  reach the LLM, so a prompt-injected question can shape query structure.
  Schema-only queries never need `CALL` or `LOAD CSV`, so reject both
  outright. Neo4j Community Edition has no role-based access control, so
  there's no read-only DB user to fall back on — the validator is the only
  boundary.
- **Coverage-table permission path is shorthand**: it reads
  `Developer/Team → HAS_PERMISSION → Repository`, but the real path is
  `(Developer|Team)-[:HAS_PERMISSION]->(Permission)<-[:PROTECTED_BY]-(Repository)`.
  Don't copy the shorthand into few-shot examples — it would pass validation
  and return nothing.
- **Stale filenames**: TechStack's "follow-on updates" section refers to
  `devflow-llm-cypher-retrieval.md` and `devflow-full-flow-with-fallback.md`;
  those are now `DevFlow-Cypher-LLM.md` and `DevFlow-Workflow-1.md`.
- **Most docs fail the lint command below**: only `DevFlow-Relationships.md`
  is clean. TechStack, Cypher-LLM, Workflow-1, FileStr-Potential, and
  `README.md` have ~90 errors between them, mostly untagged code fences and
  missing blank lines around headings and fences.
- **`docs/` referenced but doesn't exist yet**: `DevFlow-FileStr-Potential.md`
  and this file both reference a `docs/` folder for the design docs; today
  they live at `MDs/` in the repo root. No action needed until the file
  structure is actually built out.

## 9. What's deferred

Not part of the current build phase — don't introduce prematurely:

- MCP server / MCP client / the agentic tool-selection loop.
- LangGraph (stateful workflows, branching, retries) — added once the agent
  phase starts.
- AWS deployment.
- Fixed, pre-written Cypher query functions (e.g. `get_blast_radius()`) —
  LLM-generated Cypher + validation is the retrieval strategy for this phase;
  see §5–6 for why, and the reversibility condition under which fixed
  functions would come back.

## Linting

Markdown files are linted with `markdownlint-cli`:

```bash
npx markdownlint-cli "MDs/**/*.md" "*.md"
```

`.markdownlint.json` at the repo root disables `MD013` (line-length) inside
tables, since the schema/coverage tables in `MDs/DevFlow-Relationships.md`
contain real identifiers and property names that can't be wrapped without
breaking table syntax. Line-length is still enforced outside of tables, and
fenced code blocks must always have a language tag (`MD040`) — use `text`
for the plain-text diagrams/property listings in that file.
