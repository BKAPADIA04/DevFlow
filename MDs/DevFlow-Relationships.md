# Engineering Intelligence Agent — Final Relationship Table (Locked, Trimmed)

This is the final, canonical, trimmed-down list of graph entities and
relationships for the PR platform GraphRAG project. All future data
modeling, ingestion scripts, and MCP query functions should follow this
exact table. This version replaces the earlier 19-entity/40-relationship
draft — several entities were merged into properties on other nodes,
since they added hops without adding any new reasoning value.

## Entities (dots) — 11 total

```text
Repository, Commit, File, PullRequest, Developer, Team,
Review, CIRun, Deployment, Incident, Permission
```

## What got merged into properties (and why)

| Removed entity | Where it went | Why it's safe |
| --- | --- | --- |
| Branch | `PullRequest.target_branch` (property) | Never traversed, just a label |
| WebhookEvent | Removed entirely | Not used by our 10 core question types |
| Artifact | `Deployment.artifact_id` (property) | We only ask "what got deployed" |
| TestResult | `CIRun.status` (passed/failed) | Per-test-suite detail isn't needed |
| Approval / ChangeRequest | `Review.result` (property) | Just the outcome of a Review |
| Issue | Merged into Incident, via `Incident.stage` | Both mean "something was wrong" |
| Environment | `Deployment.environment` (property) | Only ever filtered on |
| Role | Merged into Permission | Splitting added a hop, no extra value |

## Relationships (lines) — 27 total, 18 distinct types

```text
Repository  CONTAINS        Commit
Repository  CONTAINS        File
Repository  CONTAINS        PullRequest
Repository  PROTECTED_BY    Permission

Developer   OWNS            Repository
Team        OWNS            Repository
Developer   CREATES         PullRequest
Developer   AUTHORED        Commit
Developer   PERFORMS        Review
Developer   BELONGS_TO      Team
Developer   HAS_PERMISSION  Permission

Team        OWNS            File
Team        HAS_PERMISSION  Permission

PullRequest MODIFIES        File
PullRequest CONTAINS        Commit
PullRequest RECEIVES        Review
PullRequest TRIGGERS        CIRun
PullRequest TRIGGERS        Deployment
PullRequest RELATED_TO      Incident

Commit      PARENT_OF       Commit
Commit      MODIFIES        File
Commit      DEPLOYED_AS     Deployment

File        OWNED_BY        Developer
File        OWNED_BY        Team
File        REQUIRES_REVIEW_FROM  Team

CIRun       TESTS           Commit

Deployment  MAY_CAUSE       Incident
```

## Coverage check — all 10 question types still answerable

| Question type | Path through the trimmed graph |
| --- | --- |
| PR risk analysis | File ownership + past Incidents via Deployment/PullRequest |
| Finding reviewers | File → REQUIRES_REVIEW_FROM → Team → members |
| Code ownership | File → OWNED_BY |
| Historical PR analysis | Commit → PARENT_OF chain + PRs touching same File |
| CI failure investigation | CIRun.status + which Commits it TESTS |
| Deployment impact analysis | Deployment.environment + MAY_CAUSE → Incident |
| Incident root-cause | Incident ← Deployment ← Commit ← Developer |
| Permission / approval reasoning | (Developer\|Team) → HAS_PERMISSION → Permission ← PROTECTED_BY ← Repository |
| Finding similar past changes | File ← MODIFIES ← Commit (reverse lookup) |
| Impact of a proposed change | File ownership + Incident history + review reqs |

## Status

This trimmed table (11 entities, 27 relationships across 18 distinct
types) is now locked as the final schema. Any future phase (data
generation, graph loader, query functions, MCP tools) should reference
this exact table — no ad hoc additions without updating this file first.

---

## Detailed entity schema (properties for each node)

Each entity below lists its ID field, core properties, and the merged-in
properties absorbed from the entities we cut (marked with *).

### Repository

```text
id            string, unique   e.g. "repo-devflow-core"
name          string           e.g. "devflow-core"
visibility    string           "public" | "private"
created_at    datetime
```

