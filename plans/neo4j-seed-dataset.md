# Neo4j Seed Dataset — batch-load a full synthetic knowledge graph

## Context

Phase 1 (Docker Neo4j + `graph/` loader package) is done and pushed:
`docker-compose.yml`, `graph/connection.py`, `graph/constraints.py`,
`graph/loader.py`, `graph/cli.py`. It's fully verified (idempotent MERGE
writes, correct node/relationship counts) but the graph only had
whatever was fed through `graph/cli.py` one text snippet at a time — a
smoke test, not a real dataset.

**Implemented approach**: instead of writing narrative text snippets and
running each through the LLM extraction pipeline (API cost, and subject
to the same occasional Gemini flakiness seen during Phase 1 testing),
the seed dataset is hand-authored directly in `ExtractionResult`'s own
shape — `{"entities": [...], "relationships": [...]}` — and loaded
straight into Neo4j via the existing loader, with **no LLM call at all**.
This is deterministic, free, and — checked by hand against
`extraction/schema.py`'s `ALLOWED_EDGES` while writing it — guarantees
exact coverage of all 11 entity types and all 18 relationship types,
rather than hoping the extractor happens to catch every one.

Still Phase 1 scope (entities/relationships only) — no embeddings/vector
index here.

## Implementation

### `data/seed_graph.json`

19 entities (all 11 entity types represented, e.g. 3 `Developer`,
2 `Team`, 2 `File`, 2 `PullRequest`, 2 `Commit`, 2 `CIRun`,
2 `Deployment`, 1 `Repository`, 1 `Permission`, 1 `Review`,
1 `Incident`) and 44 relationships (all 18 relationship types
represented at least once), extending the worked example already in
`MDs/DevFlow-Relationships.md` ("Example fake data" section) with the
edges that example states only implicitly (e.g. explicit
`File OWNED_BY Team`/`Developer`, `Team`/`Developer HAS_PERMISSION`,
`File REQUIRES_REVIEW_FROM Team`, `Repository CONTAINS Commit`/`File`).

Each entity matches `ExtractedEntity`'s shape (`id`, `type`,
`properties` as a list of `{key, value}` pairs — not a plain dict, same
as `extraction/schema.py`'s `EntityProperty`). Each relationship matches
`ExtractedRelationship`'s shape (`source_id`, `source_type`, `relation`,
`target_id`, `target_type`).

### `graph/seed.py`

```python
"""
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
```

`ExtractionResult.model_validate(data)` reuses the exact same Pydantic
schema the LLM extraction path produces, so `graph/loader.py` (which
only knows how to consume an `ExtractionResult`) needs zero changes —
the loader can't tell the difference between LLM-sourced and
hand-authored input, which is the point.

No `graph/cli.py` changes needed either, since this bypasses extraction
entirely rather than reusing `extract_and_load`.

## Verification (all run and passed)

1. `docker compose up -d` — healthy.
2. `python -m graph.seed` → `Loaded 19 entities and 44 relationships
   into Neo4j.`
3. Queried directly:
   - `MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n` → all 11
     labels present.
   - `MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS n` → all 18
     relationship types present.
4. Re-ran `python -m graph.seed` a second time → identical totals
   (19 nodes, 44 relationships) — idempotency confirmed across the full
   seed dataset, not just a single entity.

## Summary of new/changed files

- `data/seed_graph.json` (new)
- `graph/seed.py` (new)

## Out of scope

Real GitHub/GitLab/CI API ingestion (pulling actual repo history) —
eventual production path per `MDs/DevFlow-TechStack.md`, a separate,
larger build. Vector embeddings/index — still Phase 2, untouched here.
