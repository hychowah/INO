# Concept Relations & Topic Hierarchy — Implementation Plan

> **Status:** Complete (Phases 1-9)  
> **Created:** 2026-03-17  
> **Goal:** Transform flat-topic structure into a knowledge graph with cross-concept relationships and better hierarchy.

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Relation discovery | Assess-driven + maintenance batch | No new user-facing action → avoids instruction dilution in AGENTS.md |
| User confirmation | Auto-create, user can prune | Relations are non-destructive metadata; inverted friction model |
| Edges per pair | One (UNIQUE constraint) | LLM picks dominant type; keeps schema/queries simple |
| Relation types | Controlled vocabulary (5 types) | Prevents "everything is related" drift |
| Context placement | Fetch results only (not baseline) | Zero token cost on non-quiz turns |
| Topic hierarchy in baseline | Inline subtopic names | +10 tokens/root vs +50-80 for full 2-level expansion |
| Graph UI | Deferred (Phase 8) | Ship data layer first, validate with real usage |
| `source` column | Dropped | `action_log` already tracks provenance |
| Cap per concept | 5 relations max | Enforced in SQL to force quality over quantity |

### Relation Type Vocabulary

| Type | Meaning | Example |
|------|---------|---------|
| `builds_on` | A is a prerequisite for understanding B | "Ohm's Law" → "Kirchhoff's Laws" |
| `contrasts_with` | A and B are alternatives or opposites | "TCP" ↔ "UDP" |
| `commonly_confused` | Users often mix these up | "Stack" ↔ "Heap" |
| `applied_together` | A and B are used together in practice | "PID Controller" ↔ "PWM Output" |
| `same_phenomenon` | Different aspects of the same thing | "Rust" ↔ "Oxidation" |

---

## Phase 1: DB Foundation ✅  

**Risk:** Low | **Effort:** 1-2h | **Dependencies:** None

### 1.1 Migration v9 in `db/core.py`

```sql
CREATE TABLE IF NOT EXISTS concept_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id_low INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    concept_id_high INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL CHECK(relation_type IN 
        ('builds_on','contrasts_with','commonly_confused','applied_together','same_phenomenon')),
    note TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(concept_id_low, concept_id_high),
    CHECK(concept_id_low < concept_id_high)
);
CREATE INDEX IF NOT EXISTS idx_concept_relations_low ON concept_relations(concept_id_low);
CREATE INDEX IF NOT EXISTS idx_concept_relations_high ON concept_relations(concept_id_high);
```

- `concept_id_low < concept_id_high` enforced by CHECK — normalizes undirected edges, prevents self-links
- One edge per pair via UNIQUE
- FK CASCADE ensures cleanup on concept deletion

### 1.2 Create `db/relations.py`

| Function | Description |
|----------|-------------|
| `add_relation(a, b, relation_type, note=None)` | Normalize IDs, validate, cap check (≤5 per concept), INSERT OR IGNORE. Returns new ID or None. |
| `get_relations(concept_id)` | Both directions — returns related concept's title, ID, score, relation_type, note |
| `remove_relation(a, b)` | Normalize + DELETE. Returns True/False. |
| `add_relations_from_assess(concept_id, related_ids, relation_type='builds_on')` | Batch helper. Silently skips: invalid IDs, self-ref, capped. Returns count added. |
| `search_related(concept_id, depth=2)` | Recursive CTE BFS. Returns concepts within N hops. |

### 1.3 Wire up

- Add re-exports to `db/__init__.py`
- Add `DELETE FROM concept_relations WHERE concept_id_low = ? OR concept_id_high = ?` to `delete_concept()` in `db/concepts.py` (matches existing manual-CASCADE pattern)

### 1.4 Test infrastructure

- Create `tests/conftest.py` with isolated temp-DB fixture (patches `KNOWLEDGE_DB` + `CHAT_DB`)
- Create `tests/test_relations.py`: CRUD, normalization, cap enforcement, cascade, self-rejection

---

## Phase 2: Topic Hierarchy Fixes ✅

**Risk:** Low | **Effort:** 1-2h | **Dependencies:** None (parallel with Phase 1)

### 2.1 Cycle detection in `link_topics()` (`db/topics.py`)

