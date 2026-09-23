"""Uniqueness constraints for the graph loader.

One IS UNIQUE constraint per entity label, derived directly from
extraction/schema.py's EntityType + ID_FIELD_BY_TYPE rather than a
hand-kept label list, so this can never drift from the locked schema.
"""

from __future__ import annotations

from extraction.schema import ID_FIELD_BY_TYPE, EntityType
from graph.connection import get_driver

_CONSTRAINT_TEMPLATE = (
    "CREATE CONSTRAINT {name} IF NOT EXISTS "
    "FOR (n:{label}) REQUIRE n.{field} IS UNIQUE"
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


if __name__ == "__main__":
    ensure_constraints()
    print("Constraints ensured for all 11 entity labels.")
