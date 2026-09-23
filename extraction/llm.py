"""LLM client factory for the extraction pipeline.

Wraps helper/gemini_key_pool.GeminiKeyPool so extraction gets the same
round-robin, rate-limit-failover behavior as scripts/ask_gemini.py — a
single overloaded key no longer fails the whole extraction. This trades
LangChain's own Gemini wrapper (ChatGoogleGenerativeAI) for Gemini's
native structured-output mode (`response_schema`), since the pool only
knows how to drive the raw google-genai client, not a LangChain chat
model. The public shape graph.py calls against —
`get_llm().with_structured_output(Model).invoke(messages)` — is kept the
same either way.

LangSmith tracing: enabled by setting LANGSMITH_TRACING=true,
LANGSMITH_API_KEY, and (optionally) LANGSMITH_PROJECT in `.env` — nothing
else to configure. `.env` is loaded at import time (not lazily on first
LLM call) specifically so those vars are in os.environ before
extraction/graph.py builds and invokes the LangGraph graph, since
LangGraph's own run needs LANGSMITH_TRACING set before it starts to be
captured as the trace root. The actual Gemini call bypasses LangChain
(see module docstring above), so it's wrapped in `@traceable` below to
show up as its own span instead of being an opaque black box inside the
"extract" node.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TypeVar

from dotenv import load_dotenv
from google.genai import types
from langchain_core.messages import BaseMessage, SystemMessage
from langsmith import traceable
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helper"))
from gemini_key_pool import GeminiKeyPool  # noqa: E402

DEFAULT_MODEL = "gemini-3.6-flash"

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_POOL: GeminiKeyPool | None = None

SchemaT = TypeVar("SchemaT", bound=BaseModel)


def _get_pool() -> GeminiKeyPool:
    global _POOL
    if _POOL is None:
        _POOL = GeminiKeyPool()
    return _POOL


@traceable(run_type="llm", name="gemini_pool_generate_content")
def _generate(
    pool: GeminiKeyPool, model: str, contents: str, config: types.GenerateContentConfig
) -> str:
    response = pool.generate_content(model=model, contents=contents, config=config)
    return response.text


def _split_messages(messages: list[BaseMessage]) -> tuple[str | None, str]:
    """Splits LangChain messages into (system_instruction, user content)."""

    system_parts = [str(m.content) for m in messages if isinstance(m, SystemMessage)]
    other_parts = [str(m.content) for m in messages if not isinstance(m, SystemMessage)]
    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, "\n\n".join(other_parts)


class _StructuredGeminiModel:
    """Bound to one Pydantic schema; mirrors the `.invoke(messages) ->
    schema instance` shape of LangChain's `.with_structured_output(...)`
    closely enough for graph.py's usage, while routing every call through
    the multi-key pool via Gemini's native `response_schema` JSON mode.
    """

    def __init__(self, pool: GeminiKeyPool, model: str, schema: type[SchemaT]) -> None:
        self._pool = pool
        self._model = model
        self._schema = schema

    def invoke(self, messages: list[BaseMessage]) -> SchemaT:
        system_instruction, contents = _split_messages(messages)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=self._schema,
        )
        text = _generate(self._pool, self._model, contents, config)
        return self._schema.model_validate(json.loads(text))


class PooledGeminiLLM:
    """`get_llm()`'s return type — only exposes `.with_structured_output`,
    since that's all the extraction pipeline needs today.
    """

    def __init__(self, pool: GeminiKeyPool, model: str) -> None:
        self._pool = pool
        self._model = model

    def with_structured_output(self, schema: type[SchemaT]) -> _StructuredGeminiModel:
        return _StructuredGeminiModel(self._pool, self._model, schema)


def get_llm(model: str = DEFAULT_MODEL) -> PooledGeminiLLM:
    """Returns an LLM handle backed by the round-robin Gemini key pool."""

    return PooledGeminiLLM(_get_pool(), model)
