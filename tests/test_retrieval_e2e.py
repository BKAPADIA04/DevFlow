"""End-to-end tests against the seeded dataset already loaded in the running
Neo4j container (graph/seed.py) — the user's three example queries from the
retrieval plan. These make real Gemini + real Neo4j calls (no mocking infra
exists yet for the pooled Gemini client, consistent with how graph/seed.py
and graph/cli.py were verified earlier in this project), so they're skipped
by default and only run when RUN_LIVE_E2E=1 is set — the Gemini free tier's
daily request quota (20 req/day/project for gemini-3.6-flash, confirmed via
a live 429 during development) makes it unsafe to run these on every CI/test
invocation.

    RUN_LIVE_E2E=1 pytest tests/test_retrieval_e2e.py
"""

from __future__ import annotations

import os

import pytest

from retrieval.graph import answer_question

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_E2E") != "1",
    reason="live Gemini + Neo4j calls; set RUN_LIVE_E2E=1 to run "
    "(mind the free-tier daily quota — see module docstring)",
)


def test_incident_root_cause():
    answer = answer_question(
        "Which developer was involved in the PR that introduced the change "
        "related to incident INC-089?"
    )
    assert answer.source == "graph_traversal"
    assert "dev-maria" in answer.cited_entity_ids


def test_deployment_incident_connectivity():
    answer = answer_question(
        "What incidents are connected to repo-devflow-core through deployments "
        "or CI failures?"
    )
    assert "INC-089" in answer.cited_entity_ids


def test_permission_reasoning():
    answer = answer_question(
        "Who has permission to modify repo-devflow-core and what team are they "
        "part of?"
    )
    assert "team-platform" in answer.cited_entity_ids
