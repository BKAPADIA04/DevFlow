"""Locked graph schema (see MDs/DevFlow-Relationships.md) as Python types.

11 entity types, 18 relationship types, 27 directed (source, relation,
target) edges. Kept in one place so the extractor's prompt and its
validation step can never drift from each other.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    REPOSITORY = "Repository"
    COMMIT = "Commit"
    FILE = "File"
    PULL_REQUEST = "PullRequest"
    DEVELOPER = "Developer"
    TEAM = "Team"
    REVIEW = "Review"
    CI_RUN = "CIRun"
    DEPLOYMENT = "Deployment"
    INCIDENT = "Incident"
    PERMISSION = "Permission"


class RelationType(str, Enum):
    CONTAINS = "CONTAINS"
    PROTECTED_BY = "PROTECTED_BY"
    OWNS = "OWNS"
    CREATES = "CREATES"
    AUTHORED = "AUTHORED"
    PERFORMS = "PERFORMS"
    BELONGS_TO = "BELONGS_TO"
    HAS_PERMISSION = "HAS_PERMISSION"
    MODIFIES = "MODIFIES"
    RECEIVES = "RECEIVES"
    TRIGGERS = "TRIGGERS"
    RELATED_TO = "RELATED_TO"
    PARENT_OF = "PARENT_OF"
    DEPLOYED_AS = "DEPLOYED_AS"
    OWNED_BY = "OWNED_BY"
    REQUIRES_REVIEW_FROM = "REQUIRES_REVIEW_FROM"
    TESTS = "TESTS"
    MAY_CAUSE = "MAY_CAUSE"


# The 27 locked (source_type, relation, target_type) edges, straight from
# the table in MDs/DevFlow-Relationships.md / CLAUDE.md §3. This is the
# single source of truth for both the extraction prompt and the validator
# — a relationship not in this set is rejected regardless of what the LLM
# returns.
ALLOWED_EDGES: set[tuple[EntityType, RelationType, EntityType]] = {
    (EntityType.REPOSITORY, RelationType.CONTAINS, EntityType.COMMIT),
    (EntityType.REPOSITORY, RelationType.CONTAINS, EntityType.FILE),
    (EntityType.REPOSITORY, RelationType.CONTAINS, EntityType.PULL_REQUEST),
    (EntityType.REPOSITORY, RelationType.PROTECTED_BY, EntityType.PERMISSION),
    (EntityType.DEVELOPER, RelationType.OWNS, EntityType.REPOSITORY),
    (EntityType.TEAM, RelationType.OWNS, EntityType.REPOSITORY),
    (EntityType.DEVELOPER, RelationType.CREATES, EntityType.PULL_REQUEST),
    (EntityType.DEVELOPER, RelationType.AUTHORED, EntityType.COMMIT),
    (EntityType.DEVELOPER, RelationType.PERFORMS, EntityType.REVIEW),
    (EntityType.DEVELOPER, RelationType.BELONGS_TO, EntityType.TEAM),
    (EntityType.DEVELOPER, RelationType.HAS_PERMISSION, EntityType.PERMISSION),
    (EntityType.TEAM, RelationType.OWNS, EntityType.FILE),
    (EntityType.TEAM, RelationType.HAS_PERMISSION, EntityType.PERMISSION),
    (EntityType.PULL_REQUEST, RelationType.MODIFIES, EntityType.FILE),
    (EntityType.PULL_REQUEST, RelationType.CONTAINS, EntityType.COMMIT),
    (EntityType.PULL_REQUEST, RelationType.RECEIVES, EntityType.REVIEW),
    (EntityType.PULL_REQUEST, RelationType.TRIGGERS, EntityType.CI_RUN),
    (EntityType.PULL_REQUEST, RelationType.TRIGGERS, EntityType.DEPLOYMENT),
    (EntityType.PULL_REQUEST, RelationType.RELATED_TO, EntityType.INCIDENT),
    (EntityType.COMMIT, RelationType.PARENT_OF, EntityType.COMMIT),
    (EntityType.COMMIT, RelationType.MODIFIES, EntityType.FILE),
    (EntityType.COMMIT, RelationType.DEPLOYED_AS, EntityType.DEPLOYMENT),
    (EntityType.FILE, RelationType.OWNED_BY, EntityType.DEVELOPER),
    (EntityType.FILE, RelationType.OWNED_BY, EntityType.TEAM),
    (EntityType.FILE, RelationType.REQUIRES_REVIEW_FROM, EntityType.TEAM),
    (EntityType.CI_RUN, RelationType.TESTS, EntityType.COMMIT),
    (EntityType.DEPLOYMENT, RelationType.MAY_CAUSE, EntityType.INCIDENT),
}

assert len(ALLOWED_EDGES) == 27  # keep in sync with MDs/DevFlow-Relationships.md

# Commit is keyed by `hash`; every other node type is keyed by `id`
# (CLAUDE.md §3).
ID_FIELD_BY_TYPE: dict[EntityType, str] = {
    entity_type: ("hash" if entity_type is EntityType.COMMIT else "id")
    for entity_type in EntityType
}


class ExtractedEntity(BaseModel):
    """One node pulled from the input text."""

    id: str = Field(description="The entity's id (or hash, for Commit)")
    type: EntityType
    properties: dict[str, str] = Field(
        default_factory=dict,
        description="Any other properties mentioned in the text (name, path, "
        "status, severity, etc.) — only what's actually stated, no guessing.",
    )


class ExtractedRelationship(BaseModel):
    """One directed edge between two extracted entities."""

    source_id: str
    source_type: EntityType
    relation: RelationType
    target_id: str
    target_type: EntityType

    def as_edge(self) -> tuple[EntityType, RelationType, EntityType]:
        return (self.source_type, self.relation, self.target_type)


class ExtractionResult(BaseModel):
    """What the LLM returns for one piece of input text."""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
