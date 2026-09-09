# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

DevFlow is a GraphRAG-powered engineering intelligence agent for a PR/code-review
platform — it traces risk, ownership, and incidents through a live knowledge
graph, exposed via MCP.

The repository is currently at the design stage: there is no application code
yet, only the locked data-model specification that all future implementation
(ingestion scripts, graph loader, MCP query functions) must conform to.

## Architecture: the locked graph schema

`MDs/DevFlow-Relationships.md` is the canonical, locked schema for the
project's knowledge graph and is the source of truth for any future data
modeling, ingestion, or query code. Key points to internalize before writing
any code against this schema:

- **11 entity types**: Repository, Commit, File, PullRequest, Developer,
  Team, Review, CIRun, Deployment, Incident, Permission — and no others.
  Several previously-considered entities (Branch, WebhookEvent, Artifact,
  TestResult, Approval/ChangeRequest, Issue, Environment, Role) were
  deliberately merged into properties on these 11 nodes rather than kept as
  separate nodes/edges, because they added graph hops without adding
  reasoning value. The "What got merged into properties" table documents
  exactly where each one went and why — check it before reintroducing any of
  those as a first-class entity.
- **24 relationships** connect the 11 entities; the file lists the full set
  along with a per-entity property schema (ID fields, property names, which
  relationship each foreign-key-style field backs).
- Foreign-key-style properties (e.g. `Commit.author_id`, `Deployment.commit_hash`)
  intentionally duplicate what the graph edges already express. The edges are
  what the query layer traverses; the ID properties are what a loader script
  uses to build those edges and to do direct lookups without a full
  traversal. Keep both when adding new entities/fields.
- The file also documents a coverage check mapping all 10 target question
  types (PR risk analysis, finding reviewers, code ownership, historical PR
  analysis, CI failure investigation, deployment impact analysis, incident
  root-cause, permission/approval reasoning, finding similar past changes,
  impact of a proposed change) to concrete traversal paths through this
  schema, plus one worked sample dataset with an example of every
  relationship. Any schema change should be checked against this coverage
  table so no question type silently becomes unanswerable.

Do not make ad hoc additions to the entity/relationship set without first
updating `MDs/DevFlow-Relationships.md` — it is the locked reference other
phases (data generation, graph loader, MCP tools) are meant to build against.

## Linting

Markdown files are linted with `markdownlint-cli`:

```bash
npx markdownlint-cli "MDs/**/*.md" "*.md"
```

`.markdownlint.json` at the repo root disables `MD013` (line-length) inside
tables, since the schema/coverage tables in `MDs/DevFlow-Relationships.md`
contain real identifiers and property names that can't be wrapped without
breaking table syntax. Line-length is still enforced outside of tables, and
fenced code blocks must always have a language tag (`MD040`) — use `text`
for the plain-text diagrams/property listings in that file.
