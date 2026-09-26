"""Five-check validator for LLM-generated Cypher, per MDs/DevFlow-Cypher-LLM.md
§4, closing the specific gaps CLAUDE.md §8 names in that doc's denylist.

Every generated query passes through these checks, in order, before it's
allowed anywhere near Neo4j. Failing any check means "don't execute this" —
the caller is expected to route to the fallback (flat text search) or a
regeneration retry, not raise.
"""

from __future__ import annotations

import re

from neo4j import Session

from extraction.schema import EntityType, RelationType

_WRITE_KEYWORDS = ("CREATE", "MERGE", "DELETE", "SET", "REMOVE", "DROP")

# CALL and LOAD CSV are rejected outright, not denylisted by sub-pattern —
# schema-only read queries never legitimately need either, so removing the
# whole category closes CLAUDE.md §8's exact gap (apoc.*/dbms.* procedure
# calls, LOAD CSV file/URL reads) without trying to enumerate every
# dangerous procedure name.
_BANNED_CLAUSES = ("CALL", "LOAD CSV")

_STRING_LITERAL_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
_REL_BRACKET_RE = re.compile(r"\[([^\]]*)\]")
_BOUNDED_VAR_LENGTH_RE = re.compile(r"\*\s*\d*\s*\.\.\s*\d+")

_VALID_LABELS = {t.value for t in EntityType}
_VALID_RELATIONS = {r.value for r in RelationType}

MAX_RESULT_ROWS = 200
QUERY_TIMEOUT_SECONDS = 5.0


def _strip_string_literals(query: str) -> str:
    return _STRING_LITERAL_RE.sub("''", query)


def _check_read_only(stripped: str) -> str | None:
    for keyword in _WRITE_KEYWORDS:
        if re.search(rf"\b{keyword}\b", stripped, re.IGNORECASE):
            return f"query contains a write keyword: {keyword}"
    for clause in _BANNED_CLAUSES:
        if re.search(rf"\b{re.escape(clause)}\b", stripped, re.IGNORECASE):
            return f"query contains a banned clause: {clause}"
    return None


def _check_schema_whitelist(stripped: str) -> str | None:
    for match in re.finditer(r"\(\s*\w*\s*:(\w+)", stripped):
        label = match.group(1)
        if label not in _VALID_LABELS:
            return f"unknown node label: {label}"
    for match in re.finditer(r"\[\s*\w*\s*:(\w+)", stripped):
        relation = match.group(1)
        if relation not in _VALID_RELATIONS:
            return f"unknown relationship type: {relation}"
    return None


def _check_resource_limits(stripped: str) -> str | None:
    for bracket in _REL_BRACKET_RE.findall(stripped):
        if "*" not in bracket:
            continue
        if not _BOUNDED_VAR_LENGTH_RE.search(bracket):
            return f"unbounded variable-length path: [{bracket}]"
    return None


def _check_parameter_safety(stripped: str) -> str | None:
    if "$entry_id" not in stripped:
        return "query must anchor on the $entry_id parameter"
    return None


def validate_cypher(
    session: Session, query: str, *, entry_id: str
) -> tuple[bool, str | None]:
    """Runs all five checks in order. Returns (is_valid, error_reason)."""

    stripped = _strip_string_literals(query)

    error = _check_read_only(stripped)
    if error:
        return False, error

    error = _check_schema_whitelist(stripped)
    if error:
        return False, error

    error = _check_resource_limits(stripped)
    if error:
        return False, error

    error = _check_parameter_safety(stripped)
    if error:
        return False, error

    try:
        session.run(f"EXPLAIN {query}", entry_id=entry_id).consume()
    except Exception as exc:  # noqa: BLE001 — any EXPLAIN failure is a validation failure
        return False, f"query failed EXPLAIN: {exc}"

    return True, None
