"""assemble_evidence: converts raw Neo4j records (from execute_graph_query)
into an EvidenceBundle — preserving every node's full properties (so
free-text fields like PR description, incident root_cause/resolution,
commit message, review comment travel with the structured facts, not just
ids) rather than collapsing straight to a flat fact list.
"""

from __future__ import annotations

from neo4j.graph import Node, Relationship

from extraction.schema import EntityType, RelationType
from retrieval.models import EvidenceBundle, EvidenceItem, EvidencePath, EvidenceRelationship
from retrieval.state import RetrievalState

_FREE_TEXT_PROPERTIES = ("description", "root_cause", "resolution", "message", "comment", "title")


def _node_to_evidence_item(node: Node) -> EvidenceItem | None:
    labels = list(node.labels)
    if not labels:
        return None
    try:
        node_type = EntityType(labels[0])
    except ValueError:
        return None

    props = dict(node)
    props.pop("embedding", None)
    node_id = props.get("hash") if node_type is EntityType.COMMIT else props.get("id")
    if node_id is None:
        return None

    return EvidenceItem(
        node_id=node_id, node_type=node_type, properties={k: str(v) for k, v in props.items()}
    )


def assemble_evidence_node(state: RetrievalState) -> dict:
    records = state["raw_records"] or []
    entry_point = state["entry_point"]

    items_by_id: dict[str, EvidenceItem] = {}
    relationships: list[EvidenceRelationship] = []
    text_snippets: list[str] = []

    for record in records:
        for value in record.values():
            if isinstance(value, Node):
                item = _node_to_evidence_item(value)
                if item is None:
                    continue
                items_by_id[item.node_id] = item
                for key in _FREE_TEXT_PROPERTIES:
                    text = item.properties.get(key)
                    if text:
                        text_snippets.append(f"{item.node_type.value} {item.node_id} {key}: {text}")
            elif isinstance(value, Relationship):
                try:
                    relation = RelationType(value.type)
                except ValueError:
                    continue
                start_item = _node_to_evidence_item(value.start_node) if value.start_node else None
                end_item = _node_to_evidence_item(value.end_node) if value.end_node else None
                if start_item and end_item:
                    relationships.append(
                        EvidenceRelationship(
                            source_id=start_item.node_id,
                            relation=relation,
                            target_id=end_item.node_id,
                        )
                    )

    path = EvidencePath(nodes=list(items_by_id.values()), relationships=relationships)

    entry_item = items_by_id.get(entry_point.node_id) if entry_point else None
    if entry_item is None and entry_point is not None:
        entry_item = EvidenceItem(
            node_id=entry_point.node_id,
            node_type=entry_point.node_type,
            properties=entry_point.properties,
        )

    evidence = EvidenceBundle(
        source="graph_traversal",
        entry_point=entry_item,
        paths=[path] if path.nodes else [],
        text_snippets=list(dict.fromkeys(text_snippets)),
        confidence=state["confidence"],
        cypher_used=state["cypher"],
    )
    return {"evidence": evidence}
