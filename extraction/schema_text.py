"""Shared schema-vocabulary text, computed once from extraction/schema.py.

Both the extraction prompt (extraction/prompts.py) and the retrieval-side
Cypher generation prompt (retrieval/prompts.py) need to show an LLM the
exact same locked vocabulary — the 11 entity types, their id fields, and
the 27 allowed (source, relation, target) edges — so neither ever
hallucinates a plausible-but-nonexistent type or relationship. This module
is the single place that text is built, so the two prompts can never drift
apart from each other or from extraction/schema.py.
"""

from __future__ import annotations

from extraction.schema import ALLOWED_EDGES, ID_FIELD_BY_TYPE, EntityType, RelationType

ENTITY_TYPES_LINE = ", ".join(t.value for t in EntityType)

RELATION_TYPES_LINE = ", ".join(r.value for r in RelationType)

ID_FIELD_LINES = "\n".join(
    f"  {entity_type.value}: keyed by `{field}`" for entity_type, field in ID_FIELD_BY_TYPE.items()
)

EDGE_LINES = "\n".join(
    f"  {source.value} -[{relation.value}]-> {target.value}"
    for source, relation, target in sorted(
        ALLOWED_EDGES, key=lambda edge: (edge[0].value, edge[1].value, edge[2].value)
    )
)
