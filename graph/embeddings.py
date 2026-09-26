"""Builds embeddable text per entity type and batches it through Gemini's
embedding API, via the same round-robin key pool extraction/llm.py uses.

LangSmith tracing: the actual embedContent call is wrapped in @traceable
so it shows up as its own span (run_type="embedding") in LangSmith,
mirroring extraction/llm.py's _generate — both bypass LangChain's own
wrappers to drive the pooled google-genai client directly, so neither
gets automatic tracing for free.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langsmith import traceable

from extraction.schema import EntityType, ExtractedEntity

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helper"))
from gemini_key_pool import GeminiKeyPool  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 3072

_POOL: GeminiKeyPool | None = None


def _get_pool() -> GeminiKeyPool:
    global _POOL
    if _POOL is None:
        _POOL = GeminiKeyPool()
    return _POOL


def build_embedding_text(entity: ExtractedEntity) -> str:
    """One text template per EntityType, built from entity.properties.

    Types with real free text (File, PullRequest, Commit, Incident,
    Review) embed that text directly. The rest (Repository, Developer,
    Team, CIRun, Deployment, Permission) have little natural text, so a
    short synthesized sentence keeps every entity type embeddable for
    typed entry-point search (MDs/DevFlow-Workflow-1.md), not just the
    text-heavy ones.
    """

    props = {p.key: p.value for p in entity.properties}

    if entity.type is EntityType.FILE:
        return props.get("path", entity.id)
    if entity.type is EntityType.PULL_REQUEST:
        return f"{props.get('title', '')}. {props.get('description', '')}".strip()
    if entity.type is EntityType.COMMIT:
        return props.get("message", entity.id)
    if entity.type is EntityType.INCIDENT:
        return (
            f"{props.get('severity', '')} incident: "
            f"{props.get('root_cause', '')}. {props.get('resolution', '')}"
        ).strip()
    if entity.type is EntityType.REVIEW:
        return f"{props.get('result', '')} review: {props.get('comment', '')}".strip()
    if entity.type is EntityType.REPOSITORY:
        return f"repository {props.get('name', entity.id)}"
    if entity.type is EntityType.DEVELOPER:
        return f"developer {props.get('name', entity.id)}"
    if entity.type is EntityType.TEAM:
        return f"team {props.get('name', entity.id)}"
    if entity.type is EntityType.CI_RUN:
        return f"CI run, status {props.get('status', 'unknown')}"
    if entity.type is EntityType.DEPLOYMENT:
        return (
            f"deployment to {props.get('environment', 'unknown')}, "
            f"artifact {props.get('artifact_id', entity.id)}"
        )
    if entity.type is EntityType.PERMISSION:
        return (
            f"{props.get('role_name', '')} permission: "
            f"{props.get('grants', '')}"
        ).strip()

    raise ValueError(f"No embedding-text template for entity type {entity.type!r}")


@traceable(run_type="embedding", name="gemini_pool_embed_content")
def _embed(pool: GeminiKeyPool, model: str, texts: list[str]) -> Any:
    return pool.embed_content(model=model, contents=texts)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """One batched embedContent call for N texts, via the shared pool."""

    if not texts:
        return []
    response = _embed(_get_pool(), EMBEDDING_MODEL, texts)
    return [e.values for e in response.embeddings]
