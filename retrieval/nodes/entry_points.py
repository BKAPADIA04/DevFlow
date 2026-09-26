"""retrieve_entry_points node: embeds the extracted search terms and finds
candidate graph nodes via the existing per-label vector indexes
(graph/constraints.py) — no second embedding pipeline or index is created.
"""

from __future__ import annotations

from extraction.schema import EntityType
from graph.connection import get_driver
from graph.embeddings import embed_texts
from retrieval.models import EntryPointCandidate
from retrieval.state import RetrievalState

CANDIDATES_PER_INDEX = 3


def _index_name(entity_type: EntityType) -> str:
    return f"{entity_type.value.lower()}_embedding_index"


def retrieve_entry_points_node(state: RetrievalState) -> dict:
    extraction = state["extraction"]
    search_text = " ".join(extraction.search_terms) if extraction.search_terms else state["question"]

    vectors = embed_texts([search_text])
    if not vectors:
        return {"candidates": []}
    vector = vectors[0]

    types_to_search = extraction.entity_types or list(EntityType)

    candidates: list[EntryPointCandidate] = []
    driver = get_driver()
    with driver.session() as session:
        for entity_type in types_to_search:
            rows = session.run(
                "CALL db.index.vector.queryNodes($index, $k, $vector) "
                "YIELD node, score "
                "RETURN properties(node) AS props, score",
                index=_index_name(entity_type),
                k=CANDIDATES_PER_INDEX,
                vector=vector,
            ).data()
            for row in rows:
                props = dict(row["props"])
                props.pop("embedding", None)
                node_id = props.get("hash") if entity_type is EntityType.COMMIT else props.get("id")
                if node_id is None:
                    continue
                candidates.append(
                    EntryPointCandidate(
                        node_id=node_id,
                        node_type=entity_type,
                        score=row["score"],
                        properties={k: str(v) for k, v in props.items()},
                    )
                )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return {"candidates": candidates}
