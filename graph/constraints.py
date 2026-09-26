"""Uniqueness constraints and vector indexes for the graph loader.

One IS UNIQUE constraint, and one vector index, per entity label, both
derived directly from extraction/schema.py's EntityType (+
ID_FIELD_BY_TYPE for the constraint) rather than a hand-kept label list,
so neither can ever drift from the locked schema.
"""

from __future__ import annotations

from extraction.schema import ID_FIELD_BY_TYPE, EntityType
from graph.connection import get_driver
from graph.embeddings import EMBEDDING_DIMENSIONS

_CONSTRAINT_TEMPLATE = (
    "CREATE CONSTRAINT {name} IF NOT EXISTS "
    "FOR (n:{label}) REQUIRE n.{field} IS UNIQUE"
)

_VECTOR_INDEX_TEMPLATE = (
    "CREATE VECTOR INDEX {name} IF NOT EXISTS "
    "FOR (n:{label}) ON (n.embedding) "
    "OPTIONS {{indexConfig: {{"
    "`vector.dimensions`: {dimensions}, "
    "`vector.similarity_function`: 'cosine'}}}}"
)


def ensure_constraints() -> None:
    """Creates (or confirms) one uniqueness constraint per entity label.

    label/field come only from the schema enum/dict, never user input, so
    this f-string interpolation into Cypher is safe templating, not an
    injection risk. Idempotent via IF NOT EXISTS — safe to call every run.
    """

    driver = get_driver()
    driver.verify_connectivity()
    with driver.session() as session:
        for entity_type in EntityType:
            label = entity_type.value
            field = ID_FIELD_BY_TYPE[entity_type]
            name = f"{label.lower()}_{field}_unique"
            session.run(_CONSTRAINT_TEMPLATE.format(name=name, label=label, field=field))


def ensure_vector_indexes() -> None:
    """Creates (or confirms) one vector index per entity label, over the
    `embedding` property graph/loader.py writes on every node.
    Idempotent via IF NOT EXISTS — safe to call every run.
    """

    driver = get_driver()
    driver.verify_connectivity()
    with driver.session() as session:
        for entity_type in EntityType:
            label = entity_type.value
            name = f"{label.lower()}_embedding_index"
            session.run(
                _VECTOR_INDEX_TEMPLATE.format(
                    name=name, label=label, dimensions=EMBEDDING_DIMENSIONS
                )
            )


if __name__ == "__main__":
    ensure_constraints()
    ensure_vector_indexes()
    print("Constraints and vector indexes ensured for all 11 entity labels.")
