"""Command-line entry point for the query-time retrieval pipeline.

Usage:
    python -m retrieval.cli "some question about the knowledge graph"
    python -m retrieval.cli            # prompts for input interactively
"""

from __future__ import annotations

import json
import sys

from retrieval.graph import answer_question


def _read_input(argv: list[str]) -> str:
    if argv:
        return " ".join(argv)
    return input("Question: ").strip()


def main() -> None:
    question = _read_input(sys.argv[1:])
    if not question:
        print("No question provided.")
        return

    answer = answer_question(question)
    print(json.dumps(answer.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
