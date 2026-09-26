"""LangGraph pipeline for query-time retrieval, mirroring
extraction/graph.py's shape (StateGraph, conditional edges, no
checkpointer — stateless per request):

extract_query -> retrieve_entry_points -> check_confidence
    -> [low]  fallback_search
    -> [high] generate_cypher -> validate_cypher
                  -> [invalid, retries left] generate_cypher (retry)
                  -> [invalid, exhausted]     fallback_search
                  -> [valid]                  execute_graph_query -> check_results
                                                  -> [empty] fallback_search
                                                  -> [rows]  assemble_evidence
(assemble_evidence | fallback_search) -> synthesize_answer -> END
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from langsmith import traceable

from retrieval.evidence import assemble_evidence_node
from retrieval.fallback import fallback_search_node
from retrieval.models import AnswerResult
from retrieval.nodes.confidence import check_confidence_node
from retrieval.nodes.cypher_generation import generate_cypher_node, validate_cypher_node
from retrieval.nodes.entry_points import retrieve_entry_points_node
from retrieval.nodes.execute import execute_graph_query_node
from retrieval.nodes.extract import extract_query_node
from retrieval.state import MAX_CYPHER_ATTEMPTS, RetrievalState
from retrieval.synthesize import synthesize_answer_node


def _route_after_confidence(state: RetrievalState) -> str:
    return "graph" if state["route"] == "graph" else "fallback"


def _route_after_validate(state: RetrievalState) -> str:
    if state["cypher"] is not None:
        return "execute"
    if state["cypher_attempt"] < MAX_CYPHER_ATTEMPTS:
        return "retry"
    return "fallback"


def _route_after_results(state: RetrievalState) -> str:
    return "assemble" if state["raw_records"] else "fallback"


def build_retrieval_graph():
    graph = StateGraph(RetrievalState)

    graph.add_node("extract_query", extract_query_node)
    graph.add_node("retrieve_entry_points", retrieve_entry_points_node)
    graph.add_node("check_confidence", check_confidence_node)
    graph.add_node("generate_cypher", generate_cypher_node)
    graph.add_node("validate_cypher", validate_cypher_node)
    graph.add_node("execute_graph_query", execute_graph_query_node)
    graph.add_node("assemble_evidence", assemble_evidence_node)
    graph.add_node("fallback_search", fallback_search_node)
    graph.add_node("synthesize_answer", synthesize_answer_node)

    graph.set_entry_point("extract_query")
    graph.add_edge("extract_query", "retrieve_entry_points")
    graph.add_edge("retrieve_entry_points", "check_confidence")
    graph.add_conditional_edges(
        "check_confidence",
        _route_after_confidence,
        {"graph": "generate_cypher", "fallback": "fallback_search"},
    )
    graph.add_edge("generate_cypher", "validate_cypher")
    graph.add_conditional_edges(
        "validate_cypher",
        _route_after_validate,
        {"execute": "execute_graph_query", "retry": "generate_cypher", "fallback": "fallback_search"},
    )
    graph.add_conditional_edges(
        "execute_graph_query",
        _route_after_results,
        {"assemble": "assemble_evidence", "fallback": "fallback_search"},
    )
    graph.add_edge("assemble_evidence", "synthesize_answer")
    graph.add_edge("fallback_search", "synthesize_answer")
    graph.add_edge("synthesize_answer", END)

    return graph.compile()


@traceable(name="devflow_retrieval")
def answer_question(question: str) -> AnswerResult:
    """Runs the full retrieval pipeline for one natural-language question."""

    app = build_retrieval_graph()
    final_state: RetrievalState = app.invoke(
        {
            "question": question,
            "extraction": None,
            "candidates": [],
            "entry_point": None,
            "confidence": 0.0,
            "route": None,
            "cypher": None,
            "cypher_attempt": 0,
            "cypher_error": None,
            "raw_records": None,
            "evidence": None,
            "answer": None,
        }
    )
    return final_state["answer"]
