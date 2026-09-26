"""Prompt templates for the query-time retrieval pipeline.

Schema vocabulary (entity types, id fields, allowed edges) is imported from
extraction/schema_text.py — the same text extraction/prompts.py uses — so
the extraction-side and retrieval-side prompts can never describe a
different schema than the one actually loaded into Neo4j.
"""

from __future__ import annotations

from extraction.schema_text import EDGE_LINES, ENTITY_TYPES_LINE, RELATION_TYPES_LINE

# --- extract_query -----------------------------------------------------

QUERY_EXTRACTION_SYSTEM_PROMPT = f"""\
You extract structured search information from a user's question about an \
engineering knowledge graph, so the system can find the right entry-point \
node and decide how to traverse the graph.

Allowed entity types (exactly these 11, no others — only use one in \
`entity_types` if you are confident, leave it out otherwise):
{ENTITY_TYPES_LINE}

Rules:
1. `entities`: pull out the concrete things the question names or implies \
(a file path, a PR/commit/incident id, a person's name, a team name, etc.) \
as they appear in the question — do not normalize or invent an id format.
2. `entity_types`: only include a type here if the question's wording makes \
it genuinely clear (e.g. "file" -> File, "incident" -> Incident, a person's \
name -> Developer). Leave this empty rather than guessing.
3. `relationships`: short free-text phrases for any relationship the \
question implies (e.g. "caused by", "has permission to modify", "reviewed").
4. `intent`: one short label for the kind of question being asked. Prefer \
one of: pr_risk_analysis, finding_reviewers, code_ownership, \
historical_pr_analysis, ci_failure_investigation, deployment_impact, \
incident_root_cause, permission_reasoning, similar_past_changes, \
change_impact — but use another short label if none of these fit.
5. `search_terms`: the phrase(s) that should be embedded to find the \
graph's entry-point node — usually the main entity mention itself, plus \
any distinguishing context from the question.
"""


# --- generate_cypher -----------------------------------------------------

CYPHER_SYSTEM_PROMPT = f"""\
You are a Cypher query generator for a Neo4j graph database.

ALLOWED NODE LABELS (use ONLY these — do not invent others):
{ENTITY_TYPES_LINE}

ALLOWED RELATIONSHIP TYPES (use ONLY these — do not invent others):
{RELATION_TYPES_LINE}

ALLOWED (source)-[relation]->(target) EDGES (only traverse one of these \
directed edges at each hop — do not chain labels/relationships into a \
combination that isn't listed here):
{EDGE_LINES}

RULES:
- Read-only queries ONLY. Never generate CREATE, MERGE, DELETE, SET, REMOVE, \
DROP, CALL, or LOAD CSV.
- Use only the node labels and relationship types listed above.
- Always start from the given entry-point node using the parameter \
`$entry_id` for its id — NEVER inline the id as a string literal. Anchor \
the query with `MATCH (n:<EntryLabel> {{<id_field>: $entry_id}})` using the \
exact label and id field given below.
- Prefer OPTIONAL MATCH for relationships that may not exist, so the query \
returns partial results instead of nothing.
- Add a LIMIT clause to bound how many rows come back.
- Return the query as plain Cypher text only — no explanation, no markdown \
formatting, no code fences.

EXAMPLES:

Entry point: Incident, id field `id`, intent: incident_root_cause
Question: "Which developer was involved in the PR that introduced the \
change related to this incident?"
Cypher:
MATCH (i:Incident {{id: $entry_id}})
OPTIONAL MATCH (i)<-[:MAY_CAUSE]-(dep:Deployment)<-[:DEPLOYED_AS]-(c:Commit)
OPTIONAL MATCH (dev:Developer)-[:AUTHORED]->(c)
OPTIONAL MATCH (pr:PullRequest)-[:CONTAINS]->(c)
OPTIONAL MATCH (creator:Developer)-[:CREATES]->(pr)
RETURN i, dep, c, dev, pr, creator
LIMIT 50

Entry point: Repository, id field `id`, intent: deployment_impact
Question: "What incidents are connected to this repository through \
deployments or CI failures?"
Cypher:
MATCH (r:Repository {{id: $entry_id}})
OPTIONAL MATCH (r)-[:CONTAINS]->(pr:PullRequest)
OPTIONAL MATCH (pr)-[:TRIGGERS]->(dep:Deployment)-[:MAY_CAUSE]->(inc1:Incident)
OPTIONAL MATCH (pr)-[:TRIGGERS]->(ci:CIRun)-[:TESTS]->(c:Commit)
OPTIONAL MATCH (pr)-[:RELATED_TO]->(inc2:Incident)
RETURN r, pr, dep, inc1, ci, c, inc2
LIMIT 50

Entry point: Repository, id field `id`, intent: permission_reasoning
Question: "Who has permission to modify this repository and what team are \
they part of?"
Cypher:
MATCH (r:Repository {{id: $entry_id}})
OPTIONAL MATCH (r)-[:PROTECTED_BY]->(perm:Permission)
OPTIONAL MATCH (dev:Developer)-[:HAS_PERMISSION]->(perm)
OPTIONAL MATCH (dev)-[:BELONGS_TO]->(team:Team)
OPTIONAL MATCH (team)-[:HAS_PERMISSION]->(perm)
RETURN r, perm, dev, team
LIMIT 50
"""

CYPHER_RETRY_SUFFIX_TEMPLATE = """\

Your previous query was rejected: {error}

Produce a corrected query for the same entry point and intent, following \
the rules above exactly.
"""


def build_cypher_user_prompt(
    *, question: str, intent: str, entry_label: str, id_field: str
) -> str:
    return (
        f"Entry point: {entry_label}, id field `{id_field}`, intent: {intent}\n"
        f"Question: {question}\n"
        "Generate the Cypher query."
    )


# --- synthesize_answer -----------------------------------------------------

SYNTHESIS_SYSTEM_PROMPT = """\
You answer engineering questions using ONLY the evidence provided below — \
never your own general knowledge about software engineering or this \
specific codebase. The evidence is either a traced graph path or a \
lower-confidence flat text search result; its source is given to you.

Rules:
1. Base your answer strictly on the evidence. If it directly answers the \
question, answer confidently and cite the relevant entity ids.
2. If the evidence is incomplete or doesn't actually answer the question, \
set has_sufficient_evidence to false and say so explicitly in the answer \
instead of guessing or filling gaps with assumptions.
3. If the evidence came from a fallback text search (lower precision than \
a traced graph path), mention that the answer is less precise and suggest \
rephrasing with a specific file, PR, or incident id if helpful.
"""


def build_synthesis_user_prompt(*, question: str, evidence_text: str, source: str) -> str:
    return (
        f"Question: {question}\n"
        f"Evidence source: {source}\n"
        f"Evidence:\n{evidence_text}\n"
    )
