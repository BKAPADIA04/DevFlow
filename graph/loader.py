"""Loads an extraction/schema.ExtractionResult into Neo4j as nodes/edges.

Every write is MERGE (not CREATE), keyed on label + id field, so
re-running the same (or overlapping) ExtractionResult never duplicates
nodes or relationships. Node/relationship labels and types in the Cypher
below always come from the locked EntityType/RelationType enums, never
from raw extracted text, so the f-string templating here is safe (Neo4j
requires labels and relationship types to be literals, not parameters).
"""

from __future__ import annotations

from collections import defaultdict

from neo4j import Session

from extraction.schema import (
    ID_FIELD_BY_TYPE,
    EntityType,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
    RelationType,
)
from graph.connection import get_driver

_NODE_MERGE_TEMPLATE = "MERGE (n:{label} {{{id_field}: $id}}) SET n += $props"

_RELATIONSHIP_MERGE_TEMPLATE = (
    "UNWIND $rows AS row "
    "MATCH (src:{source_label} {{{source_id_field}: row.source_id}}) "
    "MATCH (tgt:{target_label} {{{target_id_field}: row.target_id}}) "
    "MERGE (src)-[r:{relation}]->(tgt)"
)


def _props_dict(entity: ExtractedEntity) -> dict[str, str]:
    return {p.key: p.value for p in entity.properties}


def _merge_entity(session: Session, entity: ExtractedEntity) -> None:
    label = entity.type.value
    id_field = ID_FIELD_BY_TYPE[entity.type]
    query = _NODE_MERGE_TEMPLATE.format(label=label, id_field=id_field)
    session.run(query, id=entity.id, props=_props_dict(entity))


def _group_relationships(
    relationships: list[ExtractedRelationship],
) -> dict[tuple[RelationType, EntityType, EntityType], list[ExtractedRelationship]]:
    groups: dict[tuple[RelationType, EntityType, EntityType], list[ExtractedRelationship]] = (
        defaultdict(list)
    )
    for rel in relationships:
        groups[(rel.relation, rel.source_type, rel.target_type)].append(rel)
    return groups


def _merge_relationships(
    session: Session,
    relation: RelationType,
    source_type: EntityType,
    target_type: EntityType,
    rels: list[ExtractedRelationship],
) -> None:
    query = _RELATIONSHIP_MERGE_TEMPLATE.format(
        source_label=source_type.value,
        source_id_field=ID_FIELD_BY_TYPE[source_type],
        target_label=target_type.value,
        target_id_field=ID_FIELD_BY_TYPE[target_type],
        relation=relation.value,
    )
    rows = [{"source_id": r.source_id, "target_id": r.target_id} for r in rels]
    session.run(query, rows=rows)


def load_extraction_result(result: ExtractionResult) -> None:
    """Writes every entity, then every relationship, from one
    ExtractionResult into Neo4j.

    Entities are all merged first so relationship MATCH clauses can find
    both endpoints extracted in the same call. A relationship whose
    endpoint wasn't extracted as an entity simply matches nothing and
    silently creates no edge.
    """

    driver = get_driver()
    with driver.session() as session:
        for entity in result.entities:
            _merge_entity(session, entity)

        for (relation, source_type, target_type), rels in _group_relationships(
            result.relationships
        ).items():
            _merge_relationships(session, relation, source_type, target_type, rels)