### Commit

```text
hash          string, unique   e.g. "a1b2c3d"
message       string           commit message text
author_id     string           → links to Developer.id (via AUTHORED)
repo_id       string           → links to Repository.id (via CONTAINS)
date          datetime
parent_hash   string, nullable → self-reference (via PARENT_OF)
```

### File

```text
id            string, unique   e.g. "repo-devflow-core:src/auth.py"
path          string           e.g. "src/auth.py"
repo_id       string           → links to Repository.id (via CONTAINS)
```

### PullRequest

```text
id                string, unique   e.g. "PR-142"
title             string
description       string
author_id         string           → links to Developer.id (via CREATES)
repo_id           string           → links to Repository.id (via CONTAINS)
target_branch     string           * merged from Branch — e.g. "main"
status            string           "open" | "merged" | "closed"
created_at        datetime
merged_at         datetime, nullable
```

### Developer

```text
id            string, unique   e.g. "dev-maria"
name           string
email          string
team_id        string           → links to Team.id (via BELONGS_TO)
```

### Team

```text
id            string, unique   e.g. "team-platform"
name           string
```

### Review

```text
id                string, unique
pull_request_id   string           → links to PullRequest.id (via RECEIVES)
reviewer_id        string           → links to Developer.id (via PERFORMS)
result             string           * merged from Approval/ChangeRequest
                                     "approved" | "changes_requested" | "commented"
comment             string
created_at          datetime
```

### CIRun

```text
id            string, unique
pull_request_id string          → links to PullRequest.id (via TRIGGERS)
commit_hash    string           → links to Commit.hash (via TESTS)
status         string           * merged from TestResult
                                  "pending" | "passed" | "failed"
started_at     datetime
finished_at    datetime, nullable
```

### Deployment

```text
id             string, unique
pull_request_id string          → links to PullRequest.id (via TRIGGERS)
commit_hash     string          → links to Commit.hash (via DEPLOYED_AS)
environment      string          * merged from Environment
                                   "staging" | "production"
artifact_id       string          * merged from Artifact — build output reference
deployed_at        datetime
```

### Incident

```text
id             string, unique   e.g. "INC-089"
severity        string           "SEV1" | "SEV2" | "SEV3"
stage            string           * merged from Issue
                                    "pre-prod" | "production"
root_cause        string
resolution         string
deployment_id       string, nullable → links to Deployment.id (via MAY_CAUSE)
pull_request_id      string, nullable → links to PullRequest.id (via RELATED_TO)
date                   datetime
```

### Permission

```text
id            string, unique
role_name      string           * merged from Role — e.g. "admin", "write", "read"
grants         string           what this permission allows, e.g. "merge_pr",
                                  "approve_review", "manage_webhooks"
repo_id         string          → links to Repository.id (via PROTECTED_BY)
```

---

## Notes on foreign-key style fields vs. graph edges

Some properties above (like `author_id` on Commit, or `commit_hash` on
Deployment) look like duplicate information once the actual graph edges
(AUTHORED, DEPLOYED_AS) exist. This is intentional:

