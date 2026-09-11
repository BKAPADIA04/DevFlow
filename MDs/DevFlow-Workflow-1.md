# DevFlow — Full GraphRAG Flow (with Fallback), Worked Example

This is the complete, current-phase flow: no MCP, no agent loop, local LLM
used only for entity/intent extraction and final synthesis. Includes a
fallback path for when graph retrieval fails or comes up empty —
borrowed directly from the LinkedIn paper's production design.

---

## 1. Full flow diagram

```
┌───────────────────────────────────────────────────────────────┐
│ 1. QUESTION COMES IN                                             │
│    "If I change src/auth.py, what could break?"                  │
└─────────────────────────────┬─────────────────────────────────┘
                               ▼
┌───────────────────────────────────────────────────────────────┐
│ 2. ENTITY + INTENT EXTRACTION (local LLM, small structured task) │
│    LLM reads the question and pulls out:                          │
│      entities = { "file": "src/auth.py" }                          │
│      intent   = "impact_analysis"                                   │
└─────────────────────────────┬─────────────────────────────────┘
                               ▼
┌───────────────────────────────────────────────────────────────┐
│ 3. ENTRY-POINT SEARCH (embedding-based, filtered by entity type)   │
│    Embed "src/auth.py" → compare against embeddings of ONLY the    │
│    File-type nodes in the graph (not all node types — this is       │
│    the "typed" filtering trick borrowed from the paper) →           │
│    → best match: File node "src/auth.py" (high confidence)          │
└─────────────────────────────┬─────────────────────────────────┘
                               ▼
                     ┌─────────┴─────────┐
                     │ Confidence check    │
                     └─────────┬─────────┘
              ┌────────────────┴────────────────┐
              ▼ high confidence                   ▼ low / no match
┌───────────────────────────────┐   ┌───────────────────────────────────┐
│ 4a. ROUTING (plain Python)      │   │ 4b. FALLBACK PATH                    │
│     intent "impact_analysis"     │   │     No confident graph entry point    │
│     → call get_blast_radius(     │   │     found. Fall back to plain text    │
│         "src/auth.py")            │   │     search over PR descriptions,       │
└─────────────────┬───────────────┘   │     incident notes, and commit          │
                  ▼                     │     messages (flat embedding search,     │
┌───────────────────────────────┐      │     no graph traversal).                  │
│ 5. GRAPH TRAVERSAL               │      └─────────────────┬───────────────────────┘
│    Run the fixed Cypher query     │                        │
│    for get_blast_radius:           │                        │
│    File → OWNED_BY → Team          │                        │
│    File → REQUIRES_REVIEW_FROM →   │                        │
│           Team                      │                        │
│    File ← MODIFIES ← Commit         │                        │
│    Commit ← CONTAINS ← PullRequest  │                        │
│    PullRequest → RELATED_TO →        │                        │
│           Incident                    │                        │
└─────────────────┬───────────────┘                        │
                  ▼                                          │
┌───────────────────────────────┐                          │
│ 6a. Did the query return any     │                          │
│     results?                       │                          │
└─────────────────┬───────────────┘                          │
        ┌──────────┴──────────┐                               │
        ▼ yes                  ▼ no / query error               │
┌─────────────────┐   ┌─────────────────────────────┐          │
│ Continue to step 7 │   │ FALL BACK to step 4b instead  │──────┘
└─────────┬─────────┘   └─────────────────────────────┘
          ▼
┌───────────────────────────────────────────────────────────────┐
│ 7. EVIDENCE ASSEMBLY                                              │
│    Format the traversal result as a connected PATH (not a flat     │
│    fact list), plus any relevant free-text snippets (PR              │
│    description, incident root-cause note) pulled alongside it.       │
└─────────────────────────────┬─────────────────────────────────┘
                               ▼
┌───────────────────────────────────────────────────────────────┐
│ 8. LLM SYNTHESIS (local model)                                    │
│    LLM receives ONLY the evidence bundle + a strict instruction:   │
│    "answer using only these facts; if evidence is insufficient,     │
│    say so — never guess."                                            │
└─────────────────────────────┬─────────────────────────────────┘
                               ▼
┌───────────────────────────────────────────────────────────────┐
│ 9. ANSWER RETURNED                                                 │
│    Plus a small note on which path was used: graph traversal        │
│    or fallback text search — for transparency and for our evals.    │
└───────────────────────────────────────────────────────────────┘
```

---

## 2. Why the fallback exists (and when it triggers)

Two separate failure points can send the system down the fallback path:

```
Trigger A — Step 3 fails to find a confident entry point
  (e.g. the question mentions something not represented as a node
   at all, or the embedding match score is below a threshold)

Trigger B — Step 5's Cypher query runs but returns an empty result
  (e.g. the entry point was found, but it has no connections of the
   relevant type — a valid but "boring" answer, or a bug in the
   query itself)
```

In both cases, instead of returning an empty or broken answer, the
system falls back to a **plain embedding search over free text**
(PR descriptions, incident notes, commit messages) — the same kind
of "flat RAG" every basic system does, just without graph structure.
This guarantees the user always gets *some* answer, even if it's a
lower-quality one, rather than a hard failure. This exact pattern is
what the LinkedIn paper describes for their production deployment.

