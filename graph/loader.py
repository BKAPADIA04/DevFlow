"""Loads an extraction/schema.ExtractionResult into Neo4j as nodes/edges.

Every write is MERGE (not CREATE), keyed on label + id field, so
re-running the same (or overlapping) ExtractionResult never duplicates
nodes or relationships. Node/relationship labels and types in the Cypher
below always come from the locked EntityType/RelationType enums, never
from raw extracted text, so the f-string templating here is safe (Neo4j
requires labels and relationship types to be literals, not parameters).

Every entity also gets a vector `embedding` property. Neo4j is the
embedding cache: before calling the embedding API, entities whose id
already has a stored embedding are looked up and skipped, so re-running
the same ExtractionResult costs zero embedding calls, not just zero
duplicate writes.
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
from graph.embeddings import build_embedding_text, embed_texts

_NODE_MERGE_TEMPLATE = (
    "MERGE (n:{label} {{{id_field}: $id}}) SET n += $props, n.embedding = $embedding"
)

_RELATIONSHIP_MERGE_TEMPLATE = (
    "UNWIND $rows AS row "
    "MATCH (src:{source_label} {{{source_id_field}: row.source_id}}) "
    "MATCH (tgt:{target_label} {{{target_id_field}: row.target_id}}) "
    "MERGE (src)-[r:{relation}]->(tgt)"
)


def _props_dict(entity: ExtractedEntity) -> dict[str, str]:
    return {p.key: p.value for p in entity.properties}


def _merge_entity(
    session: Session, entity: ExtractedEntity, embedding: list[float]
) -> None:
    label = entity.type.value
    id_field = ID_FIELD_BY_TYPE[entity.type]
    query = _NODE_MERGE_TEMPLATE.format(label=label, id_field=id_field)
    session.run(query, id=entity.id, props=_props_dict(entity), embedding=embedding)


def _fetch_existing_embeddings(
    session: Session, entities: list[ExtractedEntity]
) -> dict[str, list[float]]:
    """Looks up which of `entities`' ids already have a stored `embedding`
    in Neo4j, grouped by label since the id field differs per type
    (Commit uses `hash`, everything else `id`).

    Neo4j's own data is the embedding cache: once written, an embedding
    survives container restarts via the `neo4j_data` volume
    (docker-compose.yml), so a node found here is never re-embedded.
    """

    found: dict[str, list[float]] = {}
    ids_by_type: dict[EntityType, list[str]] = defaultdict(list)
    for entity in entities:
        ids_by_type[entity.type].append(entity.id)

    for entity_type, ids in ids_by_type.items():
        label = entity_type.value
        id_field = ID_FIELD_BY_TYPE[entity_type]
        query = (
            f"MATCH (n:{label}) WHERE n.{id_field} IN $ids "
            f"AND n.embedding IS NOT NULL "
            f"RETURN n.{id_field} AS id, n.embedding AS embedding"
        )
        for row in session.run(query, ids=ids):
            found[row["id"]] = row["embedding"]
    return found


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
        existing = _fetch_existing_embeddings(session, result.entities)
        missing = [e for e in result.entities if e.id not in existing]
        texts = [build_embedding_text(e) for e in missing]
        vectors = embed_texts(texts)
        embeddings = existing | dict(zip((e.id for e in missing), vectors))

        for entity in result.entities:
            _merge_entity(session, entity, embeddings[entity.id])

        for (relation, source_type, target_type), rels in _group_relationships(
            result.relationships
        ).items():
            _merge_relationships(session, relation, source_type, target_type, rels)
