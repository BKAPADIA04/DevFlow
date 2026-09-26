"""fallback_search node: flat vector search over the existing free-text
vector indexes (PullRequest, Commit, Incident, Review — the four
build_embedding_text branches with real prose per graph/embeddings.py),
reusing the same indexes entry-point search uses rather than standing up a
second embedding pipeline or a separate flat index (Chroma/pgvector are
both present in requirements.txt but unused, and stay that way).

Triggered when entry-point confidence is low (Trigger A) or a validated
graph query executes but returns nothing (Trigger B), per
MDs/DevFlow-Workflow-1.md §2.
"""

from __future__ import annotations

from extraction.schema import EntityType
from graph.connection import get_driver
from graph.embeddings import embed_texts
from retrieval.models import EvidenceBundle, EvidenceItem
from retrieval.state import RetrievalState

_FREE_TEXT_TYPES = (
    EntityType.PULL_REQUEST,
    EntityType.COMMIT,
    EntityType.INCIDENT,
    EntityType.REVIEW,
)
_FREE_TEXT_PROPERTIES = ("description", "root_cause", "resolution", "message", "comment", "title")
RESULTS_PER_INDEX = 3
TOTAL_RESULTS = 5


def fallback_search_node(state: RetrievalState) -> dict:
    extraction = state["extraction"]
    search_text = (
        " ".join(extraction.search_terms)
        if extraction and extraction.search_terms
        else state["question"]
    )

    vectors = embed_texts([search_text])
    if not vectors:
        return {"evidence": EvidenceBundle(source="fallback_text_search", confidence=0.0)}
    vector = vectors[0]

    hits: list[tuple[float, EvidenceItem]] = []
    driver = get_driver()
    with driver.session() as session:
        for entity_type in _FREE_TEXT_TYPES:
            index_name = f"{entity_type.value.lower()}_embedding_index"
            rows = session.run(
                "CALL db.index.vector.queryNodes($index, $k, $vector) "
                "YIELD node, score "
                "RETURN properties(node) AS props, score",
                index=index_name,
                k=RESULTS_PER_INDEX,
                vector=vector,
            ).data()
            for row in rows:
                props = dict(row["props"])
                props.pop("embedding", None)
                node_id = props.get("id")
                if node_id is None:
                    continue
                hits.append(
                    (
                        row["score"],
                        EvidenceItem(
                            node_id=node_id,
                            node_type=entity_type,
                            properties={k: str(v) for k, v in props.items()},
                        ),
                    )
                )

    hits.sort(key=lambda pair: pair[0], reverse=True)
    top_hits = hits[:TOTAL_RESULTS]

    text_snippets: list[str] = []
    for _, item in top_hits:
        for key in _FREE_TEXT_PROPERTIES:
            text = item.properties.get(key)
            if text:
                text_snippets.append(f"{item.node_type.value} {item.node_id} {key}: {text}")

    evidence = EvidenceBundle(
        source="fallback_text_search",
        entry_point=None,
        paths=[],
        text_snippets=text_snippets,
        confidence=top_hits[0][0] if top_hits else 0.0,
        cypher_used=None,
    )
    return {"evidence": evidence}
