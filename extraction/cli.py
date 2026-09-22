"""Command-line entry point for the extraction pipeline.

Usage:
    python -m extraction.cli "some PR description or incident text"
    python -m extraction.cli path/to/text_file.txt
    python -m extraction.cli            # prompts for input interactively
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from extraction.graph import extract


def _read_input(argv: list[str]) -> str:
    if argv:
        maybe_path = Path(argv[0])
        if maybe_path.is_file():
            return maybe_path.read_text()
        return " ".join(argv)
    return input("Text to extract from: ").strip()


def main() -> None:
    text = _read_input(sys.argv[1:])
    if not text:
        print("No input text provided.")
        return

    result = extract(text)
    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
