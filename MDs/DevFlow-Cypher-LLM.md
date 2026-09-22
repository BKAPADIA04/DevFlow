# DevFlow — Retrieval Strategy: LLM-Generated Cypher

This document covers, in detail, how graph retrieval works in the
current phase of DevFlow: the LLM generates the actual Cypher query
for every question, with a validation layer as the safety boundary.
No fixed, pre-written query functions are used at this stage.

---

## 1. The core design principle

```
LLM decides WHAT the user wants   (entity + intent extraction)
LLM decides HOW to retrieve it     (writes the Cypher query itself)
Our validation layer decides IF that query is allowed to run
```

This is a deliberate choice, not a shortcut. It trades some of the
reliability of hand-written, pre-tested queries for much greater
flexibility — the system can answer genuinely novel questions from
day one, without us having anticipated every possible question shape
in advance. The validation layer exists specifically to make this
trade acceptable: the LLM can propose anything, but it can only
*execute* what passes a strict, deterministic set of rules.

---

## 2. Why this over fixed query functions (for now)

| | Fixed functions | LLM-generated Cypher (current choice) |
|---|---|---|
| Reliability on known question types | Very high — hand-tested | Depends on the LLM getting it right each time |
| Handles novel/unanticipated questions | No — falls outside all patterns | Yes — this is the whole point |
| Build effort up front | High — write + test ~10+ functions | Low — one generation + validation pipeline |
| Debuggability | Easy — bug is either routing or data | Harder — bug could be a subtly wrong query |
| Matches published precedent | — | Yes — this is what the LinkedIn paper does |

We're starting here because it's faster to build a working end-to-end
system, and because it directly mirrors a validated, production-proven
design. If evals later show the generated-Cypher path is unreliable
for our common question types, fixed functions can be reintroduced as
a first-choice path, with generation kept only as a fallback for novel
questions — this is a reversible decision, not a permanent one.

---

## 3. How the Cypher gets generated

### Step 1 — Entity + intent extraction (already covered in the main flow)
```
Question: "If I change src/auth.py, what could break?"
→ entities = { "file": "src/auth.py" }
→ intent   = "impact_analysis"
```

### Step 2 — Cypher generation prompt
The LLM is given, as its **only allowed vocabulary**, our locked schema
— nothing else. This constraint is what keeps generation safe-by-design,
not just safe-by-validation.

```
SYSTEM PROMPT (fixed, not per-question):

You are a Cypher query generator for a Neo4j graph database.

ALLOWED NODE LABELS (use ONLY these — do not invent others):
Repository, Commit, File, PullRequest, Developer, Team, Review,
CIRun, Deployment, Incident, Permission

ALLOWED RELATIONSHIP TYPES (use ONLY these — do not invent others):
CONTAINS, PROTECTED_BY, OWNS, CREATES, AUTHORED, PERFORMS,
BELONGS_TO, HAS_PERMISSION, MODIFIES, RECEIVES, TRIGGERS,
RELATED_TO, PARENT_OF, DEPLOYED_AS, OWNED_BY, REQUIRES_REVIEW_FROM,
TESTS, MAY_CAUSE

RULES:
- Read-only queries ONLY. Never generate CREATE, MERGE, DELETE, SET,
  REMOVE, DROP, or any write operation.
- Use only the node labels and relationship types listed above.
- Always start from the given entity's node using its exact id.
- Prefer OPTIONAL MATCH for relationships that may not exist, so the
  query doesn't fail to return partial results.
- Return the query as plain Cypher text only — no explanation, no
  markdown formatting.

ENTITY: File, id = "file-auth"
INTENT: impact_analysis

Generate the Cypher query.
```

### Step 3 — Example generated output
```cypher
MATCH (f:File {id: "file-auth"})
OPTIONAL MATCH (f)-[:OWNED_BY]->(owner)
OPTIONAL MATCH (f)-[:REQUIRES_REVIEW_FROM]->(reviewTeam)
OPTIONAL MATCH (c:Commit)-[:MODIFIES]->(f)
OPTIONAL MATCH (pr:PullRequest)-[:CONTAINS]->(c)
OPTIONAL MATCH (pr)-[:RELATED_TO]->(inc:Incident)
RETURN owner, reviewTeam, c, pr, inc
```

