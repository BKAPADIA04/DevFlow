"""check_confidence node: pure scoring, no LLM/DB call. Decides whether the
top entry-point candidate is trustworthy enough to drive a graph traversal.

Combines top-1 similarity, the margin over the runner-up (guards against
ambiguous ties across different node types), and a small bonus if the
candidate's type matches what extract_query inferred. Thresholds below are
placeholder constants — not derived from real eval data, since no
ground-truth query set exists yet. Flagged for tuning once there's usage
to measure against.

This is also the reranker's designated future slot (CLAUDE.md §8's
reranker-position item, explicitly skipped for this implementation): a
`rerank_candidates` node would sit between retrieve_entry_points and this
node, re-scoring `candidates` before this same threshold logic runs
unchanged.
"""

from __future__ import annotations

from retrieval.state import RetrievalState

HIGH_CONFIDENCE_SCORE = 0.90
ACCEPT_SCORE = 0.75
ACCEPT_MARGIN = 0.05
TYPE_MATCH_BONUS = 0.03


def check_confidence_node(state: RetrievalState) -> dict:
    candidates = state["candidates"]
    extraction = state["extraction"]

    if not candidates:
        return {"entry_point": None, "confidence": 0.0, "route": "fallback"}

    scored = []
    for candidate in candidates:
        score = candidate.score
        if extraction and extraction.entity_types and candidate.node_type in extraction.entity_types:
            score += TYPE_MATCH_BONUS
        scored.append((score, candidate))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    top_score, top_candidate = scored[0]
    margin = top_score - scored[1][0] if len(scored) > 1 else top_score

    confident = top_score >= HIGH_CONFIDENCE_SCORE or (
        top_score >= ACCEPT_SCORE and margin >= ACCEPT_MARGIN
    )

    return {
        "entry_point": top_candidate,
        "confidence": top_score,
        "route": "graph" if confident else "fallback",
    }
