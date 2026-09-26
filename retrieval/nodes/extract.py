"""extract_query node: pulls entities/relationships/intent/search terms out
of the user's question.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from extraction.llm import get_llm
from retrieval.models import QueryExtraction
from retrieval.prompts import QUERY_EXTRACTION_SYSTEM_PROMPT
from retrieval.state import RetrievalState


def extract_query_node(state: RetrievalState) -> dict:
    try:
        llm = get_llm().with_structured_output(QueryExtraction)
        extraction: QueryExtraction = llm.invoke(
            [
                SystemMessage(content=QUERY_EXTRACTION_SYSTEM_PROMPT),
                HumanMessage(content=state["question"]),
            ]
        )
    except Exception:  # noqa: BLE001 — extraction failure degrades to fallback, never crashes
        extraction = QueryExtraction(
            entities=[],
            entity_types=[],
            relationships=[],
            intent="unknown",
            search_terms=[state["question"]],
        )

    return {"extraction": extraction}
