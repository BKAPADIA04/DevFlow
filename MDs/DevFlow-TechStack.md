# DevFlow — Tech Stack (v2: Cloud LLM + LangChain)

Full switch adopted. This replaces the earlier local-only stack.

## Core

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| LLM Framework | LangChain |
| Workflow Orchestration | LangGraph *(later — once MCP/agent phase starts)* |
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
| MCP | MCP Server *(later)* |
| Version Control | Git + GitHub |

## What changed from v1 (local-only stack)

```
Local LLM (Ollama)          → Cloud LLM API (OpenAI/Claude/Gemini)
No LangChain                → LangChain (structured output + Pydantic)
No reranker                 → Cross-Encoder / Cohere Rerank, reinstated
Separate vector store        → Neo4j native Vector Index (one DB, not two)
  (Chroma/FAISS)
Local sentence-transformers  → OpenAI/Gemini Embeddings API
```

## Architecture (query-time)

```
                    User Query
                        │
                        ▼
                 LangChain / LLM
                        │
                Query Understanding
                        │
             ┌──────────┴──────────┐
             ▼                     ▼
        Graph Retrieval       Vector Retrieval
             │                     │
             ▼                     ▼
          Neo4j                Neo4j Vector
          Cypher                 Index
             │                     │
             └──────────┬──────────┘
                        ▼
                    Reranker
                        │
                        ▼
                  Context Builder
                        │
                        ▼
                   LLM Synthesis
                        │
                        ▼
                      Answer
```

## Architecture (knowledge graph construction)

```
GitHub / GitLab / CI / Incidents
              │
              ▼
        Raw Artifacts
              │
              ▼
       LangChain + LLM
              │
              ▼
 Entity & Relationship Extraction
              │
              ▼
     Pydantic Validation
              │
              ▼
       Entity Resolution
              │
              ▼
            Neo4j
       ┌──────┴──────┐
       │             │
 Knowledge Graph  Vector Index
```

## Still deferred (unchanged from v1)

```
- MCP server / MCP client / agentic tool-selection loop
- LangGraph (stateful workflows, branching, retries) — added once
  the agent phase starts
- AWS deployment
- Fixed pre-written Cypher functions (LLM-generated Cypher +
  validation remains the retrieval strategy — see the dedicated
  retrieval doc)
```

## Why each change was made

- **Cloud LLM over local**: removes the local-model reliability risk
  we'd flagged for structured Cypher generation and entity extraction —
  frontier models are simply better at precise structured output,
  which matters most for the Cypher-generation step.
- **LangChain**: used narrowly for structured output (Pydantic-typed
  extraction), not for a tool-calling/agent loop — that distinction
  still matters, LangChain isn't being used as an orchestration
  framework yet, just as a structured-generation convenience layer.
- **Reranker reinstated**: now that a cloud LLM/embedding API is in
  play anyway, the added latency/cost of a reranking pass is
  proportionally smaller, and it improves entry-point accuracy.
- **Neo4j native vector index**: removes an entire piece of
  infrastructure (a second database) with no loss of capability —
  a clear simplification.

## Follow-on updates this implies (not yet done)

The retrieval-strategy doc (`devflow-llm-cypher-retrieval.md`) and the
full-flow doc (`devflow-full-flow-with-fallback.md`) were written
assuming a **local** LLM, which shaped some of their reasoning —
specifically:
```
- The "local model consideration" section (few-shot examples +
  retry-on-failure as mitigations for weaker structured generation)
  is less critical now, though still good practice
- Both docs should be updated to reference Neo4j's native vector
  index instead of a separate Chroma/FAISS store
- The "why no reranker" rationale in the old tech-stack doc no
  longer applies — reranking is back in scope
```
Let me know if you'd like these two docs updated to match this new
stack as well.
