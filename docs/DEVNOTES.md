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
18. [Quiz Skip ("I know this") Button](#18-quiz-skip-i-know-this-button)
19. [SQLite Timestamp Timezone Trap](#19-sqlite-timestamp-timezone-trap)
20. [Taxonomy Shadow Rebuild](#20-taxonomy-shadow-rebuild)
21. [Preference-Edit Isolated Skill Path](#21-preference-edit-isolated-skill-path)
22. [Multi-User DB Groundwork](#22-multi-user-db-groundwork)
23. [Process-Local Lock Hardening](#23-process-local-lock-hardening)

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

**Score → interval:** `interval_days = max(1, round(e^(score × SR_INTERVAL_EXPONENT)))` where `SR_INTERVAL_EXPONENT` defaults to `0.075` (env var `LEARN_SR_INTERVAL_EXPONENT`, set in `config.py`)

| Score | Interval | Score | Interval |
|-------|----------|-------|----------|
| 0 | 1 day | 50 | 43 days |
| 25 | 7 days | 75 | 277 days |

**Score delta constants:**
```
CORRECT — base: q3=2, q4=4, q5=7.  above: base + gap×0.15.  at/below: max(1, base×0.5)
WRONG   — base: q0=5, q1=3, q2=1.  above: 0 (no penalty).   at/below: base + |gap|×0.2
```

**`ease_factor` is frozen** — column remains in DB but is not used. Cleanup deferred.

**`question_difficulty` fallback** when LLM omits it: q≥4 → `score+10`, q=3 → `score`, q≤2 → `score+15`.

---

## 4. Confirmation Flows & Proposals

Destructive actions (dedup merges, maintenance `delete_concept`/`unlink_concept`/`update_concept`) are now **proposals** stored in `pending_proposals` DB table. Users approve/reject via Discord buttons (`DedupConfirmView`, `ProposedActionsView` in `services/views.py`).

**Key decisions:**
- Discord buttons over text replies — text goes to LLM pipeline, buttons are unambiguous
- DB-backed proposals survive bot restarts (exit code 42 mechanism)
- 24h auto-expiry on both View timeout and DB rows
- Safe maintenance actions (`link_concept`, `delete_topic` for empty topics, `remark`, `fetch`, `list_topics`) execute immediately; destructive ones become proposals
- Dedup prompt tightened: only merge concepts that are the **same thing with different wording**
- **`_CONFIRMABLE_ACTIONS` whitelist** (`api/routes/chat.py`): `/api/chat/confirm` now validates the incoming action type against `{'add_concept', 'suggest_topic', 'add_topic', 'link_concept'}`. Any other action type returns HTTP 400. Prevents confirmation of arbitrary or malformed action types that should never reach this endpoint.

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

**Discord 2000-char overflow:** `formatting.py` provides `truncate_for_discord()`, `truncate_with_suffix()`, and `format_quiz_metadata()`. Convention: `config.MAX_MESSAGE_LENGTH=1900` for initial sends, `formatting.DISCORD_CHAR_LIMIT=2000` for edits/appends.

**View truncation:** `send_long_with_view()` splits text at newline boundaries, sends all chunks except last as plain messages, attaches view to final chunk. Replaced 5 silent `[:1900]` truncation sites in `bot.py`.

**`view=None` rejection:** Discord raises `TypeError` when `view=None` is passed explicitly as a keyword argument to `send_fn`. `send_long_with_view()` omits the `view=` kwarg entirely when `view` is `None` — calls `await send_fn(chunks[-1])` without it rather than `await send_fn(chunks[-1], view=None)`.

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

Split monolithic `AGENTS.md` (~690 lines) into `data/skills/` (mode-specific files with conditional loading):

```
interactive (COMMAND/REPLY) → core + quiz + knowledge
review (REVIEW-CHECK)       → core + quiz
maintenance (MAINTENANCE)   → core + maintenance + knowledge
quiz-packaging              → core + quiz
taxonomy (TAXONOMY-MODE)    → taxonomy
```

`pipeline.py`: `SKILL_SETS` dict → `_mode_to_skill_set()` → `_get_base_prompt(skill_set)` with per-file mtime hot-reload. Cache keyed on `(persona, skill_set)`.

**`AGENTS.md` is a pointer file** (~25 lines) — coding-agent entry point, not read by runtime LLM.

**Session isolation:** Maintenance and review-check modes create dedicated sessions. Interactive modes share `_get_conv_session()` with 5-min idle timeout. Taxonomy-mode now also uses an isolated session, and the taxonomy action loop reuses one stable session across all iterations so operator-triggered rebuild passes do not contaminate the interactive session.

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

**`is_quiz_active()` — single source of truth for quiz state** (`pipeline.py`, lines ~235-248):
Returns `True` if either of the two quiz session keys is set:
- `quiz_anchor_concept_id` — set for a single-concept quiz (see §16)
- `active_concept_ids` — set for multi-quiz flows (see §12)

**Assess/multi_assess guard in `execute_action`** (`pipeline.py` and `scripts/agent.py`):
Before dispatching `assess` or `multi_assess`, `execute_action` calls `is_quiz_active()`. If no quiz is active, it short-circuits with `REPLY: <message>` instead of invoking the handler — preventing score mutations and log entries when the LLM fires an assess outside of a real quiz session. This is a hard code-level guard; it complements the LLM-side intent-detection instructions.

---

## 16. Quiz Anchor Concept ID

**Bug:** During an active quiz, the LLM sometimes fetched a related concept for comparison (e.g. user answered about "Decorator pattern" mentioning lambdas, LLM fetched "Lambda Captures"). The fetch loop in `pipeline.py` unconditionally overwrote `active_concept_id` with the fetched concept's ID, causing the subsequent `assess` action to evaluate against the wrong concept. The §15 intent-detection fix handled *new questions* vs *quiz answers*, but this bug occurs when the user IS answering the quiz — just confusingly.

**Root cause (3 layers):**
1. **Fetch loop overwrite** (`pipeline.py`): `active_concept_id` was updated on every fetch, even during active quiz processing.
2. **No quiz-specific anchor**: `active_concept_id` served double duty — both "concept being discussed" and "concept being quizzed" — with no way to distinguish enrichment fetches from topic pivots.
3. **LLM prompt ambiguity** (`quiz.md`): assess docs said "use that ID unless the conversation has moved to a different topic," which the LLM misinterpreted when it fetched a comparison concept.

**Fix — `quiz_anchor_concept_id` lifecycle key:**

- **Set** by `_handle_quiz()` in `tools_assess.py` and by both `_send_review_reminder()` / `_send_review_quiz()` in `scheduler.py` whenever a quiz starts. Also pre-set by `/review` command (`bot/commands.py`) before `execute_llm_response` to ensure the anchor is present from the first turn.
- **Protected** in `pipeline.py` fetch loop: when `quiz_anchor_concept_id` or `active_concept_ids` is set, the fetch loop does NOT update `active_concept_id` at all, preventing the quizzed concept from being displaced by enrichment fetches.
- **Fallback chain** in `_handle_assess()` in `tools_assess.py`: when the LLM-provided `concept_id` is not found in DB, recovers via `quiz_anchor_concept_id` (Fallback 1), then `active_concept_id` (Fallback 2), then chat history regex (Fallback 3). Ensures the assessment reaches the correct concept even if the LLM provided a stale or invalid ID.
- **Injected** by `_append_active_quiz_context()` in `context.py`: anchor takes priority over `active_concept_id` for the context block the LLM sees.
- **Cleared** in `pipeline.py` alongside other quiz state by `_QUIZ_CLEARING_ACTIONS` (`assess`, `multi_assess`, `add_concept`, `suggest_topic`, `add_topic`, `remark`). Also cleared by staleness timeout in `context.py`.
- **Not used** by multi-quiz flows (those use separate `active_concept_ids` key).

**Prompt hardening:**
- `quiz.md`: assess docs changed to "Always use the concept_id from the 'Active Quiz Context' section" — removes ambiguous "unless conversation moved" language.
- `core.md`: added "Confused answer rule" under Intent Detection — confused answers that touch related concepts still count as quiz answers; assess or clarify, don't pivot.

**Key files:** `services/tools_assess.py` (`_handle_quiz`, `_handle_assess`), `services/pipeline.py` (fetch loop guard, `_QUIZ_CLEARING_ACTIONS`, `is_quiz_active`, assess guard), `services/context.py` (`_append_active_quiz_context`), `services/scheduler.py` (`_send_review_reminder`, `_send_review_quiz`), `bot/commands.py` (`/review` anchor pre-set), `scripts/agent.py` (assess guard), `data/skills/quiz.md`, `data/skills/core.md`, `tests/test_quiz_anchor.py`, `tests/test_assess_no_quiz_guard.py`.

---

## 21. Preference-Edit Isolated Skill Path

**What changed:** `/preference` now has two modes. With no arguments it shows the current runtime `data/preferences.md`. With text input it enters a one-shot edit flow that asks the LLM to rewrite the full preferences file, then shows `PreferenceUpdateView` Apply/Reject buttons before any write happens.

**Why it bypasses `_call_llm()`:** `call_preference_edit()` in `services/pipeline.py` talks to the provider directly instead of using the normal `_call_llm()` path. That is deliberate. The normal path injects conversation history and runs the action-extraction logic used for JSON actions; both behaviors corrupt the required fenced ` ```preferences ` output format. The isolated path keeps the response as plain text plus one fenced block so the parser can reliably extract the rewritten file.

**Template/runtime file split:** The tracked file is now `data/preferences.template.md`. The live file used in prompts remains `data/preferences.md`, but it is git-ignored and copied from the template on first bot startup (`bot/events.py` `on_ready()`). This avoids committing personal preference edits while still giving fresh clones a default file.

**Why there is no DB-backed proposal:** `PreferenceUpdateView` carries the proposed file content in memory and calls `execute_preference_update()` directly on approval. Unlike maintenance or dedup proposals, this flow edits a single local file for the authorized user, so a DB-backed pending-proposal record would add persistence complexity without providing much safety value.

**Key files:** `bot/commands.py` (`/preference`), `bot/events.py` (template bootstrap), `config.py` (`PREFERENCES_TEMPLATE_MD`), `services/pipeline.py` (`SKILL_SETS["preference-edit"]`, `_parse_preferences_fence`, `call_preference_edit`, `execute_preference_update`), `services/views.py` (`PreferenceUpdateView`), `data/skills/preferences.md`, `data/preferences.template.md`.

---

## Historical (completed — reference only)

**§H1 — Codebase Restructuring (2026-03-13):** Split `db.py` (1396 lines) → `db/` package (6 submodules). Split `pipeline.py` (750 lines) → `pipeline.py` + `parser.py` + `repair.py` + `dedup.py`. Fixed scheduler↔bot circular dependency via `services/state.py`. Backward compat maintained via re-exports.

**§H2 — FastAPI Backend & Project Restructuring (2026-03-15):** Created `api.py` as thin FastAPI wrapper using same pipeline. Moved `context.py`, `tools.py` → `services/`. Moved docs → `docs/`. Moved scripts → `scripts/`. Set up standalone git repo with `.env`-based config.

**§H3 — Module Extraction Refactor (2026-03-28):** Split oversized files into focused submodules: `db/core.py` (740→232) → extracted `db/migrations.py` (~265 lines, all migration blocks). `webui/server.py` (1090→198) → extracted `webui/helpers.py` (~145, HTML helpers) + `webui/pages.py` (~890, page renderers). `services/tools.py` (960→552) → extracted `services/tools_assess.py` (~360, quiz/assess action handlers). Child modules use `import db.core as _core` for dynamic DB path access (required by test fixtures that patch `db.core.KNOWLEDGE_DB`). Parent modules re-import from children after all local definitions to avoid circular imports.

**§H4 — WebUI Package Split + Forecast Feature + Configurable SR Exponent (2026-04-04):** `webui/pages.py` (~890 lines) further split into `webui/pages/` package (6 modules: `dashboard.py`, `topics.py`, `concepts.py`, `reviews.py`, `activity.py`, `graph.py`; ~950 total lines). All 10 page functions re-exported via `webui/pages/__init__.py`. Added `/forecast` page with D3 v7 bar chart (`webui/static/forecast.js`, ~245 lines) showing due concepts bucketed by days/weeks/months with Overdue always first; drill-down fetches concept list sorted mastery ASC. DB layer: `get_due_forecast(range_type)` and `get_forecast_bucket_concepts(range_type, bucket_key)` added to `db/concepts.py` using rolling `DATE('now', N || ' days')` windows (not calendar weeks). `config.SR_INTERVAL_EXPONENT` introduced (`LEARN_SR_INTERVAL_EXPONENT` env var, default `0.075`) replacing 3 hardcoded literals in `services/tools_assess.py`.

---

## 20. Taxonomy Shadow Rebuild

**Problem:** The standard taxonomy loop is conservative and mutates live state immediately for safe actions. For a full operator-driven rebuild, that was the wrong execution model: previewing changes needed to be isolated from live data, but a pure dry-run could not produce trustworthy IDs for dependent actions like `add_topic` followed by `link_topics`.

**Design — shadow preview + replay:**

1. **Separate-process shadow preview** (`scripts/taxonomy_shadow_rebuild.py`): the parent process copies `knowledge.db`, `chat_history.db`, and the embedded vector store to a temp workspace, then launches a child process with `LEARN_DB_PATH`, `LEARN_CHAT_DB_PATH`, and `LEARN_VECTOR_STORE_PATH` pointing at those shadow copies.
2. **Real taxonomy execution on shadow data**: preview runs the normal taxonomy loop against the copied stores, not a simulation. This preserves real topic IDs and lets the loop create/link topics exactly as it would on live data.
3. **Action journaling in `call_action_loop()`**: safe actions append structured entries to an optional `action_journal` list. `add_topic` records the newly created topic ID via `last_added_topic_id`, making downstream replay validation possible.
4. **Stable taxonomy session**: taxonomy-mode now uses one isolated session reused across the entire action loop. This avoids mixing operator rebuild traffic into the interactive conversation session and keeps the rebuild turns coherent.
5. **Apply = replay, not fresh rerun**: the live apply phase does **not** ask the LLM to regenerate actions. It first checks that the live taxonomy still matches the preview baseline, takes a fresh backup, then replays only the recorded safe actions in order.
6. **ID mismatch is a hard stop**: when replaying `add_topic`, the live-created ID must match the preview-created ID. If it does not, replay aborts because subsequent `link_topics` operations would target the wrong nodes.
7. **Approval-gated actions remain manual in v1**: `update_topic`, `unlink_topics`, `delete_topic`, `unlink_concept`, and `update_concept` are printed as follow-up work only. The script never auto-applies them.
8. **Structure snapshots are the operator-facing artifact**: each run writes `live_before`, `preview_after`, and `live_after` topic-tree snapshots under `backups/taxonomy_shadow_rebuild/` in markdown or plain text.

**Why separate processes?** `db/core.py` and `services/backup.py` capture path configuration at import time. Switching a single Python process from shadow paths back to live paths would be brittle and easy to get wrong. Separate child processes keep shadow preview and live apply isolated.

**Windows/OneDrive note:** backup finalization uses an atomic temp-dir rename. On Windows, OneDrive or Defender can briefly lock newly copied vector-store files and block that rename. `services/backup.py` now retries the final rename a few times before surfacing the error. If the backup directory lives under OneDrive, operators should prefer pausing sync or overriding `LEARN_BACKUP_DIR` to a non-OneDrive path during manual rebuilds.

**Operator guide:** see `docs/TAXONOMY_REBUILD.md` for the full manual workflow.

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

The skip is handled entirely in Discord UI (`QuizQuestionView` / `_QuizSkipButton`), calling `services.tools_assess.skip_quiz()` directly. It is **not** registered in `ACTION_HANDLERS` because the LLM should never autonomously skip a quiz — only the user presses the button.

**Scoring:** Uses the same quality=5 algorithm as a normal perfect answer. A synthetic `question_difficulty = min(100, current_score + 10)` is used since no actual question was assessed. This gives `base_gain=7` plus a gap-proportional bonus (`gap * 0.15`), typically ~8.5 points — identical to what a real quality-5 assessment would yield.

**Anti-gaming guard:** The skip button only appears when `review_count >= 2` for the concept. First-time and once-reviewed concepts must be answered properly. Enforced in both `_send_quiz_response` (button visibility) and `skip_quiz()` (server-side check).

**Race condition prevention:** `quiz_answered` session flag prevents double-scoring. Set by `skip_quiz()` on use. Reset to `None` at the start of every `_handle_user_message` call. The Discord button's `clicked` flag also prevents duplicate button presses.

**4-tuple return signature:** `_handle_user_message` was changed from 3-tuple `(response, pending_action, assess_meta)` to 4-tuple `(response, pending_action, assess_meta, quiz_meta)`. The new `quiz_meta = {concept_id, show_skip}` has two roles: (1) when `show_skip=True`, attach a `QuizQuestionView` with the skip button; (2) any non-None `quiz_meta` triggers `format_quiz_metadata()` being appended to the message footer. The delivery-path guard was widened from `elif quiz_meta and quiz_meta.get('show_skip'):` to `elif quiz_meta:` in both `bot/commands.py` and `bot/events.py` so that all quiz deliveries — not only skip-eligible ones — receive the metadata footer. A prior regression left `Quiz again` and `Next due` discarding `quiz_meta` and relying on session state; this was fixed by passing `quiz_meta` through `_send_quiz_response()`. `Explain` remains plain-text by design.

**Synthetic remark & LLM continuity:** `skip_quiz()` writes a synthetic remark (`"[Skipped — user indicated prior knowledge]"`) to preserve the LLM's strategy context. `quiz.md` instructs the LLM to probe skipped concepts more rigorously on next encounter.

**Session cleanup:** `skip_quiz()` clears `last_quiz_question`, `last_assess_concept_id`, `last_assess_quality`, and `pending_review` to prevent stale state from interfering with subsequent interactions.

**Delivery-path parity fix:** The manual `/review` command already attached `QuizQuestionView` when `review_count >= 2`, but scheduler-triggered review DMs originally sent plain text only. Both manual and scheduler review-question delivery now route through `bot.messages.send_review_question()`, so timer-triggered quizzes and manual reviews attach the skip button with the same eligibility rule, message-splitting behavior, and metadata footer.

**Quiz message metadata:** Every quiz question message now includes a bot-injected footer line produced by `format_quiz_metadata()` (in `services/formatting.py`): `📖 **{title}** · Score: N/100 · Review #N`. When `review_count < 2`, a hint `_(skip unlocks after N more review(s))_` is also appended. This is injected by the bot layer — the LLM does not generate it.

**Key files:** `services/tools_assess.py` (`skip_quiz()`), `services/views.py` (`QuizQuestionView`, `_QuizSkipButton`, `_send_quiz_response`), `services/formatting.py` (`format_quiz_metadata`), `bot/messages.py` (`send_review_question`, appends metadata + skip button), `bot/handler.py` (4-tuple return), `bot/commands.py` & `bot/events.py` (4-tuple handling, widened `elif quiz_meta:` guard), `data/skills/quiz.md` (LLM skip guidance).

---

## 19. SQLite Timestamp Timezone Trap

**Bug:** `_is_quiz_stale()` compared `datetime.now()` (local time) against `session_state.updated_at`, which SQLite stores as UTC via `CURRENT_TIMESTAMP`. In non-UTC timezones (e.g. UTC+8) every quiz appeared ~8 hours stale immediately on creation, clearing the quiz anchor and blocking all `assess` actions — so scores never updated.

**Fix:** Changed to `datetime.now(timezone.utc).replace(tzinfo=None)` — a UTC-naive datetime matching SQLite's UTC output.

**Rule:** SQLite `CURRENT_TIMESTAMP` and `datetime('now')` always return **UTC**. Any Python comparison against these columns must use `datetime.now(timezone.utc).replace(tzinfo=None)`, never bare `datetime.now()`. Other DB timestamps in this codebase are written by Python's `datetime.now()` (local) and compared locally — that is consistent. Only `session_state.updated_at` is written by SQLite directly.

**Affected file:** `services/context.py` (`_is_quiz_stale`).

---

## 22. Multi-User DB Groundwork

**Goal:** Make the storage layer multi-user-ready without changing existing single-user runtime behavior.

**What changed:**
- `Migration 12` rebuilt `session_state` to use composite PK `(user_id, key)` in `chat_history.db`.
- `Migration 13` added a `users` table in `knowledge.db`.
- `services/state.py` now owns `_current_user_id` as a ContextVar, with `set_current_user()` / `get_current_user()`.
- `db.core._uid()` lazily reads that ContextVar so db functions can accept `*, user_id=None` and default safely.
- `db/concepts.py`, `db/topics.py`, `db/reviews.py`, `db/chat.py`, `db/action_log.py`, and `db/diagnostics.py` now scope reads/writes by `user_id`.

**Important behavior rule:** The app is still single-user externally until entry points call `set_current_user()`. Right now all callers fall back to `user_id='default'`, which keeps old data and old behavior intact.

**Known limitation:** concept title uniqueness is still global. A future migration should replace the global title uniqueness with `UNIQUE(user_id, title COLLATE NOCASE)`.

**Validation:** full suite green with `python -m pytest tests/ -x -q --tb=short -o "addopts="`.

---

## 23. Process-Local Lock Hardening

**Goal:** Keep the runtime single-user and trustworthy across bot, WebUI, API, and scheduler paths that still share mutable in-process state.

**Key decisions:**
- `services/state.py` now owns the shared `PIPELINE_LOCK` plus `pipeline_serialized()` and `pipeline_serialized_nowait()` helpers. This replaced the old WebUI-only lock and made the process-local boundary explicit.
- Bot message handling, manual review/maintenance/taxonomy/preference flows, reply-based confirmations, direct Discord button bypasses, and FastAPI chat/confirm/decline now all serialize through the same lock.
- The scheduler does **not** block waiting for that lock. Review, maintenance, taxonomy, and dedup checks skip the current cycle when the pipeline is busy so background work yields to active chat turns.
- `db.chat` session helpers and `db.action_log.log_action()` now resolve omitted `user_id` through `_uid()`. `clear_session(None)` intentionally still means clear all users.
- `OpenAICompatibleProvider._get_messages()` must return a copy of stored session messages. Returning the live list let callers mutate provider state accidentally.

**Vector-search lesson:** Qdrant-first helpers must not early-return empty results when vector hits point at stale ids. `db.search_concepts()` and `db.diagnostics._get_relationship_candidates()` now fall back to SQL/FTS when vector-derived ids do not map back to current SQLite rows.

**Important scope rule:** This hardening is process-local only. The runtime is still single-user externally until entry points call `set_current_user()` with real identities.