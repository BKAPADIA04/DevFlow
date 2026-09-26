"""Unit tests for retrieval/nodes/confidence.py's scoring logic.

Feeds hand-built candidate lists (no vector search, no DB) and asserts
accept/reject at the threshold boundaries.
"""

from __future__ import annotations

from extraction.schema import EntityType
from retrieval.models import EntryPointCandidate, QueryExtraction
from retrieval.nodes.confidence import check_confidence_node


def _extraction(entity_types: list[EntityType] | None = None) -> QueryExtraction:
    return QueryExtraction(
        entities=["x"], entity_types=entity_types or [], intent="test", search_terms=["x"]
    )


def test_clear_winner_is_accepted():
    candidates = [
        EntryPointCandidate(node_id="a", node_type=EntityType.FILE, score=0.95, properties={}),
        EntryPointCandidate(node_id="b", node_type=EntityType.FILE, score=0.5, properties={}),
    ]
    state = {"candidates": candidates, "extraction": _extraction()}
    result = check_confidence_node(state)
    assert result["route"] == "graph"
    assert result["entry_point"].node_id == "a"


def test_close_tie_is_rejected():
    candidates = [
        EntryPointCandidate(node_id="a", node_type=EntityType.FILE, score=0.80, properties={}),
        EntryPointCandidate(node_id="b", node_type=EntityType.DEVELOPER, score=0.78, properties={}),
    ]
    state = {"candidates": candidates, "extraction": _extraction()}
    result = check_confidence_node(state)
    assert result["route"] == "fallback"


def test_single_low_score_candidate_is_rejected():
    candidates = [
        EntryPointCandidate(node_id="a", node_type=EntityType.FILE, score=0.4, properties={}),
    ]
    state = {"candidates": candidates, "extraction": _extraction()}
    result = check_confidence_node(state)
    assert result["route"] == "fallback"


def test_single_very_high_score_candidate_is_accepted_without_margin():
    candidates = [
        EntryPointCandidate(node_id="a", node_type=EntityType.FILE, score=0.95, properties={}),
    ]
    state = {"candidates": candidates, "extraction": _extraction()}
    result = check_confidence_node(state)
    assert result["route"] == "graph"


def test_empty_candidates_is_rejected():
    state = {"candidates": [], "extraction": _extraction()}
    result = check_confidence_node(state)
    assert result["route"] == "fallback"
    assert result["entry_point"] is None
    assert result["confidence"] == 0.0


def test_type_match_bonus_can_tip_a_close_call():
    # Both start just above ACCEPT_SCORE (0.75) with a margin (0.03) below
    # ACCEPT_MARGIN (0.05) — without the bonus this would be rejected.
    candidates = [
        EntryPointCandidate(node_id="a", node_type=EntityType.FILE, score=0.76, properties={}),
        EntryPointCandidate(node_id="b", node_type=EntityType.DEVELOPER, score=0.73, properties={}),
    ]
    state = {"candidates": candidates, "extraction": _extraction([EntityType.FILE])}
    result = check_confidence_node(state)
    assert result["route"] == "graph"
    assert result["entry_point"].node_id == "a"
