"""Loads the hand-authored seed dataset (data/seed_graph.json) into Neo4j.

Unlike graph/cli.py, this never calls the LLM — data/seed_graph.json is
already in ExtractionResult's shape (entities + relationships), so it's
parsed and validated with Pydantic directly, then written with the same
idempotent loader graph/cli.py uses. Deterministic and free: no API cost,
no extraction flakiness, and the dataset is hand-checked against
extraction/schema.py's ALLOWED_EDGES to cover every one of the 11 entity
types and 18 relationship types.

Usage:
    python -m graph.seed
"""

from __future__ import annotations

import json
from pathlib import Path

from extraction.schema import ExtractionResult
from graph.constraints import ensure_constraints
from graph.loader import load_extraction_result

SEED_FILE = Path(__file__).resolve().parent.parent / "data" / "seed_graph.json"


def main() -> None:
    data = json.loads(SEED_FILE.read_text())
    result = ExtractionResult.model_validate(data)

    ensure_constraints()
    load_extraction_result(result)

    print(
        f"Loaded {len(result.entities)} entities and "
        f"{len(result.relationships)} relationships into Neo4j."
    )


if __name__ == "__main__":
    main()
