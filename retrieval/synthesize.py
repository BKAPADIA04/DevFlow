"""synthesize_answer node: the final LLM call, answering strictly from the
assembled evidence — never unsupported model knowledge — and tagging the
answer with its source (graph_traversal vs. fallback_text_search) for
transparency, per CLAUDE.md §5 and MDs/DevFlow-Workflow-1.md step 8/9.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from extraction.llm import get_llm
from retrieval.models import AnswerResult
from retrieval.prompts import SYNTHESIS_SYSTEM_PROMPT, build_synthesis_user_prompt
from retrieval.state import RetrievalState


def synthesize_answer_node(state: RetrievalState) -> dict:
    evidence = state["evidence"]

    if evidence is None or (not evidence.paths and not evidence.text_snippets):
        return {
            "answer": AnswerResult(
                answer="I don't have enough information in the knowledge graph to answer this.",
                source=evidence.source if evidence else "fallback_text_search",
                has_sufficient_evidence=False,
                cited_entity_ids=[],
            )
        }

    user_prompt = build_synthesis_user_prompt(
        question=state["question"],
        evidence_text=evidence.to_prompt_text(),
        source=evidence.source,
    )

    try:
        llm = get_llm().with_structured_output(AnswerResult)
        answer: AnswerResult = llm.invoke(
            [
                SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
        )
        answer.source = evidence.source
    except Exception:  # noqa: BLE001 — synthesis failure must not crash the request
        answer = AnswerResult(
            answer="I found evidence but couldn't generate an answer from it.",
            source=evidence.source,
            has_sufficient_evidence=False,
            cited_entity_ids=[],
        )

    return {"answer": answer}
