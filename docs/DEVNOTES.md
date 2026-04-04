# DEVNOTES.md — learning_agent

> **Purpose:** Key findings and non-obvious patterns. Keep ≤400 lines — prune stale entries.
>
> **Audience:** Developers / Copilot during code-editing sessions only.
> The runtime LLM does NOT read this file — its instructions are in `data/skills/*.md`.
>
> **When to update:** After fixing a non-trivial bug or making an architectural decision
> that isn't obvious from the code — add a short entry here.

---

## Table of Contents
1. [LLM Output Formatting](#1-llm-output-formatting)
2. [Architecture Decisions](#2-architecture-decisions)
3. [Score-Based Review System](#3-score-based-review-system)
4. [Confirmation Flows & Proposals](#4-confirmation-flows--proposals)
5. [ID Confusion & Session Stash Pattern](#5-id-confusion--session-stash-pattern)
6. [Maintenance Score Guard](#6-maintenance-score-guard)
7. [Pending Review Tracking](#7-pending-review-tracking)
8. [Discord Formatting](#8-discord-formatting)
9. [JSON Parser](#9-json-parser)
10. [Phantom-Add Prevention](#10-phantom-add-prevention)
11. [Modular Skill Loading](#11-modular-skill-loading)
12. [Hybrid Vector Search & Multi-Quiz](#12-hybrid-vector-search--multi-quiz)
13. [Topic Hierarchy Auto-Parenting](#13-topic-hierarchy-auto-parenting)
14. [Two-Prompt Scheduled Quiz Pipeline](#14-two-prompt-scheduled-quiz-pipeline-migration-11)
15. [Quiz Intent Detection & Context Lifecycle](#15-quiz-intent-detection--context-lifecycle)
16. [Quiz Anchor Concept ID](#16-quiz-anchor-concept-id)
17. [Context Enrichment & Qdrant Migration](#17-context-enrichment--qdrant-migration)

---

## 1. LLM Output Formatting

**Key lesson:** Every action the LLM can emit MUST have a concrete JSON example in the skill files. Parameter lists alone are not enough — the LLM hallucinated wrong structures (flat params, wrong field names) until given `<!-- DO NOT REMOVE -->` annotated JSON templates.

**Escalation hierarchy for LLM output errors:**
1. Flat-params recovery (`pipeline.py execute_action`) — code, instant, structural fix only
2. Repair sub-agent (`services/repair.py`) — ephemeral LLM session, ~5-10s, fixes action names
3. Error to user — if repair also fails

**Flat-params recovery:** When `params` is empty but extra keys exist at top level, `execute_action()` recovers them into `params`. Logs a warning. Doesn't fix missing/wrong field names.

---

## 2. Architecture Decisions

### 2.1 Prompt-first fixes over defensive code
When the LLM emits malformed actions, prefer fixing the prompt over adding defensive parsing code. Defensive code masks prompt bugs. Only add code fallbacks if the same bug recurs after two prompt fix attempts.

### 2.2 Repair sub-agent
When `execute_action()` gets an "Unknown action" error, it calls `repair_action()` (a lightweight LLM session) to fix the malformed JSON. Session rotates every 15 minutes to cap context growth. The seeding prompt teaches valid action names (~300 chars); subsequent calls only send the malformed JSON (~100 chars).

### 2.3 Session reuse across conversation
`_get_conv_session()` manages a conversation-level session that persists across `call_with_fetch_loop()` invocations. New session on idle timeout (config `SESSION_TIMEOUT_MINUTES`). Within a fetch loop, iteration 0 sends full prompt; iterations 1+ use lightweight followup (~500 chars vs ~4500 chars).

---

## 3. Score-Based Review System

**Replaced SM-2 with asymmetric score system (0–100):**
- `question_difficulty` (0–100): LLM reports how hard its question was
- `gap = question_difficulty − current_score`
- **Correct:** score increases (bigger gain for harder questions)
- **Wrong + gap > 0:** NO decrease (probe above user's level)
- **Wrong + gap ≤ 0:** proportional decrease (actual regression)

**Score → interval:** `interval_days = max(1, round(e^(score × 0.05)))`

| Score | Interval | Score | Interval |
|-------|----------|-------|----------|
| 0 | 1 day | 50 | 12 days |
| 25 | 3 days | 75 | 43 days |

**Score delta constants:**
```
CORRECT — base: q3=2, q4=4, q5=7.  above: base + gap×0.15.  at/below: max(1, base×0.5)
WRONG   — base: q0=5, q1=3, q2=1.  above: 0 (no penalty).   at/below: base + |gap|×0.2
```

**`ease_factor` is frozen** — column remains in DB but is not used. Cleanup deferred.

**`question_difficulty` fallback** when LLM omits it: q≥4 → `score+10`, q=3 → `score`, q≤2 → `score+15`.

---

## 4. Confirmation Flows & Proposals

Destructive actions (dedup merges, maintenance `delete_concept`/`unlink_concept`/`update_concept`) are now **proposals** stored in `pending_proposals` DB table. Users approve/reject via Discord buttons (`DedupConfirmView`, `MaintenanceConfirmView` in `services/views.py`).

**Key decisions:**
- Discord buttons over text replies — text goes to LLM pipeline, buttons are unambiguous
- DB-backed proposals survive bot restarts (exit code 42 mechanism)
- 24h auto-expiry on both View timeout and DB rows
- Safe maintenance actions (`link_concept`, `delete_topic` for empty topics, `remark`, `fetch`, `list_topics`) execute immediately; destructive ones become proposals
- Dedup prompt tightened: only merge concepts that are the **same thing with different wording**

---

## 5. ID Confusion & Session Stash Pattern

**Bug:** After `add_concept` confirmation, LLM used topic ID instead of concept ID (both were bare `[N]` format).

**Fix:** Three layers:
1. **Session stash** in `_handle_add_concept`: `db.set_session('last_added_concept_id', str(id))` — same pattern as `last_assess_concept_id`
2. **Chat history persistence** after button confirm: save `[confirmed: add concept]` + result to chat history so LLM sees the ID
3. **Type-prefixed IDs** everywhere: `[topic:N]` / `[concept:N]` — makes confusion structurally impossible

**Lesson:** When an action creates an entity whose ID is needed by a future turn, stash the ID in session state at creation time. Don't parse formatted result strings. Follow the existing stash pattern.

**Why NOT `active_concept_id`?** That key powers "Active Quiz Context" — setting it after creation (not quiz) would mislead the LLM into phantom assessments. Note: `active_concept_id` is now auto-cleared after `QUIZ_STALENESS_TIMEOUT_MINUTES` of inactivity, and also cleared when the LLM executes any action in `_QUIZ_CLEARING_ACTIONS` (see §15).

---

## 6. Maintenance Score Guard

**Bug:** Maintenance LLM raised concept scores from 18→55 via `update_concept`, ignoring prompt instructions.

**Fix (defense-in-depth):**
1. **Code guard** in `_handle_update_concept` (tools.py): when `action_source='maintenance'`, strip `mastery_level`, `ease_factor`, `interval_days`, `next_review_at`, `last_reviewed_at`, `review_count`
2. **Action source** set in `execute_maintenance_actions` (pipeline.py) so approved proposals also get the guard
3. **Reduced temptation**: struggling concepts diagnostic hides raw scores, shows `(7 reviews, still building)` instead
4. **Prompt prohibition** in `maintenance.md`: "NEVER modify score/scheduling fields"

**Lesson:** When the LLM has both data and tool to modify it, prompt instructions alone are insufficient — add a code-level guard.

---

## 7. Pending Review Tracking

**Bug:** Scheduler sent multiple unanswered review DMs in sequence. LLM hallucinated phantom answers from chat history pollution (`[SCHEDULED_REVIEW]` saved as `role='user'`).

**Fix:**
- **DB-backed pending state** (`pending_review` session key): JSON blob with `{concept_id, concept_title, question, sent_at, reminder_count}`
- **Chat history sanitized**: `[SCHEDULED_REVIEW]` → `[system: review quiz sent for concept #N — awaiting response]`
- **Pending cleared on assess only** (tools_assess.py `_handle_assess`) — casual messages don't clear it
- **Static reminders** (no LLM call) with `REVIEW_REMINDER_MAX` (default 3) before moving on
- Set pending AFTER `user.send()` succeeds — avoids race condition

---

## 8. Discord Formatting

**Discord 2000-char overflow:** `formatting.py` provides `truncate_for_discord()` and `truncate_with_suffix()`. Convention: `config.MAX_MESSAGE_LENGTH=1900` for initial sends, `formatting.DISCORD_CHAR_LIMIT=2000` for edits/appends.

**View truncation:** `send_long_with_view()` splits text at newline boundaries, sends all chunks except last as plain messages, attaches view to final chunk. Replaced 5 silent `[:1900]` truncation sites in `bot.py`.

**Signal handler crash:** `webui/server.py` signal handler must guard with `threading.current_thread() is threading.main_thread()` since bot.py spawns webui in a background thread.

**SVG/D3:** Set visual properties as inline SVG `.attr()` calls, not CSS classes — avoids specificity issues. CSS only for interactive states.

---

## 9. JSON Parser

**Bug:** Brace-counting JSON extraction broke on code in string values (C++, LaTeX `\frac{a}{b}`, regex `{3,5}`).

**Fix:** Try-each-`}` with last-valid-parse in `_extract_json_object()` and `_extract_json_str()`. Tries `json.loads()` at every `}` position, keeps the **last** successful parse (largest valid JSON). Uses `json.loads()` as the validator instead of a brace-counting state machine.

Why "last valid" not "first valid": partial JSON may parse but miss trailing fields like `"message"`.

Safety net in `process_output()`: if output has no recognized prefix but contains `"action"`, tries extraction and returns the `message` field.

---

## 10. Phantom-Add Prevention

**Bug:** LLM output `REPLY:` claiming "Added concept X" with no JSON action — nothing saved to DB.

**Fix:**
1. **Anti-phantom-add rule** (skill `core.md`, rule 12): "NEVER claim you created a concept/topic in REPLY. Creating requires a JSON action."
2. **Button-based `suggest_topic`** flow: single-turn (LLM suggests → buttons → callback creates). LLM does NOT handle Turn 2.
3. **`SuggestTopicConfirmView`** + shared `execute_suggest_topic_accept()` — DRY between button and text-reply paths
4. **Unified `_pending_confirmations`** dict in bot.py — handles both `add_concept` and `suggest_topic`
5. **Silent detection** (pipeline.py): regex logs warning when REPLY contains "Added/Created" without action. Log-only.

---

## 11. Modular Skill Loading

Split monolithic `AGENTS.md` (~690 lines) into `data/skills/` (4 files, conditional per mode):

```
interactive (COMMAND/REPLY) → core + quiz + knowledge
review (REVIEW-CHECK)       → core + quiz
maintenance (MAINTENANCE)   → core + maintenance + knowledge
```

`pipeline.py`: `SKILL_SETS` dict → `_mode_to_skill_set()` → `_get_base_prompt(skill_set)` with per-file mtime hot-reload. Cache keyed on `(persona, skill_set)`.

**`AGENTS.md` is a pointer file** (~25 lines) — coding-agent entry point, not read by runtime LLM.

**Session isolation:** Maintenance and review-check modes create dedicated sessions. Interactive modes share `_get_conv_session()` with 5-min idle timeout.

---

## 12. Hybrid Vector Search & Multi-Quiz

**What was added:** Qdrant embedded vector store + sentence-transformers alongside SQLite. Not classical RAG — no LLM prompt stuffing. Vector similarity is used for search, dedup, relation candidates, and multi-concept quiz clustering.

**Key design decisions:**
- **Best-effort, non-fatal:** every vector call is wrapped in `try/except`. If `qdrant-client` or the model is absent, FTS5/LIKE fallback activates silently. `db.VECTORS_AVAILABLE` flag for runtime detection.
- **Lazy model load:** `services/embeddings.py` loads `all-mpnet-base-v2` on first call (~100–200ms on CPU, ~420MB download once). Tests inject a mock instead.
- **No SQLite schema changes:** Qdrant stores its own files in `data/vectors/`. Existing `knowledge.db` is untouched.
- **Sync hooks, not triggers:** `_vector_upsert()` / `_vector_delete()` are called at the end of each CRUD function in `db/concepts.py` + `db/topics.py`. SQL always writes first.
- **Fetch dispatch order bug fixed:** `_handle_fetch()` originally checked `concept_id` before `cluster` — cluster calls never reached `_handle_fetch_cluster()`. Cluster check moved first.

**Threshold tuning:** Use `python scripts/test_similarity.py` to measure real cosine scores before changing `SIMILARITY_THRESHOLD_DEDUP` (0.92) or `SIMILARITY_THRESHOLD_RELATION` (0.5). Technical sub-concepts (e.g. 304 vs 316 stainless) typically score 0.88–0.94 — well below the dedup threshold when descriptions are distinct.

**Multi-quiz session state:**
- `multi_quiz` → stores `active_concept_ids` (JSON) in session
- `multi_assess` → scores each concept independently, then clears `active_concept_ids` + `active_concept_id`
- `context.py` reads `active_concept_ids` first; falls back to single `active_concept_id`

**Migration:** First deploy with existing data requires `python scripts/migrate_vectors.py` once. New writes auto-sync.

---

## 13. Topic Hierarchy Auto-Parenting

**Problem:** New topics from `suggest_topic` and auto-created topics from `add_concept` with `topic_titles` appeared as standalone root topics even when an obvious parent existed (e.g. "Python AST" should be under "Python").

**Fix (three layers):**
1. **Prompt rules** (knowledge.md): "Always check the Knowledge Map first" — LLM must set `parent_ids` on `add_topic` and `suggest_topic` when a parent exists. Both action specs include examples showing `parent_ids` usage.
2. **`execute_suggest_topic_accept()`** (tools_assess.py): Passes `parent_ids` from `action_data['params']` through to `execute_action('add_topic', ...)`. The data survives the confirm round-trip via `action_data` dict in `_pending_confirmations` / `SuggestTopicConfirmView` — no session stash needed.
3. **`_find_candidate_parents()`** (tools.py): When `_resolve_topic_ids` auto-creates a topic from `topic_titles`, uses `db.search_similar_topics()` to find parents before creation.

**Auto-parent heuristics** (`_find_candidate_parents`):
- Pre-filters candidates at similarity ≥ 0.50 (broad net via `search_similar_topics`)
- Accepts as parent if: candidate title is a substring of the new title (e.g. "Python" in "Python AST")
- For non-substring matches: requires similarity ≥ 0.65 AND candidate title must be shorter (broader scope) — avoids suggesting a more-specific topic as parent
- Skips exact title matches (self-hit)
- Wrapped in try/except — vector store unavailable → no auto-parenting, non-fatal

**Self-link guard** (db/topics.py `add_topic`): `if pid == topic_id: continue` prevents a topic from being its own parent when `parent_ids` inadvertently contains the new ID.

**Maintenance support:** `link_topics` added to `SAFE_MAINTENANCE_ACTIONS` so the maintenance agent can auto-fix orphan subtopics and reparent topics without requiring user approval (non-destructive, reversible via `unlink_topics`).

---

## 14. Two-Prompt Scheduled Quiz Pipeline (Migration 11)

**Problem:** Single-prompt quiz generation gave the LLM too many competing responsibilities: analyze concept data, pick the right question type/difficulty, AND format output with persona voice.

**Fix:** Split into two prompts:
- **P1 (Reasoning model):** Stateless question generation. Uses `data/skills/quiz_generator.md` as system prompt. Receives concept detail + related concepts, outputs structured JSON (`question`, `difficulty`, `question_type`, `target_facet`, `reasoning`, `concept_ids`). Uses `REASONING_LLM_*` provider if configured, otherwise falls back to main provider.
- **P2 (Fast model):** Packages P1 output with persona voice for Discord. Uses skill set `"quiz-packaging"` (core + quiz). Receives P1 JSON, outputs standard `quiz` action.

**Fallback:** If P1 fails (timeout, parse error, provider unavailable), scheduler falls back to single-prompt `call_with_fetch_loop()` — same behavior as before the change.

**Migration 11:** Added `last_quiz_generator_output TEXT` column on `concepts` table. Stores raw P1 JSON output for debugging/inspection. Displayed in webui concept detail page. Non-functional — purely for transparency.

**Key files:** `services/pipeline.py` (`generate_quiz_question`, `package_quiz_for_discord`), `services/scheduler.py` (`_send_review_quiz`), `services/llm.py` (`get_reasoning_provider`), `services/context.py` (`build_quiz_generator_context`), `config.py` (REASONING_LLM_* vars).

---

## 15. Quiz Intent Detection & Context Lifecycle

**Bug:** When a quiz was active and the user sent an unrelated question (e.g. "async vs thread" during an embeddings quiz), the LLM treated it as a quiz answer and assessed it. Three root causes: (1) no criteria in instructions for distinguishing quiz answers from new questions, (2) `active_concept_id` only cleared after `assess`, persisting indefinitely, (3) chat history duplicated in OpenAI-compat provider.

**Fix (defense-in-depth, 3 layers):**

1. **LLM instructions** (`core.md` MODE: REPLY → "Intent Detection During Active Quiz"): signal lists for quiz-answer vs new-question, decision rule ("if not answering quiz → REPLY: instead of assess"), worked examples. `quiz.md` assess docs reinforced with same rule.
2. **Backend clearing** (`pipeline.py` `_QUIZ_CLEARING_ACTIONS`): quiz context clears after `assess`, `multi_assess`, `add_concept`, `suggest_topic`, `add_topic`, `remark`. NOT after `fetch`, `quiz`, `multi_quiz`, or plain REPLY:. Also clears `active_concept_ids` for multi-quiz.
3. **Staleness timeout** (`context.py` `_append_active_quiz_context()`): checks `session_state.updated_at` via `db.get_session_updated_at()`. If elapsed > `QUIZ_STALENESS_TIMEOUT_MINUTES` (config, default 15 min), auto-clears and skips injection. Excludes REVIEW-CHECK mode (returns early before reaching this code).
4. **Chat history dedup** (`context.py` `_append_chat_history()`): for session-based providers (OpenAI-compat), skips the entire "Recent Conversation" section on continuation turns (`is_new_session=False`). The provider already accumulates full history in its `_sessions` dict — injecting truncated chat history caused the LLM to see the same messages twice with slightly different content (old ones from context, newer ones from provider memory). New sessions and stateless providers always get history. Parameter `is_new_session` is threaded from `_get_conv_session()` through `call_with_fetch_loop()` → `_call_llm()` → `build_prompt_context()`.

**Context injection text** (`_append_active_quiz_context()`): reworded to "Use this concept_id for assess ONLY if the user's message actually answers the quiz question."

**Key files:** `data/skills/core.md` (intent detection rules), `data/skills/quiz.md` (assess guard), `services/context.py` (staleness + dedup), `services/pipeline.py` (`_QUIZ_CLEARING_ACTIONS`), `config.py` (`QUIZ_STALENESS_TIMEOUT_MINUTES`), `db/chat.py` (`get_session_updated_at`).

---

## 16. Quiz Anchor Concept ID

**Bug:** During an active quiz, the LLM sometimes fetched a related concept for comparison (e.g. user answered about "Decorator pattern" mentioning lambdas, LLM fetched "Lambda Captures"). The fetch loop in `pipeline.py` unconditionally overwrote `active_concept_id` with the fetched concept's ID, causing the subsequent `assess` action to evaluate against the wrong concept. The §15 intent-detection fix handled *new questions* vs *quiz answers*, but this bug occurs when the user IS answering the quiz — just confusingly.

**Root cause (3 layers):**
1. **Fetch loop overwrite** (`pipeline.py`): `active_concept_id` was updated on every fetch, even during active quiz processing.
2. **No quiz-specific anchor**: `active_concept_id` served double duty — both "concept being discussed" and "concept being quizzed" — with no way to distinguish enrichment fetches from topic pivots.
3. **LLM prompt ambiguity** (`quiz.md`): assess docs said "use that ID unless the conversation has moved to a different topic," which the LLM misinterpreted when it fetched a comparison concept.

**Fix — `quiz_anchor_concept_id` lifecycle key:**

- **Set** by `_handle_quiz()` in `tools_assess.py` and by both `_send_review_reminder()` / `_send_review_quiz()` in `scheduler.py` whenever a quiz starts. Stored alongside `active_concept_id`.
- **Protected** in `pipeline.py` fetch loop: when `quiz_anchor_concept_id` or `active_concept_ids` is set, the fetch loop does NOT update `active_concept_id` at all, preventing the quizzed concept from being displaced by enrichment fetches.
- **Fallback chain** in `_handle_assess()` in `tools_assess.py`: when the LLM-provided `concept_id` is not found in DB, recovers via `quiz_anchor_concept_id` (Fallback 1), then `active_concept_id` (Fallback 2), then chat history regex (Fallback 3). Ensures the assessment reaches the correct concept even if the LLM provided a stale or invalid ID.
- **Injected** by `_append_active_quiz_context()` in `context.py`: anchor takes priority over `active_concept_id` for the context block the LLM sees.
- **Cleared** in `pipeline.py` alongside other quiz state by `_QUIZ_CLEARING_ACTIONS` (`assess`, `multi_assess`, `add_concept`, `suggest_topic`, `add_topic`, `remark`). Also cleared by staleness timeout in `context.py`.
- **Not used** by multi-quiz flows (those use separate `active_concept_ids` key).

**Prompt hardening:**
- `quiz.md`: assess docs changed to "Always use the concept_id from the 'Active Quiz Context' section" — removes ambiguous "unless conversation moved" language.
- `core.md`: added "Confused answer rule" under Intent Detection — confused answers that touch related concepts still count as quiz answers; assess or clarify, don't pivot.

**Key files:** `services/tools_assess.py` (`_handle_quiz`, `_handle_assess`), `services/pipeline.py` (fetch loop guard, `_QUIZ_CLEARING_ACTIONS`), `services/context.py` (`_append_active_quiz_context`), `services/scheduler.py` (`_send_review_reminder`, `_send_review_quiz`), `data/skills/quiz.md`, `data/skills/core.md`, `tests/test_quiz_anchor.py`.

---

## Historical (completed — reference only)

**§H1 — Codebase Restructuring (2026-03-13):** Split `db.py` (1396 lines) → `db/` package (6 submodules). Split `pipeline.py` (750 lines) → `pipeline.py` + `parser.py` + `repair.py` + `dedup.py`. Fixed scheduler↔bot circular dependency via `services/state.py`. Backward compat maintained via re-exports.

**§H2 — FastAPI Backend & Project Restructuring (2026-03-15):** Created `api.py` as thin FastAPI wrapper using same pipeline. Moved `context.py`, `tools.py` → `services/`. Moved docs → `docs/`. Moved scripts → `scripts/`. Set up standalone git repo with `.env`-based config.

**§H3 — Module Extraction Refactor (2026-03-28):** Split oversized files into focused submodules: `db/core.py` (740→232) → extracted `db/migrations.py` (~265 lines, all migration blocks). `webui/server.py` (1090→198) → extracted `webui/helpers.py` (~145, HTML helpers) + `webui/pages.py` (~890, page renderers). `services/tools.py` (960→552) → extracted `services/tools_assess.py` (~360, quiz/assess action handlers). Child modules use `import db.core as _core` for dynamic DB path access (required by test fixtures that patch `db.core.KNOWLEDGE_DB`). Parent modules re-import from children after all local definitions to avoid circular imports.

---

## 17. Context Enrichment & Qdrant Migration

**Problem:** Concept relationships (stored in `concept_relations` table since migration 9) were invisible to the LLM at runtime. Due concepts, quiz context, and the P1 quiz generator received no relation data. Additionally, the Qdrant client library upgrade (1.17.x) removed `client.search()` in favor of `client.query_points()`.

**Fix — 7-step context enrichment (2026-03-25):**

1. **Chat history dedup** (see §15 point 4 update): session-based providers skip entire chat history section on continuation turns.
2. **Due concept relation lines**: `build_lightweight_context()` now calls `db.get_relations(c['id'])` per due concept, appending top 2 relation lines formatted as `↳ relation_type #id title (score, "note")`.
3. **Skill file updates**: `knowledge.md` instructs LLM to check `↳` relation lines and note connections for future `assess` calls (via `related_concept_ids`). `quiz.md` instructs use of `commonly_confused`/`contrasts_with` for distinction-testing. `quiz_generator.md` added anti-hallucination guard.
4. **Quiz context relations**: `_append_active_quiz_context()` refactored to use shared `_is_quiz_stale()` and `_format_relations_snippet()` helpers. Both single and multi-quiz paths include relation lines.
5. **Active concept auto-include**: New `_append_active_concept_detail(parts)` inserts full concept detail (description, score, remark, recent reviews, relations) when `active_concept_id` is set and not stale. Eliminates a fetch round-trip.
6. **Concept name pre-fetch**: New `_preload_mentioned_concept(user_message)` does exact case-insensitive title match. Guarded by: max 200 chars, topic relevance filter (skips if matched concept is in a different topic than the active concept). DB uniqueness enforced by case-insensitive UNIQUE index (migration 8).
7. **Quiz generator enrichment**: `build_quiz_generator_context()` now includes related concept descriptions (300 chars), remark summaries (200 chars), and last 2 review Q&As (100 chars each) per related concept.

**Shared helpers:**
- `_is_quiz_stale()`: checks `get_session_updated_at('active_concept_id')` against `QUIZ_STALENESS_TIMEOUT_MINUTES`
- `_format_relations_snippet(concept_id, max_rels)`: reusable relation formatter used in steps 2, 4, 5, 6, and 7

**Qdrant API migration:** `client.search()` removed in qdrant-client 1.17.x. Migrated 3 call sites in `db/vectors.py` to `client.query_points()`: `query_vector` parameter renamed to `query`, results accessed via `.points` property. Test fake embeddings changed from SHA-256 hash (which produced uncorrelated vectors) to bag-of-words (word → stable dimension via `hash(word) % 768`), producing meaningful cosine similarity for overlapping text.

**Key files:** `services/context.py` (all enrichment), `services/pipeline.py` (`is_new_session` threading), `db/vectors.py` (Qdrant migration), `data/skills/{knowledge,quiz,quiz_generator}.md` (instructions), `tests/test_context_enrichment.py` (30 tests), `tests/test_vectors.py` (embedding fix).

---

## 18. Quiz Skip ("I know this") Button

**Problem:** Users who already know a concept's answer shouldn't be forced to type it out. A "skip" mechanism awards full credit and moves on, but must not be gameable on first encounters.

**Design — button-only, not an LLM action:**

The skip is handled entirely in Discord UI (`QuizQuestionView` / `_QuizSkipButton`), calling `tools.skip_quiz()` directly. It is **not** registered in `ACTION_HANDLERS` because the LLM should never autonomously skip a quiz — only the user presses the button.

**Scoring:** Uses the same quality=5 algorithm as a normal perfect answer. A synthetic `question_difficulty = min(100, current_score + 10)` is used since no actual question was assessed. This gives `base_gain=7` plus a gap-proportional bonus (`gap * 0.15`), typically ~8.5 points — identical to what a real quality-5 assessment would yield.

**Anti-gaming guard:** The skip button only appears when `review_count >= 2` for the concept. First-time and once-reviewed concepts must be answered properly. Enforced in both `_send_quiz_response` (button visibility) and `skip_quiz()` (server-side check).

**Race condition prevention:** `quiz_answered` session flag prevents double-scoring. Set by `skip_quiz()` on use. Reset to `None` at the start of every `_handle_user_message` call. The Discord button's `clicked` flag also prevents duplicate button presses.

**4-tuple return signature:** `_handle_user_message` was changed from 3-tuple `(response, pending_action, assess_meta)` to 4-tuple `(response, pending_action, assess_meta, quiz_meta)`. The new `quiz_meta = {concept_id, show_skip}` tells callers whether to attach a `QuizQuestionView`. `learn_command` and `on_message` used it correctly for initial quiz delivery. A later regression left `Quiz again` and `Next due` discarding `quiz_meta` and relying on session state; this was fixed by passing `quiz_meta` through `_send_quiz_response()`. `Explain` remains plain-text by design.

**Synthetic remark & LLM continuity:** `skip_quiz()` writes a synthetic remark (`"[Skipped — user indicated prior knowledge]"`) to preserve the LLM's strategy context. `quiz.md` instructs the LLM to probe skipped concepts more rigorously on next encounter.

**Session cleanup:** `skip_quiz()` clears `last_quiz_question`, `last_assess_concept_id`, `last_assess_quality`, and `pending_review` to prevent stale state from interfering with subsequent interactions.

**Delivery-path parity fix:** The manual `/review` command already attached `QuizQuestionView` when `review_count >= 2`, but scheduler-triggered review DMs originally sent plain text only. Both manual and scheduler review-question delivery now route through `bot.messages.send_review_question()`, so timer-triggered quizzes and manual reviews attach the skip button with the same eligibility rule and message-splitting behavior.

**Key files:** `services/tools_assess.py` (`skip_quiz()`), `services/views.py` (`QuizQuestionView`, `_QuizSkipButton`), `bot/handler.py` (4-tuple return), `bot/commands.py` & `bot/events.py` (4-tuple handling, `QuizQuestionView` attachment), `data/skills/quiz.md` (LLM skip guidance).