"""Pydantic models for the query-time retrieval pipeline (retrieval/graph.py).

Kept separate from extraction/schema.py's ExtractedEntity/ExtractedRelationship
on purpose: those model what an LLM pulled out of *source text* during graph
construction, while these model what an LLM pulls out of a *user question*
and what the pipeline assembles as evidence for it — different shapes, same
underlying EntityType/RelationType vocabulary.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from extraction.schema import EntityType, RelationType


class QueryExtraction(BaseModel):
    """What the first LLM call pulls out of the user's question."""

    entities: list[str] = Field(
        default_factory=list,
        description="Raw entity mentions from the question, e.g. 'src/auth.py', 'INC-089'.",
    )
    entity_types: list[EntityType] = Field(
        default_factory=list,
        description="Best-effort inferred entity type(s) for the question's subject. "
        "Leave empty if the type genuinely can't be inferred from the wording — "
        "guessing wrong is worse than leaving this empty.",
    )
    relationships: list[str] = Field(
        default_factory=list,
        description="Free-text relationship hints implied by the question, e.g. "
        "'caused by', 'has permission to modify'.",
    )
    intent: str = Field(
        description="The kind of question being asked, e.g. 'incident_root_cause', "
        "'finding_reviewers', 'permission_reasoning'."
    )
    search_terms: list[str] = Field(
        description="Short phrase(s) to embed for vector entry-point search. "
        "Usually the entity mention itself, plus any distinguishing context."
    )


class EntryPointCandidate(BaseModel):
    """One candidate graph node from typed vector search."""

    node_id: str
    node_type: EntityType
    score: float
    properties: dict[str, str] = Field(default_factory=dict)


class EvidenceItem(BaseModel):
    """One node surfaced as evidence, with its full property set."""

    node_id: str
    node_type: EntityType
    properties: dict[str, str] = Field(default_factory=dict)


class EvidenceRelationship(BaseModel):
    source_id: str
    relation: RelationType
    target_id: str


class EvidencePath(BaseModel):
    nodes: list[EvidenceItem] = Field(default_factory=list)
    relationships: list[EvidenceRelationship] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    """Assembled context handed to the final synthesis LLM call."""

    source: Literal["graph_traversal", "fallback_text_search"]
    entry_point: EvidenceItem | None = None
    paths: list[EvidencePath] = Field(default_factory=list)
    text_snippets: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    cypher_used: str | None = None

    def to_prompt_text(self) -> str:
        """Formats this bundle as a compact, connected-path context block —
        not a flat fact list — for the synthesis prompt.
        """

        lines: list[str] = []
        for path in self.paths:
            for node in path.nodes:
                props = ", ".join(f"{k}={v}" for k, v in node.properties.items())
                lines.append(f"- {node.node_type.value} {node.node_id} ({props})")
            for rel in path.relationships:
                lines.append(f"  {rel.source_id} -[{rel.relation.value}]-> {rel.target_id}")
        if self.text_snippets:
            lines.append("Relevant text:")
            lines.extend(f"- {snippet}" for snippet in self.text_snippets)
        return "\n".join(lines) if lines else "(no evidence found)"


class AnswerResult(BaseModel):
    """What the final synthesis LLM call returns."""

    answer: str
    source: Literal["graph_traversal", "fallback_text_search"]
    has_sufficient_evidence: bool
    cited_entity_ids: list[str] = Field(default_factory=list)
