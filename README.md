# DevFlow

GraphRAG-powered engineering intelligence agent for a PR/code-review
platform — trace risk, ownership, and incidents through a live Neo4j
knowledge graph, answering questions like "who should review this file" or
"what could break if I change this" by traversing real relationships
between commits, PRs, reviews, deployments, and incidents.

Full architecture, locked schema, and design rationale live in
[`CLAUDE.md`](CLAUDE.md) and [`MDs/`](MDs) — this file is a practical
quickstart, not the spec.

## Status

Both pipelines described in `CLAUDE.md` §2 are implemented:

- **Knowledge graph construction** (`extraction/`, `graph/`) — raw text →
  LangGraph-orchestrated LLM extraction, schema-validated against the
  locked 11 entity types / 18 relationship types → Neo4j, with a native
  vector `embedding` property and a per-label vector index on every node.
- **Query-time retrieval** (`retrieval/`) — a natural-language question →
  LLM entity/intent extraction → typed vector entry-point search → a
  confidence check → LLM-generated, schema-constrained, validated Cypher
  → graph traversal → evidence assembly → LLM answer synthesis, with a
  flat vector-search fallback when entry-point confidence is low or a
  query comes back empty.

MCP tooling, LangGraph-based agent orchestration on top of this, and AWS
deployment are still deferred (`CLAUDE.md` §9).

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # then fill in NEO4J_PASSWORD and GEMINI_API_KEYS
docker compose up -d   # starts Neo4j (bolt://localhost:7687, browser on :7474)
```

`.env` needs:

- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` — Neo4j connection
- `GEMINI_API_KEYS` — comma-separated Gemini API keys (round-robined
  across for rate-limit failover, see `helper/gemini_key_pool.py`).
  The Gemini free tier caps `gemini-3.6-flash` at 20 requests/day per
  Google Cloud project — rotating keys within the *same* project does not
  raise this, since the quota is per-project, not per-key.
- `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`
  (optional) — LangSmith tracing for every LLM call in both pipelines.

## Usage

```bash
# One-time: uniqueness constraints + vector indexes for all 11 entity types
python -m graph.constraints

# Load the hand-authored seed dataset (no LLM calls, deterministic)
python -m graph.seed

# Extract entities/relationships from raw text and load into Neo4j
python -m graph.cli "Maria opened PR-142 fixing a token refresh bug..."

# Ask a question against the graph
python -m retrieval.cli "Which developer was involved in the PR \
that introduced the change related to incident INC-089?"
```

## Project layout

- `extraction/` — knowledge-graph-construction pipeline: LangGraph
  extraction with schema-violation retry, structured Pydantic output.
- `graph/` — Neo4j connection, constraints/vector indexes, the
  idempotent loader, embeddings (Gemini, cached in Neo4j itself so
  re-loading the same entities never re-embeds them).
- `retrieval/` — query-time LangGraph pipeline: entity/intent extraction,
  typed entry-point search, Cypher generation + five-check validation,
  evidence assembly, fallback text search, answer synthesis.
- `helper/` — shared Gemini API key pool (round-robin, rate-limit
  failover).
- `data/` — the hand-authored seed dataset.
- `MDs/` — locked design docs (schema, tech stack, retrieval strategy,
  worked traces).
- `plans/` — implementation plans for each phase as they were built.
- `tests/` — pytest suite (`pytest tests/`); live end-to-end retrieval
  tests are gated behind `RUN_LIVE_E2E=1` to protect the Gemini daily
  quota.

## Research paper referred

- <https://arxiv.org/abs/2404.17723>
