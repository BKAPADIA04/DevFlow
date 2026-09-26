"""Unit tests for retrieval/graph.py's conditional-edge routing functions.

Pure logic, no LLM/DB — each test hand-builds a minimal RetrievalState dict
covering one branch.
"""

from __future__ import annotations

from retrieval.graph import _route_after_confidence, _route_after_results, _route_after_validate
from retrieval.state import MAX_CYPHER_ATTEMPTS


def test_route_after_confidence_high():
    assert _route_after_confidence({"route": "graph"}) == "graph"


def test_route_after_confidence_low():
    assert _route_after_confidence({"route": "fallback"}) == "fallback"


def test_route_after_confidence_none():
    assert _route_after_confidence({"route": None}) == "fallback"


def test_route_after_validate_valid():
    state = {"cypher": "MATCH (n) RETURN n", "cypher_attempt": 1}
    assert _route_after_validate(state) == "execute"


def test_route_after_validate_invalid_with_retries_left():
    state = {"cypher": None, "cypher_attempt": 1}
    assert MAX_CYPHER_ATTEMPTS > 1
    assert _route_after_validate(state) == "retry"


def test_route_after_validate_invalid_exhausted():
    state = {"cypher": None, "cypher_attempt": MAX_CYPHER_ATTEMPTS}
    assert _route_after_validate(state) == "fallback"


def test_route_after_results_with_rows():
    assert _route_after_results({"raw_records": [object()]}) == "assemble"


def test_route_after_results_empty():
    assert _route_after_results({"raw_records": []}) == "fallback"


def test_route_after_results_none():
    assert _route_after_results({"raw_records": None}) == "fallback"