- The **graph edges** are what the query layer traverses ("who authored
  this commit," "what got deployed").
- The **ID properties** are what the data-loading script uses to build
  those edges in the first place, and they're also convenient for direct
  lookups without a full traversal (e.g. quickly filtering all commits by
  one author before deciding whether to traverse further).

This keeps the loader script simple: read each entity's flat JSON record,
create the node, then use its foreign-key-style fields to create the
matching edges.

---

## Example fake data (sample records)

A small set of sample entity records, used consistently below to show
one concrete example of every relationship.

```text
Developers:
  dev-maria   (Maria Chen, team-platform)
  dev-sam     (Sam Okafor, team-webhooks)
  dev-dan     (Dan Lee, team-platform)

Teams:
  team-platform   (owns repo-devflow-core, owns File src/auth.py)
  team-webhooks   (owns File src/webhook_sender.py)

Repository:
  repo-devflow-core   (private)

Files:
  file-auth       src/auth.py         (owned by team-platform)
  file-webhook    src/webhook_sender.py (owned by team-webhooks)

Commits:
  commit-a1b2c3d   (by dev-maria, modifies file-auth)
  commit-e4f5g6h   (by dev-sam, modifies file-webhook, parent: a1b2c3d)

PullRequest:
  PR-142   "Fix token refresh bug"   by dev-maria, targets "main",
           modifies file-auth, contains commit-a1b2c3d

Review:
  REV-501   on PR-142, by dev-dan, result: "changes_requested"

CIRun:
  CI-901   for PR-142, tests commit-a1b2c3d, status: "failed"

Deployment:
  DEPLOY-034   for PR-142, deploys commit-a1b2c3d, environment: "production"

Incident:
  INC-089   severity SEV2, stage "production",
            caused by DEPLOY-034, related to PR-142

Permission:
  PERM-01   role_name "admin", grants "merge_pr, approve_review",
            applies to repo-devflow-core
```

---

## Example relationship instances

Each of the 27 relationships shown with one concrete example from the
sample data above.

| Relationship | Example |
| --- | --- |
| Repository CONTAINS Commit | repo-devflow-core CONTAINS commit-a1b2c3d |
| Repository CONTAINS File | repo-devflow-core CONTAINS file-auth |
| Repository CONTAINS PullRequest | repo-devflow-core CONTAINS PR-142 |
| Repository PROTECTED_BY Permission | repo-devflow-core PROTECTED_BY PERM-01 |
| Developer OWNS Repository | dev-maria OWNS repo-devflow-core |
| Team OWNS Repository | team-platform OWNS repo-devflow-core |
| Developer CREATES PullRequest | dev-maria CREATES PR-142 |
| Developer AUTHORED Commit | dev-maria AUTHORED commit-a1b2c3d |
| Developer PERFORMS Review | dev-dan PERFORMS REV-501 |
| Developer BELONGS_TO Team | dev-maria BELONGS_TO team-platform |
| Developer HAS_PERMISSION Permission | dev-maria HAS_PERMISSION PERM-01 |
| Team OWNS File | team-platform OWNS file-auth |
| Team HAS_PERMISSION Permission | team-platform HAS_PERMISSION PERM-01 |
| PullRequest MODIFIES File | PR-142 MODIFIES file-auth |
| PullRequest CONTAINS Commit | PR-142 CONTAINS commit-a1b2c3d |
| PullRequest RECEIVES Review | PR-142 RECEIVES REV-501 |
| PullRequest TRIGGERS CIRun | PR-142 TRIGGERS CI-901 |
| PullRequest TRIGGERS Deployment | PR-142 TRIGGERS DEPLOY-034 |
| PullRequest RELATED_TO Incident | PR-142 RELATED_TO INC-089 |
| Commit PARENT_OF Commit | commit-a1b2c3d PARENT_OF commit-e4f5g6h |
| Commit MODIFIES File | commit-a1b2c3d MODIFIES file-auth |
| Commit DEPLOYED_AS Deployment | commit-a1b2c3d DEPLOYED_AS DEPLOY-034 |
| File OWNED_BY Developer | file-webhook OWNED_BY dev-sam |
| File OWNED_BY Team | file-auth OWNED_BY team-platform |
| File REQUIRES_REVIEW_FROM Team | file-auth REQUIRES_REVIEW_FROM team-platform |
| CIRun TESTS Commit | CI-901 TESTS commit-a1b2c3d |
| Deployment MAY_CAUSE Incident | DEPLOY-034 MAY_CAUSE INC-089 |

### Traceable story this data tells

Put together, this small sample already demonstrates the flagship
traversal: Maria authored a commit to `src/auth.py`, opened PR-142, which
Dan flagged for changes, CI failed on it, it still got deployed to
production, and it caused incident INC-089 — a fully traceable chain from
developer to incident, exactly the kind of answer a plain search tool
could never assemble on its own.
