# DevFlow web interface — ask, ingest, visualize

## Context

Everything so far (`extraction/`, `graph/`, `retrieval/`) is CLI-only
(`python -m graph.cli`, `python -m retrieval.cli`, `python -m graph.seed`).
There's no way to interact with the knowledge graph without a terminal, no
way to see the graph itself, and no way to add new source text without
re-running a CLI command. This plan adds a local web interface: a page to
ask questions against `retrieval.graph.answer_question`, a page to paste in
new raw text and have it flow through the existing extraction pipeline into
Neo4j, and a live view of the graph that refreshes after new data lands.
Explicitly **not** building the traversal-animation idea from earlier in
the conversation — that's dropped; this is a "decent interface," not a
visualization showpiece.

Per your answers: the frontend is a proper React app (npm/Vite, not plain
static HTML), the graph view is backend-proxied (FastAPI queries Neo4j via
the existing driver singleton and returns JSON — Neo4j credentials never
reach the browser), and "add new data" is free text through the existing
LLM extraction pipeline (not hand-authored JSON).

## Architecture

```
React (Vite, localhost:5173)
    │  fetch()
    ▼
FastAPI (api/main.py, localhost:8000)
    │
    ├─ POST /api/ask      → retrieval.graph.answer_question(question)
    ├─ POST /api/ingest   → extraction.graph.extract(text)
    │                        + graph.loader.load_extraction_result(result)
    └─ GET  /api/graph    → graph.connection.get_driver() query → JSON
                             {nodes: [...], edges: [...]}
```

All three endpoints are thin wrappers around pipelines that already exist
and are already verified working end-to-end — no new business logic, no
new LLM prompts, no new Cypher.

## Backend — `api/` (new)

**`api/main.py`** — one FastAPI app, three routes, CORS enabled for the
Vite dev server origin.

- `POST /api/ask` — body `{"question": str}`. Calls
  `retrieval.graph.answer_question(question)` and returns
  `AnswerResult.model_dump()` as-is. Same shape `retrieval/cli.py` already
  prints; the endpoint adds nothing beyond an HTTP wrapper.

- `POST /api/ingest` — body `{"text": str}`. Reuses
  `extraction.graph.extract`, `graph.constraints.ensure_constraints` +
  `ensure_vector_indexes` (both idempotent `IF NOT EXISTS`, safe to call
  every request), and `graph.loader.load_extraction_result` — exactly
  `graph/cli.py`'s `main()` body, minus the `print()`s, as a route. Returns
  the resulting `ExtractionResult.model_dump()` so the frontend can show
  what was actually added.

- `GET /api/graph?limit=300` — new read-only query, not a reuse of
  existing code (nothing today returns the graph as a JSON payload). Runs
  `MATCH (n) OPTIONAL MATCH (n)-[r]->(m) RETURN n, r, m LIMIT $limit`
  against `graph.connection.get_driver()`, then converts the returned
  `neo4j.graph.Node`/`Relationship` objects into plain JSON:
  `{"nodes": [{"id": ..., "label": ..., "properties": {...}}], "edges":
  [{"source": ..., "target": ..., "type": ...}]}`. Every node's
  `embedding` property (3072 floats) is stripped before serializing —
  the same `props.pop("embedding", None)` pattern already used in
  `retrieval/nodes/entry_points.py` and `retrieval/evidence.py`. `id` is
  `hash` for `Commit` nodes, `id` for everything else, matching
  `ID_FIELD_BY_TYPE` (`extraction/schema.py`).

`limit=300` is a placeholder cap, generous against the current ~20-node
seeded graph. Flagged here, not solved: once real ingestion grows the
graph past a few hundred nodes, this endpoint will need
filtering/pagination (by label, by recency, by neighborhood of a
searched node) — out of scope for this pass.

No new Python dependencies — `fastapi` and `uvicorn` are already in
`requirements.txt`; CORS middleware is built into FastAPI
(`fastapi.middleware.cors.CORSMiddleware`).

