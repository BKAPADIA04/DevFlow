"""FastAPI app for the local DevFlow web interface.

Three thin routes, each wrapping a pipeline that already exists and is
already verified end-to-end via the CLIs (graph/cli.py, graph/seed.py,
retrieval/cli.py) — no new business logic, prompts, or Cypher here beyond
the read-only /api/graph query, which nothing else in the project
currently exposes as JSON.

Run with:
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from neo4j.graph import Node, Relationship
from pydantic import BaseModel

from extraction.graph import extract
from extraction.schema import ID_FIELD_BY_TYPE, EntityType, ExtractionResult
from graph.connection import get_driver
from graph.constraints import ensure_constraints, ensure_vector_indexes
from graph.loader import load_extraction_result
from retrieval.graph import answer_question
from retrieval.models import AnswerResult

app = FastAPI(title="DevFlow")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str


class IngestRequest(BaseModel):
    text: str


@app.post("/api/ask", response_model=AnswerResult)
def ask(request: AskRequest) -> AnswerResult:
    return answer_question(request.question)


@app.post("/api/ingest", response_model=ExtractionResult)
def ingest(request: IngestRequest) -> ExtractionResult:
    result = extract(request.text)
    ensure_constraints()
    ensure_vector_indexes()
    load_extraction_result(result)
    return result


def _node_id(entity_type: EntityType, properties: dict) -> str | None:
    id_field = ID_FIELD_BY_TYPE[entity_type]
    return properties.get(id_field)


@app.get("/api/graph")
def graph(limit: int = 300) -> dict:
    driver = get_driver()
    with driver.session() as session:
        records = list(
            session.run(
                "MATCH (n) OPTIONAL MATCH (n)-[r]->(m) RETURN n, r, m LIMIT $limit",
                limit=limit,
            )
        )

    nodes_by_id: dict[str, dict] = {}
    edges: list[dict] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def _add_node(value: Node) -> str | None:
        labels = list(value.labels)
        if not labels:
            return None
        try:
            entity_type = EntityType(labels[0])
        except ValueError:
            return None

        props = dict(value)
        props.pop("embedding", None)
        node_id = _node_id(entity_type, props)
        if node_id is None:
            return None

        nodes_by_id[node_id] = {
            "id": node_id,
            "label": entity_type.value,
            "properties": {k: str(v) for k, v in props.items()},
        }
        return node_id

    for record in records:
        n_id = _add_node(record["n"]) if record["n"] is not None else None
        m_id = _add_node(record["m"]) if record["m"] is not None else None
        rel = record["r"]
        if isinstance(rel, Relationship) and n_id is not None and m_id is not None:
            key = (n_id, rel.type, m_id)
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({"source": n_id, "target": m_id, "type": rel.type})

    return {"nodes": list(nodes_by_id.values()), "edges": edges}
