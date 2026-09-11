# DevFlow — Project File Structure

Based on: `DevFlow-Relationships.md`, `DevFlow-TechStack.md`,
`DevFlow-Cypher-LLM.md`, `DevFlow-Workflow-1.md`

```
devflow/
├── README.md
├── pyproject.toml
├── .env.example
├── docker-compose.yml
│
├── docs/
│   ├── DevFlow-Relationships.md
│   ├── DevFlow-TechStack.md
│   ├── DevFlow-Cypher-LLM.md
│   └── DevFlow-Workflow-1.md
│
├── data/
│   ├── entities/
│   │   ├── developers.json
│   │   ├── teams.json
│   │   ├── repositories.json
│   │   ├── files.json
│   │   ├── commits.json
│   │   ├── pull_requests.json
│   │   ├── reviews.json
│   │   ├── ci_runs.json
│   │   ├── deployments.json
│   │   ├── incidents.json
│   │   └── permissions.json
│   └── source_text/
│       └── raw_descriptions.json
│
├── graph/
│   ├── schema.py
│   ├── connection.py
│   ├── loader.py
│   └── vector_index.py
│
├── extraction/
│   ├── structured_extractor.py
│   ├── entity_resolver.py
│   └── edge_writer.py
│
├── retrieval/
│   ├── entity_intent_extractor.py
│   ├── entry_point_search.py
│   ├── cypher_generator.py
│   ├── validator.py
│   ├── graph_traversal.py
│   ├── fallback_text_search.py
│   └── reranker.py
│
├── synthesis/
│   ├── evidence_assembler.py
│   └── answer_synthesizer.py
│
├── api/
│   ├── main.py
│   └── routes/
│       └── query.py
│
├── scripts/
│   └── seed_sample_data.py
│
└── tests/
    ├── test_graph_loader.py
    ├── test_cypher_generator.py
    ├── test_validator.py
    └── test_retrieval_pipeline.py
```

## Notes

- `retrieval/reranker.py` is included since `DevFlow-TechStack.md`
  reinstates reranking, even though `DevFlow-Workflow-1.md` predates
  that decision.
- `retrieval/cypher_generator.py` + `validator.py` map directly to
  sections 3 and 4 of `DevFlow-Cypher-LLM.md` (generation prompt +
  the 5-check validation layer).
- `extraction/` matches the "Knowledge Graph Construction" pipeline
  from `DevFlow-TechStack.md`'s architecture diagram (source text →
  LLM structured extraction → entity resolution → edge writes).
- No fixed-function query files (e.g. `get_blast_radius.py`) — that
  approach was explicitly replaced by LLM-generated Cypher.

## Open item

`DevFlow-Workflow-1.md` still describes the older fixed-function
routing approach, while `DevFlow-Cypher-LLM.md` describes the current
LLM-generated-Cypher approach that superseded it. Worth reconciling
these two docs before implementation starts, so `retrieval/` isn't
built against conflicting descriptions of the same step.
