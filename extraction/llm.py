"""LLM client factory for the extraction pipeline.

Uses langchain-google-genai (Gemini) with structured output, per CLAUDE.md
§6 ("LangChain used narrowly: only for structured output"). Reads the same
GEMINI_API_KEYS env var as helper/gemini_key_pool.py; only the first key is
used here since ChatGoogleGenerativeAI takes a single api key rather than a
rotating pool.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

DEFAULT_MODEL = "gemini-3.6-flash"

_ENV_LOADED = False


def _ensure_env_loaded() -> None:
    global _ENV_LOADED
    if not _ENV_LOADED:
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        _ENV_LOADED = True


def _first_gemini_key() -> str:
    _ensure_env_loaded()

    combined = os.environ.get("GEMINI_API_KEYS", "")
    for key in combined.split(","):
        key = key.strip()
        if key:
            return key

    single = os.environ.get("GEMINI_API_KEY_1") or os.environ.get("GOOGLE_API_KEY")
    if single:
        return single

    raise ValueError(
        "No Gemini API key found. Set GEMINI_API_KEYS (comma-separated), "
        "GEMINI_API_KEY_1, or GOOGLE_API_KEY in the environment."
    )


def get_llm(model: str = DEFAULT_MODEL, temperature: float = 0.0) -> ChatGoogleGenerativeAI:
    """Returns a chat model ready for `.with_structured_output(...)`."""

    return ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        google_api_key=_first_gemini_key(),
    )
