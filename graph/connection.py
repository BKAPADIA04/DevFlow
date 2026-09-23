"""Neo4j driver connection for the graph-loading pipeline.

Mirrors extraction/llm.py's pattern: load .env at import time (not
lazily), expose one lazily-built singleton. Uses the official `neo4j`
driver directly rather than a LangChain wrapper, per CLAUDE.md §6
("LangChain used narrowly... only for structured output").
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_DRIVER: Driver | None = None


def get_driver() -> Driver:
    global _DRIVER
    if _DRIVER is None:
        _DRIVER = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
        )
    return _DRIVER


def close_driver() -> None:
    global _DRIVER
    if _DRIVER is not None:
        _DRIVER.close()
        _DRIVER = None