Before INSERT, run recursive CTE to check if `child_id` is already an ancestor of `parent_id`:
```sql
WITH RECURSIVE ancestors AS (
    SELECT parent_id AS id FROM topic_relations WHERE child_id = ?
    UNION ALL
    SELECT tr.parent_id FROM topic_relations tr JOIN ancestors a ON tr.child_id = a.id
)
SELECT 1 FROM ancestors WHERE id = ? LIMIT 1
```
If found → return False (would create cycle).

### 2.2 Add `unlink_topics(parent_id, child_id)`

Simple `DELETE FROM topic_relations WHERE parent_id=? AND child_id=?`. Returns bool.

### 2.3 Action handler

Add `_handle_unlink_topics` to `services/tools.py`, register in `ACTION_HANDLERS`.

### 2.4 Tests

Cycle detection (direct, transitive, valid link, self-link), unlink (existing, nonexistent, last parent).

---

## Phase 3: Assess-Driven Relation Creation ✅

**Risk:** Medium | **Effort:** 2-3h | **Dependencies:** Phase 1

### 3.1 Extend `_handle_assess` in `services/tools.py`

After the remark block (~line 545), add:
```python
related_ids = params.get('related_concept_ids', [])
if related_ids and isinstance(related_ids, list):
    added = db.add_relations_from_assess(cid, related_ids)
    if added:
        result_parts.append(f"Linked {added} related concept(s)")
```

All validation (existence, self-ref, cap) lives in `db.add_relations_from_assess()`.

### 3.2 Tests

- Existing assess calls without `related_concept_ids` → unchanged behavior
- With valid IDs → relations created
- With invalid/self IDs → silently skipped
- Cap respected

---

## Phase 4: Context Enrichment ✅

**Risk:** Low | **Effort:** 1-2h | **Dependencies:** Phase 1

### 4.1 Relations in fetch results (`services/context.py`)

In `format_fetch_result()`, when formatting concept detail, append:
```
## Related Concepts
- [builds_on] Concept Title (#ID, score 45/100)
- [commonly_confused] Other Concept (#ID, score 30/100)
```

~15 tokens per relation × ~3-5 relations = 45-75 additional tokens per concept fetch. Only appears during fetch, not baseline.

### 4.2 Inline subtopic names in Knowledge Map

Update `build_lightweight_context()` topic map line:
```
Before: - [topic:1] Material Science: 15 concepts, 3 subtopics, score 45/100, 2 due
After:  - [topic:1] Material Science: 15 concepts, 3 subtopics (Metals, Polymers, Ceramics), score 45/100, 2 due
```

Fetch children once per root during context build, cache per call. +10 tokens/root.

---

## Phase 5: AGENTS.md Prompt Updates ✅ DONE

**Risk:** Low | **Effort:** 30min | **Dependencies:** Phases 3-4

### 5.1 `assess` action — add `related_concept_ids` param

In the Parameters section:
> `related_concept_ids` (int[], optional): If the user's answer demonstrates understanding of or connection to other tracked concepts, list their IDs. Relationships are auto-created using the most fitting type: `builds_on`, `contrasts_with`, `commonly_confused`, `applied_together`, `same_phenomenon`.

### 5.2 `remove_relation` action reference

New action block (~5 lines):
> **Parameters:** `concept_id_a` (int), `concept_id_b` (int)

### 5.3 `unlink_topics` action reference

> **Parameters:** `parent_id` (int), `child_id` (int) — Remove a parent→child topic edge.

### 5.4 Adaptive Quiz Evolution Step 4 addition

One line: "Check the Related Concepts section in fetch results — use these connections for cross-concept synthesis questions."

### 5.5 Token budget: ~150 additional tokens (acceptable)

---

## Phase 6: Maintenance Relationship Discovery ✅ DONE

**Risk:** Medium | **Effort:** 2h | **Dependencies:** Phase 1

### 6.1 `get_relationship_candidates(limit=20)` in `db/diagnostics.py`

FTS5-based candidate generation (O(n log n), not pairwise O(n²)):
1. For each concept, extract title keywords (>3 chars)
2. Query FTS5 for matches (excluding self)
3. Filter out pairs that already have a relation
4. Return top candidates with titles

### 6.2 "Cluttered root topics" diagnostic

Root topics with >10 direct concepts not organized into subtopics.

### 6.3 Wire into maintenance