## Frontend — `frontend/` (new, Vite + React)

Scaffolded with `npm create vite@latest frontend -- --template react`,
entirely separate from the Python venv (its own `package.json`,
`node_modules/` already covered by the repo's existing `.gitignore`).

- **`src/api.js`** — thin `fetch` wrapper for the three endpoints, base
  URL from `VITE_API_BASE_URL` (default `http://localhost:8000`).
- **`src/components/AskPanel.jsx`** — a question input + submit, displays
  the returned answer text, a `source` badge (`graph_traversal` vs.
  `fallback_text_search`), and `cited_entity_ids` as chips.
- **`src/components/IngestPanel.jsx`** — a textarea + submit, shows the
  entities/relationships that came back from `/api/ingest` on success,
  and calls a passed-in `onIngested` callback so the graph view refetches
  without a manual page reload.
- **`src/components/GraphView.jsx`** — fetches `/api/graph`, renders with
  `react-force-graph-2d` (npm package `react-force-graph`), nodes
  color-coded by entity-type label (a fixed 11-color palette, one per
  `EntityType`), click-to-inspect a node's full property panel. Exposes a
  manual "Refresh" button in addition to the ingest-triggered refetch.
- **`src/App.jsx`** — three-panel layout (Ask / Add Data / Graph), holds
  the shared "graph needs refresh" state that `IngestPanel` triggers and
  `GraphView` reacts to.

Updates are refetch-on-success, not a websocket/SSE push — sufficient for
a single-user local tool with one browser tab open; real-time push across
multiple tabs would be a genuine future addition, not attempted here.

## Files to create

- `api/__init__.py`, `api/main.py`
- `frontend/` — full Vite scaffold: `package.json`, `vite.config.js`,
  `index.html`, `src/main.jsx`, `src/App.jsx`, `src/api.js`,
  `src/components/{AskPanel,IngestPanel,GraphView}.jsx`, basic CSS

No existing files change. `requirements.txt` is untouched (fastapi/uvicorn
already present).

## Verification

1. `docker compose up -d` (Neo4j), `uvicorn api.main:app --reload --port
   8000` — confirm all three routes respond:
   - `curl localhost:8000/api/graph` → JSON with the ~20 seeded
     nodes/edges, no `embedding` field present anywhere.
   - `curl -X POST localhost:8000/api/ask -d '{"question": "..."}'` with
     one of the three example questions from `retrieval/prompts.py` →
     same `AnswerResult` shape `retrieval.cli` already produces.
   - `curl -X POST localhost:8000/api/ingest -d '{"text": "..."}'` with a
     short new PR/incident snippet → confirm the returned entities, then
     confirm a follow-up `/api/graph` call includes the new node(s).
2. `cd frontend && npm install && npm run dev` — open the page, ask one
   of the three example questions and confirm the answer/citations
   render, paste new text into the ingest panel and confirm the graph
   view picks up the new node after submit, click a node and confirm its
   properties show.

## Implementation notes (post-build)

- The combined `react-force-graph` package also bundles the AR/VR
  variants, which reference a global `AFRAME` at module-load time and
  crash the whole page (`ReferenceError: AFRAME is not defined`) with no
  visible error beyond a blank screen. Switched to the standalone
  `react-force-graph-2d` package (default export, not named) instead —
  same 2D rendering, none of the AR/VR baggage.
- `/api/graph` and the graph visualization were verified live in a real
  browser against the running backend/Neo4j (19 seeded nodes,
  color-coded, no `embedding` field leaked).
- `/api/ask` and `/api/ingest` were verified correct via direct backend
  calls (`TestClient`), but a live browser click-through of "Ask" hit a
  `402 RESOURCE_EXHAUSTED — prepayment credits are depleted` from the
  Gemini API — a billing issue on the Google Cloud project, not a bug in
  this implementation. Blocked on the user resolving billing before a
  full live browser verification of Ask/Ingest can be completed.
