"""Unit tests for retrieval/evidence.py's assemble_evidence_node.

Builds real neo4j.graph.Node/Relationship/Record shapes by hand (the same
objects the driver would hand back from a live query), so
isinstance(value, Node)/isinstance(value, Relationship) in evidence.py
behave exactly as they would against a real result — the point of the bug
this module fixed (see graph/loader.py's sibling: execute.py switching
from .data() to raw Record objects).
"""

from __future__ import annotations

from neo4j import Record
from neo4j.graph import Graph

from extraction.schema import EntityType, RelationType
from retrieval.evidence import assemble_evidence_node
from retrieval.models import EntryPointCandidate


def _node(graph: Graph, element_id: str, label: str, properties: dict):
    from neo4j.graph import Node

    return Node(graph, element_id, hash(element_id), [label], properties)


def _relationship(graph: Graph, rel_id: str, rel_type: str, start, end):
    rel_cls = graph.relationship_type(rel_type)
    rel = rel_cls(graph, rel_id, hash(rel_id), {})
    rel._start_node = start
    rel._end_node = end
    return rel


def test_preserves_free_text_properties_and_relationships():
    graph = Graph()
    incident = _node(
        graph,
        "n1",
        "Incident",
        {"id": "INC-089", "severity": "SEV2", "root_cause": "bad rollout", "embedding": [0.1] * 8},
    )
    deployment = _node(graph, "n2", "Deployment", {"id": "DEPLOY-034", "environment": "production"})
    rel = _relationship(graph, "r1", "MAY_CAUSE", deployment, incident)

    record = Record({"i": incident, "dep": deployment, "may_cause": rel})

    state = {
        "raw_records": [record],
        "entry_point": EntryPointCandidate(
            node_id="INC-089", node_type=EntityType.INCIDENT, score=0.9, properties={}
        ),
        "confidence": 0.9,
        "cypher": "MATCH (i:Incident {id: $entry_id}) ... RETURN i, dep",
    }

    result = assemble_evidence_node(state)
    evidence = result["evidence"]

    assert evidence.source == "graph_traversal"
    assert evidence.entry_point.node_id == "INC-089"

    node_ids = {n.node_id for path in evidence.paths for n in path.nodes}
    assert node_ids == {"INC-089", "DEPLOY-034"}

    incident_item = next(n for path in evidence.paths for n in path.nodes if n.node_id == "INC-089")
    assert "embedding" not in incident_item.properties
    assert incident_item.properties["root_cause"] == "bad rollout"

    assert any(
        r.source_id == "DEPLOY-034" and r.relation == RelationType.MAY_CAUSE and r.target_id == "INC-089"
        for path in evidence.paths
        for r in path.relationships
    )

    assert any("bad rollout" in snippet for snippet in evidence.text_snippets)


def test_empty_records_yields_empty_evidence():
    state = {
        "raw_records": [],
        "entry_point": EntryPointCandidate(
            node_id="INC-089", node_type=EntityType.INCIDENT, score=0.9, properties={}
        ),
        "confidence": 0.9,
        "cypher": "MATCH (i:Incident {id: $entry_id}) RETURN i",
    }
    result = assemble_evidence_node(state)
    evidence = result["evidence"]
    assert evidence.paths == []
    assert evidence.text_snippets == []
    # entry point still carried through even with no traversal results
    assert evidence.entry_point.node_id == "INC-089"


def test_commit_node_uses_hash_as_id():
    graph = Graph()
    commit = _node(graph, "n1", "Commit", {"hash": "a1b2c3d", "message": "fix bug"})
    record = Record({"c": commit})

    state = {
        "raw_records": [record],
        "entry_point": EntryPointCandidate(
            node_id="a1b2c3d", node_type=EntityType.COMMIT, score=0.9, properties={}
        ),
        "confidence": 0.9,
        "cypher": "MATCH (c:Commit {hash: $entry_id}) RETURN c",
    }
    result = assemble_evidence_node(state)
    evidence = result["evidence"]
    node_ids = {n.node_id for path in evidence.paths for n in path.nodes}
    assert node_ids == {"a1b2c3d"}