---

## 4. The validation layer — full rule set

Every generated query passes through these checks, in order, before
it's allowed anywhere near Neo4j. Failing any check routes straight to
the fallback (flat text search).

```
1. READ-ONLY CHECK
   Reject if the query text contains, case-insensitively:
     CREATE, MERGE, DELETE, SET, REMOVE, DROP, CALL {  (write subquery),
     or any APOC write procedure (apoc.create.*, apoc.merge.*, etc.)

2. SCHEMA WHITELIST CHECK
   Parse out every node label (":Label") and relationship type
   ("[:REL_TYPE]") referenced in the query.
   Reject if any label is not in our 11, or any relationship type
   is not in our 18.

3. SYNTAX / EXECUTABILITY CHECK
   Run the query through Neo4j's EXPLAIN first (does not execute,
   just validates the query plan). Reject if this fails.

4. RESOURCE LIMITS
   - Query timeout: e.g. 5 seconds max
   - Result size cap: e.g. reject/truncate results over some row limit
   - Optional: reject queries with unbounded variable-length paths
     (e.g. "-[*]-" with no upper bound), since these can be expensive

5. PARAMETER SAFETY
   The entity id used to start the query comes from our own
   entry-point search, not from raw user text — so there's no
   injection risk from the original question itself. The LLM only
   fills in query STRUCTURE, not raw untrusted string values.
```

If a query fails any check, it never reaches Neo4j — the system logs
the failure reason and falls back to flat text search.

---

## 5. Failure modes and what happens for each

| Failure | What happens |
|---|---|
| LLM generates a write operation | Rejected at check 1 → fallback |
| LLM references an invented label/relationship (hallucinated schema) | Rejected at check 2 → fallback |
| LLM generates syntactically broken Cypher | Rejected at check 3 → fallback |
| Query is valid but too expensive/slow | Rejected/timed out at check 4 → fallback |
| Query is valid, runs, but finds nothing | Passes validation, executes, returns empty → fallback (Trigger B in the main flow doc) |
| Query is valid and finds real results | Proceeds to evidence assembly + synthesis, as normal |

---

## 6. Why the schema constraint matters more than it looks

Giving the LLM the exact list of 11 labels and 18 relationship types isn't
just a nice-to-have prompt detail — it's the main thing keeping
generation safe *before* validation even runs. An LLM with no
constraints might invent a plausible-sounding but nonexistent
relationship like `DEPENDS_ON` or `LINKED_TO` — validation would catch
this, but constraining the vocabulary up front means far fewer queries
get rejected in the first place, which directly improves the system's
overall success rate (fewer fallbacks, better user experience).

---

## 7. What to measure in evals (this retrieval strategy specifically)

This deserves its own eval slice, separate from the general retrieval
evals already planned, since it's the highest-risk component in the
current architecture:

```
- % of generated queries that pass validation on the first try
- % of generated queries that fail EACH validation check
  (helps identify whether the LLM struggles more with schema
  adherence, write-safety, or syntax)
- % of validated queries that return correct results, compared
  against our hand-labeled ground truth (same eval set used for
  the general traversal-correctness metric)
- Fallback rate specifically attributable to Cypher generation
  failure, vs. fallback rate from failed entry-point search —
  track these as two separate numbers, not one combined rate
```

This last point matters: knowing *why* the system fell back (bad
entry point vs. bad generated query) tells you which part of the
pipeline needs more work — conflating them hides that signal.

---

## 8. Local model consideration

This is very likely the hardest task we're asking the local LLM to
do in the entire system — precise, schema-aware structured generation
is a harder skill than entity extraction or free-text synthesis. Two
practical mitigations worth building in from the start:

```
- Few-shot examples in the generation prompt: include 2-3 example
  (question → correct Cypher) pairs covering different question
  shapes, to anchor the model's output format and style
- Retry-once-on-failure: if a generated query fails validation, give
  the LLM one retry with the specific failure reason included in the
  prompt ("Your query used relationship DEPENDS_ON, which doesn't
  exist. Allowed relationships are: ...") before falling back to text
  search — this alone often meaningfully improves success rate
```

Both are cheap to add and likely to measurably reduce the fallback
rate — worth including in the first working version, not treated as
later polish.