### What the fallback answer looks like (lower quality, still useful)
```
Fallback answer for a question with no confident graph entry point:
"I couldn't find a specific tracked component matching your question.
Based on related text I found: [snippets from PR descriptions/incidents
that came up in a plain text search]. This answer is less precise than
our usual graph-traced answers — consider rephrasing with a specific
file, PR, or incident ID if you have one."
```
Marking these answers as lower-confidence (in the returned metadata) is
important — it lets you track in your evals how often the system falls
back, which is itself a useful health metric for the project.

---

## 3. Worked example — full trace, step by step

**Question:** *"If I change src/auth.py, what could break?"*

### Step 2 — Entity + intent extraction
```
LLM output:
  entities = { "file": "src/auth.py" }
  intent   = "impact_analysis"
```

### Step 3 — Entry-point search
```
Embed "src/auth.py" → compare against File-type node embeddings only
Best match: File node "file-auth" (path: src/auth.py)
Confidence: high (0.94 similarity)
→ proceed to step 4a, not the fallback path
```

### Step 4a — Routing
```
intent "impact_analysis" + entity type "file"
→ call get_blast_radius("file-auth")
```

### Step 5 — Graph traversal (using our sample data from before)
```cypher
MATCH (f:File {id: "file-auth"})
OPTIONAL MATCH (f)-[:OWNED_BY]->(owner)
OPTIONAL MATCH (f)-[:REQUIRES_REVIEW_FROM]->(reviewTeam)
OPTIONAL MATCH (c:Commit)-[:MODIFIES]->(f)
OPTIONAL MATCH (pr:PullRequest)-[:CONTAINS]->(c)
OPTIONAL MATCH (pr)-[:RELATED_TO]->(inc:Incident)
RETURN owner, reviewTeam, c, pr, inc
```
Result (using the sample data from earlier):
```
owner: team-platform
reviewTeam: team-platform
commit: commit-a1b2c3d (by dev-maria)
pull_request: PR-142 ("Fix token refresh bug")
incident: INC-089 (SEV2, caused by DEPLOY-034)
```

### Step 6a — Did it return results?
```
Yes → continue to step 7 (no fallback needed this time)
```

### Step 7 — Evidence assembly (formatted as a path)
```
file-auth (src/auth.py)
  → owned by → team-platform
  → requires review from → team-platform
  → modified by → commit-a1b2c3d (author: dev-maria)
      → part of → PR-142 ("Fix token refresh bug")
          → related to → INC-089 (SEV2, production incident)

Free-text snippet attached: INC-089 root cause note —
"payments table lock during index creation caused checkout timeouts"
```
*(Note: this particular root-cause snippet is from our sample incident
data used earlier for illustration — in a real run, whatever incident is
actually linked to this file would be pulled in instead.)*

### Step 8 — LLM synthesis
```
Prompt to local LLM:
  "Using ONLY the evidence below, answer the user's question.
   If evidence is insufficient, say so.

   Evidence: [the assembled path above]
   Question: If I change src/auth.py, what could break?"
```

### Step 9 — Final answer
```
"Changing src/auth.py requires review from team-platform, since they
own this file. The last change to this file (PR-142, 'Fix token
refresh bug', authored by Maria) was linked to a production incident
(INC-089, SEV2). Recommend looping in team-platform for review and
double-checking whether this change touches the same code path that
caused INC-089 before deploying."

[Answer source: graph traversal, high confidence]
```

---

## 4. Worked example — fallback case

**Question:** *"Has anyone mentioned rate limiting issues recently?"*

### Step 2 — Entity + intent extraction
```
entities = { }   (no specific tracked entity mentioned — "rate limiting"
                   isn't a node type in our schema)
intent   = "general_search"
```

### Step 3 — Entry-point search
```
No graph node type matches "rate limiting" well enough.
Confidence: low (below threshold)
→ trigger fallback (Trigger A)
```

### Step 4b — Fallback path
```
Run a plain embedding search over free text fields across all
PR descriptions, incident root-cause notes, and commit messages
for "rate limiting"
→ finds: Incident INC-104 root-cause note mentions
  "unbounded retry logic caused a rate-limit spike on the GitHub API"
```

### Step 9 — Final answer (fallback)
```
"I couldn't find a specific tracked component matching 'rate limiting'
in our system. However, a related note was found: Incident INC-104's
root cause mentions unbounded retry logic causing a rate-limit spike
on the GitHub API. This answer is less precise than our usual
graph-traced answers, since it wasn't reached through a structured
traversal — consider asking about a specific file, PR, or incident ID
for a more complete answer."

[Answer source: fallback text search, low confidence]
```

---

## 5. Why this design is solid for evals later

Tracking `[Answer source: graph traversal | fallback text search]` on
every response gives you, for free, one of your most important eval
metrics: **what percentage of real questions the graph confidently
handles vs. falls back on.** A high fallback rate would tell you the
schema or entry-point matching needs work; a low one tells you the
graph is doing its job. This is exactly the kind of measurable signal
that makes a strong evals section in your final writeup.
