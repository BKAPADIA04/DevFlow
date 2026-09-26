"""LangGraph state for the query-time retrieval pipeline.

Mirrors extraction/graph.py's ExtractionState: a plain TypedDict, no
checkpointer configured (stateless, single-shot per question — same
tradeoff extraction already makes).
"""

from __future__ import annotations

from typing import Literal, TypedDict

from neo4j import Record

from retrieval.models import AnswerResult, EntryPointCandidate, EvidenceBundle, QueryExtraction


class RetrievalState(TypedDict):
    question: str

    # extract_query
    extraction: QueryExtraction | None

    # retrieve_entry_points / check_confidence
    candidates: list[EntryPointCandidate]
    entry_point: EntryPointCandidate | None
    confidence: float
    route: Literal["graph", "fallback"] | None

    # generate_cypher / validate_cypher
    cypher: str | None
    cypher_attempt: int
    cypher_error: str | None

    # execute_graph_query / check_results
    raw_records: list[Record] | None

    # assemble_evidence / fallback_search
    evidence: EvidenceBundle | None

    # synthesize_answer
    answer: AnswerResult | None


MAX_CYPHER_ATTEMPTS = 2
