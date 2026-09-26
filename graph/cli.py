"""Command-line entry point: raw text -> LLM extraction -> live Neo4j graph.

Usage:
    python -m graph.cli "some PR description or incident text"
    python -m graph.cli path/to/text_file.txt
    python -m graph.cli            # prompts for input interactively
"""

from __future__ import annotations

import json
import sys

from extraction.cli import _read_input
from extraction.graph import extract
from graph.constraints import ensure_constraints, ensure_vector_indexes
from graph.loader import load_extraction_result


def main() -> None:
    text = _read_input(sys.argv[1:])
    if not text:
        print("No input text provided.")
        return

    result = extract(text)
    print(json.dumps(result.model_dump(mode="json"), indent=2))

    ensure_constraints()
    ensure_vector_indexes()
    load_extraction_result(result)
    print(
        f"Loaded {len(result.entities)} entities and "
        f"{len(result.relationships)} relationships into Neo4j."
    )


if __name__ == "__main__":
    main()