- Add to `get_maintenance_diagnostics()` return dict
- Add `relate_concepts` as a maintenance-only action in `services/tools.py`
- Register in `SAFE_MAINTENANCE_ACTIONS` (auto-execute, no user confirmation)

### 6.4 AGENTS.md maintenance section update

Add: "Relationship candidates — review proposed pairs, auto-create if pedagogically useful."

---

## ── MVP BOUNDARY ──

Ship Phases 1-6 and validate with real usage for 1-2 weeks before continuing.

---

## Phase 7: User Pruning ✅

- `_handle_remove_relation` added to `services/tools.py`
- Registered in `ACTION_HANDLERS`
- `remove_relation` documented in AGENTS.md

## Phase 8: Web UI Graph ✅

**D3.js force-directed knowledge graph at `/graph` in the web UI.**

### Implemented
- `("graph", "Graph")` nav item in `webui/server.py` layout
- `page_graph()` function — assembles same data shape as `/api/graph`, injects via `window.__GRAPH_DATA`
- `webui/static/graph.js` — D3 v7 force-directed visualization with data/render layer separation
- Full-bleed layout (`body_class` param on `layout()`, CSS override for `.graph-page`)
- D3 v7 loaded from CDN

### Graph features
- **Concept nodes**: uniform circles, 4-bucket discrete mastery colors (struggling/building/solid/mastered) with opacity variation for colorblind safety
- **Topic nodes**: larger circles, accent blue, with labels
- **Edges**: muted gray by default; relation type colors revealed on node hover/click
- **Relation types**: 5 colors — builds_on (green), contrasts_with (orange), commonly_confused (red), applied_together (blue), same_phenomenon (purple)
- **Concept→topic membership edges**: dashed, light gray
- **Click**: navigates to `/concept/{id}` or `/topic/{id}`
- **Hover tooltips**: title, mastery bar, due date, interval, review count, topics, description snippet
- **Zoom/pan**: D3 zoom with auto-fit on load
- **Node drag**: force simulation reheats on drag
- **Search**: debounced (200ms), dims non-matches to 0.15 opacity, accent glow on matches
- **Topic filter**: dropdown to show only concepts under a specific topic
- **Mastery filter**: btn-group (All/Struggling/Building/Solid/Mastered)
- **Layout toggle**: "Free Layout" (force-directed) / "Group by Topic" (cluster by topic positions)
- **Legend**: collapsible overlay (ⓘ button), shows mastery buckets + relation type colors
- **Edge states**: <5 nodes shows "getting started" notice; no relations hides relation layer
- **Mobile**: `<700px` hides graph, shows fallback message with links to Topics/Concepts pages
- **`MAX_GRAPH_NODES` cap**: configurable via `config.py` / env var, top N by mastery with banner notice

### API enrichments
- `get_all_concepts_summary()` — added `topic_ids` (int[]), `next_review_at`, `interval_days`; optional `limit`/`offset` params
- `get_concept_topic_edges()` — new function returning concept→topic membership edges
- `GET /api/graph` — added `concept_topic_edges`, `total_concepts` to response; added `topic_id`, `min_mastery`, `max_mastery`, `max_nodes` query params for server-side filtering

## Phase 9: Scalability ✅

- `MAX_GRAPH_NODES = 500` config constant with env var override
- `get_all_concepts_summary()` accepts optional `limit`/`offset` params
- `get_due_concepts()` accepts `offset` param (backward compatible)
- `get_due_count()` helper for efficient COUNT query
- Dynamic due-concept header in LLM context: shows "(top 5 of N)" when total > 5
- `/api/graph` server-side filtering: `?topic_id=&min_mastery=&max_mastery=&max_nodes=`
- Client-side: auto-switch to cluster layout for large graphs, concept labels hidden at 30+ nodes

---

## Verification Checklist

- [ ] Unit tests pass for all phases (isolated DB fixture)
- [ ] Migration test: v8 DB → v9 migration preserves existing data
- [ ] Integration: assess with `related_concept_ids` → relation in DB → fetch shows "Related Concepts"
- [ ] Regression: existing test suite passes after each phase
- [ ] Token budget: measure context size with 10/20/30 root topics — confirm inline subtopic names stay within budget
- [ ] Manual test: quiz flow with relationship context → LLM uses relations for synthesis questions
