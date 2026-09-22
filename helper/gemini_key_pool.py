"""Round-robin API key pool for the Gemini API with rate-limit fault tolerance.

Cycles through multiple Gemini API keys so a single key hitting its rate
limit doesn't fail the whole request. A key that returns 429/5xx is put on a
cooldown (with exponential backoff) and skipped until it recovers, while
requests keep flowing through the remaining keys.
"""

import itertools
import os
import threading
import time
from typing import Any

from google import genai
from google.genai import errors

DEFAULT_COOLDOWN_SECONDS = 60.0
MAX_COOLDOWN_SECONDS = 900.0
DEFAULT_MODEL = "gemini-flash-latest"


class _KeyState:
    __slots__ = ("key", "cooldown_until", "cooldown_seconds")

    def __init__(self, key: str) -> None:
        self.key = key
        self.cooldown_until = 0.0
        self.cooldown_seconds = DEFAULT_COOLDOWN_SECONDS

    def is_available(self) -> bool:
        return time.monotonic() >= self.cooldown_until

    def mark_rate_limited(self) -> None:
        self.cooldown_until = time.monotonic() + self.cooldown_seconds
        self.cooldown_seconds = min(self.cooldown_seconds * 2, MAX_COOLDOWN_SECONDS)

    def mark_success(self) -> None:
        self.cooldown_seconds = DEFAULT_COOLDOWN_SECONDS


class GeminiKeyPool:
    """Round-robins Gemini API calls across a pool of keys."""

    def __init__(self, api_keys: list[str] | None = None) -> None:
        keys = api_keys or _load_keys_from_env()
        if not keys:
            raise ValueError(
                "No Gemini API keys provided. Set GEMINI_API_KEYS (comma-separated) "
                "or GEMINI_API_KEY_1, GEMINI_API_KEY_2, ... in the environment, "
                "or pass api_keys explicitly."
            )
        self._states = [_KeyState(k) for k in keys]
        self._clients: dict[str, genai.Client] = {}
        self._lock = threading.Lock()
        self._cycle = itertools.cycle(range(len(self._states)))

    def _client_for(self, key: str) -> genai.Client:
        client = self._clients.get(key)
        if client is None:
            client = genai.Client(api_key=key)
            self._clients[key] = client
        return client

    def _next_state(self) -> _KeyState:
        with self._lock:
            for _ in range(len(self._states)):
                state = self._states[next(self._cycle)]
                if state.is_available():
                    return state
            # every key is cooling down: wait for whichever frees up soonest
            return min(self._states, key=lambda s: s.cooldown_until)

    def generate_content(self, *, model: str = DEFAULT_MODEL, contents: Any, **kwargs: Any):
        """Calls generateContent, rotating to the next key on 429/5xx errors."""
        last_error: Exception | None = None
        attempts = len(self._states) * 2

        for _ in range(attempts):
            state = self._next_state()
            if not state.is_available():
                time.sleep(max(0.0, state.cooldown_until - time.monotonic()))

            client = self._client_for(state.key)
            try:
                response = client.models.generate_content(
                    model=model, contents=contents, **kwargs
                )
            except errors.APIError as exc:
                last_error = exc
                if exc.code == 429 or exc.code >= 500:
                    state.mark_rate_limited()
                    continue
                raise
            else:
                state.mark_success()
                return response

        raise RuntimeError(
            f"All {len(self._states)} Gemini API keys are rate-limited or failing"
        ) from last_error


def _load_keys_from_env() -> list[str]:
    combined = os.environ.get("GEMINI_API_KEYS", "")
    keys = [k.strip() for k in combined.split(",") if k.strip()]
    if keys:
        return keys

    numbered = []
    i = 1
    while True:
        key = os.environ.get(f"GEMINI_API_KEY_{i}")
        if not key:
            break
        numbered.append(key)
        i += 1
    return numbered
