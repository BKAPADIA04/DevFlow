"""Table-driven tests for retrieval/cypher_validator.py's pure-regex checks
(read-only, schema whitelist, resource limits, parameter safety) — the
parts that don't need a live Neo4j EXPLAIN call. Each case is one of the
exact gaps CLAUDE.md §8 names, plus known-good queries (the three
few-shot examples from retrieval/prompts.py) that must all pass every
pre-EXPLAIN check.
"""

from __future__ import annotations

import pytest

from retrieval.cypher_validator import (
    _check_parameter_safety,
    _check_read_only,
    _check_resource_limits,
    _check_schema_whitelist,
    _strip_string_literals,
)

GOOD_QUERIES = [
    "MATCH (i:Incident {id: $entry_id}) "
    "OPTIONAL MATCH (i)<-[:MAY_CAUSE]-(dep:Deployment)<-[:DEPLOYED_AS]-(c:Commit) "
    "OPTIONAL MATCH (dev:Developer)-[:AUTHORED]->(c) "
    "RETURN i, dep, c, dev LIMIT 50",
    "MATCH (r:Repository {id: $entry_id}) "
    "OPTIONAL MATCH (r)-[:CONTAINS]->(pr:PullRequest) "
    "OPTIONAL MATCH (pr)-[:TRIGGERS]->(dep:Deployment)-[:MAY_CAUSE]->(inc:Incident) "
    "RETURN r, pr, dep, inc LIMIT 50",
    "MATCH (r:Repository {id: $entry_id}) "
    "OPTIONAL MATCH (r)-[:PROTECTED_BY]->(perm:Permission) "
    "OPTIONAL MATCH (dev:Developer)-[:HAS_PERMISSION]->(perm) "
    "OPTIONAL MATCH (dev)-[:BELONGS_TO]->(team:Team) "
    "OPTIONAL MATCH (team)-[:HAS_PERMISSION]->(perm) "
    "RETURN r, perm, dev, team LIMIT 50",
]


def _all_pre_explain_errors(query: str) -> list[str | None]:
    stripped = _strip_string_literals(query)
    return [
        _check_read_only(stripped),
        _check_schema_whitelist(stripped),
        _check_resource_limits(stripped),
        _check_parameter_safety(stripped),
    ]


@pytest.mark.parametrize("query", GOOD_QUERIES)
def test_good_queries_pass_every_check(query: str):
    assert _all_pre_explain_errors(query) == [None, None, None, None]


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (n:File {id: $entry_id}) SET n.reviewed = true RETURN n",
        "MATCH (n:File {id: $entry_id}) DETACH DELETE n",
        "MERGE (n:File {id: $entry_id}) RETURN n",
        "MATCH (n:File {id: $entry_id}) REMOVE n.path RETURN n",
        "DROP INDEX file_embedding_index",
    ],
)
def test_write_keywords_rejected(query: str):
    error = _check_read_only(_strip_string_literals(query))
    assert error is not None
    assert "write keyword" in error


def test_call_rejected_outright():
    query = "CALL apoc.load.json('http://evil.example/x') YIELD value RETURN value"
    error = _check_read_only(_strip_string_literals(query))
    assert error is not None
    assert "CALL" in error


def test_load_csv_rejected_outright():
    query = "LOAD CSV FROM 'file:///etc/passwd' AS row RETURN row"
    error = _check_read_only(_strip_string_literals(query))
    assert error is not None
    assert "LOAD CSV" in error


def test_invented_relationship_rejected():
    query = "MATCH (n:File {id: $entry_id})-[:DEPENDS_ON]->(m) RETURN m"
    error = _check_schema_whitelist(_strip_string_literals(query))
    assert error is not None
    assert "DEPENDS_ON" in error


def test_invented_label_rejected():
    query = "MATCH (n:Hacker {id: $entry_id}) RETURN n"
    error = _check_schema_whitelist(_strip_string_literals(query))
    assert error is not None
    assert "Hacker" in error


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (n:File {id: $entry_id})-[*]-(m) RETURN m",
        "MATCH (n:File {id: $entry_id})-[:MODIFIES*]-(m) RETURN m",
        "MATCH (n:File {id: $entry_id})-[*2..]-(m) RETURN m",
    ],
)
def test_unbounded_variable_length_path_rejected(query: str):
    error = _check_resource_limits(_strip_string_literals(query))
    assert error is not None
    assert "unbounded" in error


def test_bounded_variable_length_path_accepted():
    query = "MATCH (n:File {id: $entry_id})-[:MODIFIES*1..3]-(m) RETURN m"
    assert _check_resource_limits(_strip_string_literals(query)) is None


def test_missing_entry_id_parameter_rejected():
    query = "MATCH (n:File {id: 'file-auth'}) RETURN n"
    error = _check_parameter_safety(_strip_string_literals(query))
    assert error is not None


def test_string_literal_containing_keyword_is_not_a_false_positive():
    # A property value containing the word "delete" should never trip the
    # read-only check just because it appears inside a string literal.
    query = "MATCH (n:Incident {id: $entry_id}) WHERE n.resolution = 'delete stale cache' RETURN n"
    assert _check_read_only(_strip_string_literals(query)) is None
