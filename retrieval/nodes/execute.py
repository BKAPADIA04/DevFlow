"""execute_graph_query node: runs the validated Cypher against Neo4j with
the entry-point id bound as a parameter, under the same resource limits
the validator checked for (query timeout, row cap). Any driver-level
failure (timeout, connection error) is treated identically to "empty
results" downstream — never raised to the caller.
"""

from __future__ import annotations

from neo4j import Query

from graph.connection import get_driver
from retrieval.cypher_validator import MAX_RESULT_ROWS, QUERY_TIMEOUT_SECONDS
from retrieval.state import RetrievalState


def execute_graph_query_node(state: RetrievalState) -> dict:
    entry_point = state["entry_point"]
    driver = get_driver()
    try:
        with driver.session() as session:
            query = Query(state["cypher"], timeout=QUERY_TIMEOUT_SECONDS)
            result = session.run(query, entry_id=entry_point.node_id)
            # Keep raw Record objects (not .data()), which would flatten
            # Node/Relationship values into plain dicts and lose the label
            # info assemble_evidence needs to tell node types apart.
            records = list(result)
    except Exception:  # noqa: BLE001 — execution failure degrades to fallback, never crashes
        records = []

    return {"raw_records": records[:MAX_RESULT_ROWS]}
