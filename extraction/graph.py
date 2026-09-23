"""LangGraph pipeline: input text -> LLM extraction -> schema validation,
with one retry if the LLM's output violates the locked schema.

extract -> validate -> (violations found and no retry used yet) -> extract
                     -> (clean, or retry already used)           -> END
"""

from __future__ import annotations

from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langsmith import traceable

from extraction.llm import get_llm
from extraction.prompts import SYSTEM_PROMPT, build_retry_feedback
from extraction.schema import ALLOWED_EDGES, ExtractedEntity, ExtractedRelationship, ExtractionResult

MAX_ATTEMPTS = 2  # one initial attempt + one retry, per CLAUDE.md §8's
# "retry-once-on-failure" mitigation


class ExtractionState(TypedDict):
    text: str
    attempt: int
    entities: list[ExtractedEntity]
    relationships: list[ExtractedRelationship]
    dropped: list[str]
    retry_feedback: str | None


def _extract_node(state: ExtractionState) -> dict:
    llm = get_llm().with_structured_output(ExtractionResult)

    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    human_content = state["text"]
    if state.get("retry_feedback"):
        human_content += "\n\n" + state["retry_feedback"]
    messages.append(HumanMessage(content=human_content))

    result: ExtractionResult = llm.invoke(messages)

    return {
        "entities": result.entities,
        "relationships": result.relationships,
        "attempt": state["attempt"] + 1,
    }


def _validate_node(state: ExtractionState) -> dict:
    entities = state["entities"]
    relationships = state["relationships"]

    entity_ids = {e.id for e in entities}

    kept_relationships: list[ExtractedRelationship] = []
    dropped: list[str] = []

    for rel in relationships:
        if rel.source_id not in entity_ids or rel.target_id not in entity_ids:
            dropped.append(
                f"{rel.source_type.value}({rel.source_id}) -[{rel.relation.value}]-> "
                f"{rel.target_type.value}({rel.target_id}): source or target not "
                "among extracted entities"
            )
            continue
        if rel.as_edge() not in ALLOWED_EDGES:
            dropped.append(
                f"{rel.source_type.value} -[{rel.relation.value}]-> "
                f"{rel.target_type.value}: not a valid edge in the locked schema"
            )
            continue
        kept_relationships.append(rel)

    return {"relationships": kept_relationships, "dropped": dropped}


def _route_after_validate(state: ExtractionState) -> str:
    if state["dropped"] and state["attempt"] < MAX_ATTEMPTS:
        return "retry"
    return "done"


def _prepare_retry_node(state: ExtractionState) -> dict:
    return {"retry_feedback": build_retry_feedback(state["dropped"]), "dropped": []}


def build_extraction_graph():
    graph = StateGraph(ExtractionState)

    graph.add_node("extract", _extract_node)
    graph.add_node("validate", _validate_node)
    graph.add_node("prepare_retry", _prepare_retry_node)

    graph.set_entry_point("extract")
    graph.add_edge("extract", "validate")
    graph.add_conditional_edges(
        "validate", _route_after_validate, {"retry": "prepare_retry", "done": END}
    )
    graph.add_edge("prepare_retry", "extract")

    return graph.compile()


@traceable(name="devflow_extraction")
def extract(text: str) -> ExtractionResult:
    """Runs the extraction pipeline on one piece of input text."""

    app = build_extraction_graph()
    final_state: ExtractionState = app.invoke(
        {
            "text": text,
            "attempt": 0,
            "entities": [],
            "relationships": [],
            "dropped": [],
            "retry_feedback": None,
        }
    )
    return ExtractionResult(
        entities=final_state["entities"], relationships=final_state["relationships"]
    )
