"""generate_cypher / validate_cypher nodes.

generate_cypher builds the prompt from MDs/DevFlow-Cypher-LLM.md §3's shape
(fixed schema vocabulary + entry point + intent + question), with two
deliberate hardenings over the doc's own baseline: few-shot examples from
day one, and the entry-point id always bound as a driver parameter
($entry_id) rather than ever being inlined into the generated Cypher text.

validate_cypher runs the five-check validator (retrieval/cypher_validator.py)
and either accepts the query or feeds the specific failure reason back for
one regeneration attempt, mirroring extraction/graph.py's retry pattern.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from extraction.llm import get_llm
from extraction.schema import ID_FIELD_BY_TYPE
from graph.connection import get_driver
from retrieval.cypher_validator import validate_cypher
from retrieval.prompts import (
    CYPHER_RETRY_SUFFIX_TEMPLATE,
    CYPHER_SYSTEM_PROMPT,
    build_cypher_user_prompt,
)
from retrieval.state import RetrievalState


class _CypherOutput(BaseModel):
    cypher: str


def generate_cypher_node(state: RetrievalState) -> dict:
    entry_point = state["entry_point"]
    extraction = state["extraction"]

    user_prompt = build_cypher_user_prompt(
        question=state["question"],
        intent=extraction.intent if extraction else "unknown",
        entry_label=entry_point.node_type.value,
        id_field=ID_FIELD_BY_TYPE[entry_point.node_type],
    )
    if state.get("cypher_error"):
        user_prompt += CYPHER_RETRY_SUFFIX_TEMPLATE.format(error=state["cypher_error"])

    llm = get_llm().with_structured_output(_CypherOutput)
    result: _CypherOutput = llm.invoke(
        [
            SystemMessage(content=CYPHER_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
    )

    return {
        "cypher": result.cypher,
        "cypher_attempt": state["cypher_attempt"] + 1,
        "cypher_error": None,
    }


def validate_cypher_node(state: RetrievalState) -> dict:
    entry_point = state["entry_point"]
    driver = get_driver()
    with driver.session() as session:
        is_valid, error = validate_cypher(session, state["cypher"], entry_id=entry_point.node_id)

    if is_valid:
        return {}
    return {"cypher": None, "cypher_error": error}
