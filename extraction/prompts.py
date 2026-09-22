"""Prompt template for LLM entity/relationship extraction.

Schema-constrained the same way the retrieval-side Cypher generator is
(CLAUDE.md §6): the LLM is only ever shown the 11 locked entity types and
27 locked (source, relation, target) edges, so it has no vocabulary to
hallucinate a plausible-but-nonexistent type or relationship from.
"""

from __future__ import annotations

from extraction.schema import ALLOWED_EDGES, ID_FIELD_BY_TYPE, EntityType

_EDGE_LINES = "\n".join(
    f"  {source.value} -[{relation.value}]-> {target.value}"
    for source, relation, target in sorted(
        ALLOWED_EDGES, key=lambda edge: (edge[0].value, edge[1].value, edge[2].value)
    )
)

_ID_FIELD_LINES = "\n".join(
    f"  {entity_type.value}: keyed by `{field}`"
    for entity_type, field in ID_FIELD_BY_TYPE.items()
)

SYSTEM_PROMPT = f"""\
You extract graph entities and relationships from raw engineering text \
(PR descriptions, commit messages, review comments, CI logs, incident \
reports, etc.) for a knowledge graph with a fixed, locked schema.

Allowed entity types (exactly these 11, no others):
{", ".join(t.value for t in EntityType)}

Each entity's identifying field:
{_ID_FIELD_LINES}

Allowed relationships (exactly these 27 directed edges — a relationship \
whose (source type, relation, target type) triple is not in this list \
does not exist in this schema and must never be produced):
{_EDGE_LINES}

Rules:
1. Only extract an entity or relationship the text actually states or \
strongly implies. Do not invent ids, properties, or edges to fill gaps.
2. Every relationship's source_id/target_id must refer to an entity you \
also included in `entities`.
3. Never use a relation name, or a (source type, relation, target type) \
combination, outside the list above — if the text implies a connection \
that isn't in the list, omit it rather than approximate it.
4. If the text mentions an entity only by name/reference with no other \
detail, still include it with just its id and type; leave `properties` \
empty rather than guessing values.
5. If nothing in the text maps to this schema, return empty lists.
"""

RETRY_SUFFIX_TEMPLATE = """\

Your previous attempt included items that violate the schema and were \
dropped:
{violations}

Produce a corrected extraction from the same input text, following the \
rules above exactly.
"""


def build_retry_feedback(violations: list[str]) -> str:
    bullet_list = "\n".join(f"  - {v}" for v in violations)
    return RETRY_SUFFIX_TEMPLATE.format(violations=bullet_list)
