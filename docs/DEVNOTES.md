# DEVNOTES.md — learning_agent

> **Purpose:** Project-specific institutional memory. Past bugs, architecture decisions,
> and non-obvious patterns for this codebase.
>
> **Audience:** Developers / Copilot during code-editing sessions only.
> The runtime LLM does NOT read this file — its instructions are in `AGENTS.md`.
>
> **When to update:** After fixing a non-trivial bug or making an architectural decision
> that isn't obvious from the code — add a short entry here.

---

## Table of Contents
1. [LLM Output Formatting Bugs](#1-llm-output-formatting-bugs)
2. [Architecture Decisions](#2-architecture-decisions)
3. [Score-Based Review System](#3-score-based-review-system)
4. [Codebase Restructuring for LLM Dev Scalability](#4-codebase-restructuring-for-llm-dev-scalability)
5. [FastAPI Backend & Project Restructuring](#5-fastapi-backend--project-restructuring)

---

## 1. LLM Output Formatting Bugs

### 1.1 `assess` action: LLM puts fields at top level instead of inside `params`
**Date:** 2026-03-10

**Symptom:** After a quiz answer, the bot replied `⚠️ assess requires concept_id and quality (0-5)` even though the user answered correctly.

**Root cause:** The LLM returned:
```json
{"action": "assess", "concept_id": 19, "understood": true, "remark": "..."}
```
instead of:
```json
{"action": "assess", "params": {"concept_id": 19, "quality": 4, ...}, "message": "..."}
```

Three failures:
- Fields at top level instead of inside `"params"` wrapper
- Used `"understood": true` (boolean) instead of `"quality": 0-5` (integer)
- Omitted `"message"` entirely

**Why:** `AGENTS.md` had a parameter list for `assess` but **no concrete JSON example**. Every other action (`add_concept`, `fetch`, `quiz`) had a `json` example block. The LLM hallucinated a wrong structure without a template to follow.

**Fix:** Added a full JSON example for `assess` in `AGENTS.md` (with a `<!-- DO NOT REMOVE -->` comment to prevent accidental deletion during context trimming).

**Lesson:** Every action that the LLM can emit MUST have a concrete JSON example in `AGENTS.md`. Parameter lists alone are not enough — the LLM needs an unambiguous template to copy.

### 1.2 `quiz` action: same flat-format bug as assess
**Date:** 2026-03-10

**Symptom:** LLM returned `{"action": "quiz", "concept_id": 8, "question": "..."}` — fields at top level, no `params` wrapper, and used `question` instead of `message`. The quiz appeared to work (user saw the question) but `concept_id` was silently lost — `_handle_quiz` never appended the `_(quiz on concept #X)_` tracking tag to chat history, breaking the subsequent `assess` context.

**Fix:** Added JSON example for `quiz` in `AGENTS.md` (same approach as assess fix).

### 1.3 Defensive flat-params recovery added to `execute_action`
**Date:** 2026-03-10

**Context:** After adding JSON examples for both `assess` and `quiz` in AGENTS.md, the LLM still returned flat-format `assess` on the very next call. The prompt fix alone is not enough for this particular model/behavior.

**Fix:** Added a code-level fallback in `pipeline.py → execute_action()` that detects when `params` is empty but extra keys exist at the top level, and recovers them into `params`. Logs a warning when triggered so we can track frequency.

**Note:** This does NOT fix missing/wrong fields (e.g. `understood: true` instead of `quality: 4`) — it only recovers the structural mismatch. The prompt examples remain the primary fix for teaching the LLM the correct field names.

---

## 2. Architecture Decisions

### 2.1 Prompt-first fixes over defensive code
**Date:** 2026-03-10

When the LLM emits malformed actions, prefer fixing the prompt (`AGENTS.md`) over adding defensive parsing code. Rationale:
- Defensive code masks prompt bugs — the LLM keeps emitting bad JSON, it just happens to work
- Fixing the prompt fixes the root cause and improves all actions, not just the patched one
- Aligns with workspace-wide LLM-first design principle (see root `AGENTS.md`)

Only add code-level fallbacks if the same prompt bug recurs after two prompt fix attempts.

### 2.2 Repair sub-agent with ephemeral kimi session
**Date:** 2026-03-12

**Problem:** LLM hallucinated `GENERATE_QUIZ` as an action name (not in `ACTION_HANDLERS`). The existing flat-params recovery (§1.3) couldn't help because the *action name itself* was wrong, not just the structure. The prompt already had a `quiz` JSON example (§1.2 fix) and an explicit constraint ("use ONLY exact action names" added to AGENTS.md), yet the LLM still invented a new name — likely seeded by the scheduler prompt which said "Generate a review quiz".

**Fix (three layers):**
1. **Prompt:** Added bolded constraint in AGENTS.md: "Use ONLY the exact action names listed below." Reworded scheduler prompt from "Generate a review quiz" → "Start a review quiz" to remove the hallucination seed.
2. **Repair sub-agent:** Added `_repair_action()` in `pipeline.py`. When `execute_action()` gets an "Unknown action" error, it calls a lightweight kimi session to fix the malformed JSON. Uses `--session learn_repair_HHMM` to reuse context across calls.
3. **Ephemeral session rotation:** Session name rotates every 15 minutes (aligned with `REVIEW_CHECK_INTERVAL_MINUTES`) to cap context window growth. On first use of a new session, the seeding prompt teaches kimi the valid action list (~300 chars). Subsequent calls within the same session only send the malformed JSON (~100 chars).

**Latency impact:** Zero cost on happy path (valid actions). ~5-10s on repair path (warm session, small prompt) vs ~15-25s if it were a cold subprocess. Kimi session files in `~/.kimi/sessions/` are small and not cleaned up — add cleanup later if disk use becomes an issue.

**Escalation hierarchy for LLM output errors:**
1. Flat-params recovery (§1.3) — code, instant, structural fix only
2. Repair sub-agent (§2.2) — kimi session, ~5-10s, fixes action names
3. Error to user — if repair also fails

**Async change:** `execute_action()` and `execute_llm_response()` in `pipeline.py` are now `async` to support the repair sub-agent `await`. All callers in `bot.py` and `scheduler.py` updated to `await`.

### 2.3 Session reuse across conversation
**Date:** 2026-03-12

**Problem:** Every kimi-cli call was a fresh subprocess with no session — even across related messages (quiz question → user answer → assess). Each call re-sends the full ~4500 char prompt including AGENTS.md file refs, topic map, and chat history. Within a single request, the fetch loop was also redundantly sending full context on every iteration.

**Fix:** `_get_conv_session()` manages a conversation-level session (`learn_HHMMSS`) that persists across `call_with_fetch_loop()` invocations:
- **New session** created when idle for `SESSION_TIMEOUT_MINUTES` (5 min, same as Discord session timeout)
- **Within a fetch loop:** iteration 0 sends full prompt; iterations 1+ use lightweight `_call_kimi_followup()` (~500 chars) since kimi already has context in the session
- **Across user messages:** quiz question and user's answer reuse the same session, so kimi retains the question context for better assess accuracy

**Latency impact:**
- Fetch follow-ups: ~500 chars prompt vs ~4500 chars (90% smaller)
- Cross-message continuity: kimi doesn't need to re-parse AGENTS.md from file refs on every call within the session

**Session lifecycle:** One session per active conversation (5-min idle timeout). Sessions accumulate in `~/.kimi/sessions/` as small files. Cleanup deferred.

---

## 3. Score-Based Review System

### 3.1 Replaced SM-2 with asymmetric score system
**Date:** 2026-03-12

**Problem:** The old SM-2 system had three compounding issues:
1. `mastery_level = quality` — one bad answer dropped mastery from 5 → 0 (volatile)
2. Hard interval reset on wrong answers — back to 1 day after 4 good reviews
3. No distinction between "user regressed" and "LLM probed beyond user's level"

The root cause: the LLM dynamically adjusts question difficulty (a good thing), but the scoring system treated all wrong answers equally. A user at mastery 3 who fails a synthesis-level question gets the same penalty as someone who fails a basic recall question.

**Solution:** Replaced with a **score-based system (0–100)** with asymmetric deltas:
- **question_difficulty** (0–100): LLM reports how hard its question was
- **gap = question_difficulty − current_score**: positive means question was above user's level
- **Correct:** score increases (bigger gain for harder questions)
- **Wrong + gap > 0:** NO decrease — recognized as a probe above user's level
- **Wrong + gap ≤ 0:** proportional decrease — actual regression on material they should know

### 3.2 Score → interval via exponential curve
**Formula:** `interval_days = max(1, round(e^(score × 0.05)))`

| Score | Interval | Phase |
|-------|----------|-------|
| 0 | 1 day | Just learned |
| 25 | 3 days | Building |
| 50 | 12 days | Solid |
| 75 | 43 days | Approaching mastery |
| 100 | 148 days | Mastered |

This replaces both `ease_factor` and the old SM-2 interval multiplication. The exponential coefficient (0.05) is tunable — increase for faster spacing, decrease for more frequent reviews.

**Key property for scalability:** As the knowledge base grows, high-score concepts automatically space themselves far apart. 100 concepts at score 50 ≈ 8 reviews/day. At score 70 ≈ 3/day.

### 3.3 ease_factor frozen
`ease_factor` is no longer updated by `_handle_assess`. The column remains in the DB for backward compatibility but is not used in any calculations. Cleanup (dropping the column) is deferred.

### 3.4 Migration (schema v4)
Migration 4 in `db.py` converts existing data:
- `mastery_level *= 15` (maps 0–5 → 0–75 range)
- Guard: skips if any `mastery_level > 5` (already migrated)
- Recalculates `interval_days` and `next_review_at` from new scores
- Imprecise but self-corrects within 1–2 reviews

### 3.5 Score delta constants
```
CORRECT — base gain: q3=2, q4=4, q5=7
  above level: gain = base + gap × 0.15
  at/below:    gain = max(1, base × 0.5)

WRONG — base loss: q0=5, q1=3, q2=1
  above level: loss = 0  (no penalty)
  at/below:    loss = base + |gap| × 0.2
```
These are tunable. If scores climb too fast, reduce the gain multiplier (0.15). If wrong-answer penalties feel too harsh, reduce the loss multiplier (0.2).

### 3.6 question_difficulty estimation
LLM provides `question_difficulty` in the `assess` action. If omitted, the code estimates:
- quality ≥ 4: `min(100, score + 10)` (question was near their level)
- quality = 3: `score` (marginal)
- quality ≤ 2: `min(100, score + 15)` (benefit of the doubt — likely probed above level)

The LLM is instructed to use a **hybrid tier + fine-tuning** approach: pick the tier matching the user's score (0–25 / 25–50 / 50–75 / 75–100), then estimate a precise number within that band.

---

## 4. Codebase Restructuring for LLM Dev Scalability
**Date:** 2026-03-13

**Problem:** Adding a new feature required reading ~3900 lines of context (db.py 1396 + pipeline.py 750 + tools.py 540 + agent.py 387 + context.py 426 + bot.py 439). An LLM developer (Copilot, etc.) needed most of the codebase in its context window for any non-trivial change.

**Goal:** Reduce typical per-feature context to ~1000 lines by splitting monolithic files into focused modules.

### 4.1 db.py → db/ package
Replaced the 1396-line `db.py` monolith with a `db/` package (6 submodules):

| Module | Responsibility | ~Lines |
|--------|---------------|--------|
| `db/core.py` | Connection helpers, `init_databases()`, migrations, datetime utils, constants | 310 |
| `db/topics.py` | Topic CRUD, topic maps, hierarchical maps | 240 |
| `db/concepts.py` | Concept CRUD, search, detail view | 260 |
| `db/reviews.py` | Review log, remarks | 100 |
| `db/chat.py` | Chat history, session state | 105 |
| `db/diagnostics.py` | Maintenance diagnostics, title similarity | 140 |
| `db/__init__.py` | Re-exports all public functions | 120 |

**Backward compatibility:** `db/__init__.py` re-exports every public function. All existing `import db; db.add_concept(...)` calls work unchanged. No callers were modified.

### 4.2 pipeline.py → focused service modules
Split the 750-line `services/pipeline.py` into:

| Module | Responsibility | ~Lines |
|--------|---------------|--------|
| `services/parser.py` | `parse_llm_response`, `extract_llm_action`, `process_output`, `extract_fetch_params` | 180 |
| `services/repair.py` | `repair_action` (action-name repair sub-agent) | 90 |
| `services/dedup.py` | `handle_dedup_check`, `execute_dedup_merges`, `_parse_dedup_response` | 140 |
| `services/pipeline.py` | Pure orchestration: `execute_action`, `call_with_fetch_loop`, `handle_review_check`, `handle_maintenance` | 342 |

**Backward compatibility:** `pipeline.py` re-imports `process_output`, `handle_dedup_check`, and `execute_dedup_merges` so existing `pipeline.xxx()` calls in bot.py, scheduler.py, and tests continue to work.

### 4.3 Deduplicated parse_llm_response
`agent.py` had a ~50-line copy of `parse_llm_response` + `_extract_json_object` that diverged from the pipeline copy. Removed the duplicate; `agent.py` now imports from `services.parser`.

### 4.4 Fixed circular dependency (scheduler ↔ bot)
`scheduler.py` imported `bot` at runtime to read `bot.last_activity_at`. Created `services/state.py` (~10 lines) with `last_activity_at: datetime | None`. Both `bot.py` (writes) and `scheduler.py` (reads) now use the shared state module. No runtime `import bot` needed.

### 4.5 Old files kept for reference
`_db_old.py` and `services/_pipeline_old.py` are the renamed originals. Safe to delete once confidence is high. They are prefixed with `_` so they won't be imported accidentally.

### 4.6 How to work with the new structure
- **Adding a new db function:** Put it in the appropriate `db/*.py` submodule, add to `db/__init__.py` re-exports.
- **Adding a new action:** Only touch `services/pipeline.py` (the orchestrator) and `tools.py`.
- **Changing LLM output parsing:** Only touch `services/parser.py`.
- **Changing dedup logic:** Only touch `services/dedup.py`.
- **Changing review scheduling:** Only touch `services/scheduler.py` + `db/reviews.py`.

---

## 5. FastAPI Backend & Project Restructuring
**Date:** 2026-03-15

### 5.1 FastAPI backend (`api.py`) — parallel entry point
**Goal:** Enable a mobile app (React Native) to use the same learning pipeline via HTTP, while keeping the Discord bot running.

**Implementation:** Created `api.py` (~150 lines) as a thin FastAPI wrapper that calls the exact same pipeline functions as `bot.py`:
```
bot.py (Discord)  ─┐
                    ├──→  pipeline.call_with_fetch_loop()  →  execute_llm_response()  →  process_output()
api.py (FastAPI)  ─┘
```

**Endpoints:**
| Method | Route | Maps to |
|--------|-------|---------|
| `POST` | `/api/chat` | `pipeline.call_with_fetch_loop()` → `execute_llm_response()` → `process_output()` |
| `GET` | `/api/topics` | `db.get_hierarchical_topic_map()` |
| `GET` | `/api/topics/{id}` | `db.get_topic()` + `db.get_concepts_for_topic()` |
| `GET` | `/api/concepts/{id}` | `db.get_concept_detail()` |
| `GET` | `/api/due` | `db.get_due_concepts()` |
| `GET` | `/api/stats` | `db.get_review_stats()` |
| `GET` | `/api/health` | Health check (no auth) |

**Auth:** Optional bearer token via `API_SECRET_KEY` config. Skipped if not set (solo mode). Same header pattern upgrades to Firebase tokens later.

**Concurrency with bot.py:** Both run as separate processes. SQLite WAL mode + short-lived connections handle concurrent access. The `webui/server.py` already proved this pattern works.

**No scheduler in API:** The Discord bot owns the scheduler (review DMs, maintenance). The mobile app uses `GET /api/due` on launch instead.

### 5.2 Project structure reorganization
**Problem:** 17 items at root, with internal modules (`context.py`, `tools.py`) mixed with entry points and docs.

**Changes:**
| Move | Reason |
|------|--------|
| `context.py` → `services/context.py` | Only imported by `services/pipeline.py` — belongs with the rest of the service layer |
| `tools.py` → `services/tools.py` | Only imported by `services/pipeline.py` and `services/repair.py` |
| `agent.py` → `scripts/agent.py` | Dead code (not imported anywhere), kept for manual CLI debugging |
| `ARCHITECTURE.md`, `DEVNOTES.md`, `PLAN.md` → `docs/` | Dev docs, not runtime files |
| `start.bat`, `start_api.bat` → `scripts/` | Launcher scripts |

**Path fixes required after moves:**
- `context.py`: `Path(__file__).parent` → `Path(__file__).parent.parent` for `AGENTS.md` and `preferences.md`
- `tools.py`: same fix for `preferences.md`
- `pipeline.py`: `import context as ctx` → `from services import context as ctx`; `import tools` → `from services import tools`
- `repair.py`: `import tools` → `from services import tools`
- `bot.py`: `from tools import _handle_list_topics` → `from services.tools import _handle_list_topics`
- Tests: updated accordingly
- Bat scripts: added `cd /d "%~dp0\..\"` and fixed venv activation paths

**Result:** Root went from 17 items → 9 items. Entry points (`bot.py`, `api.py`) and runtime config (`config.py`, `AGENTS.md`, `preferences.md`) stay at root. Everything else is organized.

### 5.3 Standalone git repo
**Problem:** Project was a subfolder inside the `PA/` git repo. Needed its own repo for GitHub.

**Security audit before commit:**
- Removed hardcoded Discord bot token from `config.py` (was a fallback default)
- Removed hardcoded `AUTHORIZED_USER_ID` — now reads from `LEARN_AUTHORIZED_USER_ID` env var
- Sanitized `ARCHITECTURE.md` — removed personal Discord user ID
- All secrets now live in `.env` (git-ignored) or environment variables

**Files added:**
- `.gitignore` — excludes `venv/`, `data/`, `__pycache__/`, `.env`
- `.env.example` — documents all env vars
- `python-dotenv` added to requirements — `config.py` auto-loads `.env` on import

### 5.4 Config changes
- `API_HOST`, `API_PORT`, `API_SECRET_KEY` added (env vars: `LEARN_API_HOST`, `LEARN_API_PORT`, `LEARN_API_SECRET_KEY`)
- `BOT_TOKEN` no longer has a hardcoded fallback — empty string default, must be set via env var for Discord mode
- `AUTHORIZED_USER_ID` now reads from `LEARN_AUTHORIZED_USER_ID` env var (default `0`)
- `validate_config()` relaxed — `BOT_TOKEN` no longer validated (not needed for API-only mode)
- `python-dotenv` loads `.env` at import time with graceful fallback if not installed

### 5.5 Virtual environment
Added `venv/` (Python 3.12) with all dependencies. Both `scripts/start.bat` and `scripts/start_api.bat` auto-activate the venv before launching. The venv is git-ignored.

---

## 6. Confirmation Flows for Dedup & Maintenance
**Date:** 2026-03-15

### 6.1 Problem: Dedup auto-merged concepts without confirmation
The dedup sub-agent ran on a 24h schedule, identified potential duplicates via LLM, and **immediately deleted** merge targets. No user approval. This caused:
- Related-but-distinct concepts merged (e.g. "Ring Buffer" → "ISR Bottom Half")
- Concepts became too broad for effective spaced repetition
- User lost granularity in their knowledge graph

### 6.2 Problem: Maintenance auto-executed destructive actions
The maintenance LLM could `delete_concept`, `unlink_concept`, etc. without asking. While AGENTS.md said to "suggest" some actions, there was no code-level enforcement.

### 6.3 Fix: Proposal-based confirmation with Discord buttons

**Architecture:** Destructive actions are now **proposals** stored in a `pending_proposals` DB table. Users approve/reject via discord.py `View`/`Button` components (not text replies — those would be consumed by the LLM pipeline).

**Flow:**
```
Scheduler/Command
    │
    ├── Dedup: LLM identifies duplicates → save_proposal('dedup', groups)
    │   → DM user with DedupConfirmView (per-group ✅/❌ + bulk buttons)
    │   → User clicks buttons → execute_dedup_merges(approved_groups)
    │
    └── Maintenance: LLM proposes actions → safe ones execute immediately
        → destructive ones → save_proposal('maintenance', actions)
        → DM user with MaintenanceConfirmView (same button pattern)
        → User clicks → execute_maintenance_actions(approved_actions)
```

**Key design decisions:**
- **Discord buttons over text replies** — `on_message` routes all text to the LLM pipeline; intercepting "1, 2" or "all" is fragile and ambiguous. Buttons are mobile-friendly, have built-in timeout, and the callback lives in the View class (not `on_message`).
- **DB-backed proposals over in-memory state** — the bot restarts (exit code 42 mechanism). In-memory state would be lost between DM and user response (hours later). DB proposals survive restarts.
- **24h auto-expiry** — `View(timeout=86400)` disables buttons after 24h. DB rows also have `expires_at` column, cleaned up by scheduler.
- **Skip dedup if pending** — if a proposal from the last cycle isn't resolved yet, the next cycle skips dedup. Prevents overwriting proposals.
- **Separate proposal from execution in maintenance** — `call_maintenance_loop` returns `(report_text, proposed_actions)`. Safe actions (`link_concept`, `delete_topic` for empty topics, `remark`) execute immediately. Destructive actions (`delete_concept`, `unlink_concept`, `update_concept`) are collected and shown with buttons.

### 6.4 Dedup prompt tightened
The dedup LLM prompt was too permissive — "find duplicate or highly overlapping concepts" merged related concepts. New prompt:
- Only merge concepts that are the **same thing with different wording**
- Explicit examples of what IS vs IS NOT a duplicate
- "When in doubt, do NOT merge" instruction
- Removed "highly overlapping" language

### 6.5 Schema change (migration 6)
Added `pending_proposals` table to `knowledge.db`:
```sql
CREATE TABLE pending_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_type TEXT NOT NULL,       -- 'dedup' or 'maintenance'
    payload TEXT NOT NULL,             -- JSON blob of action dicts
    discord_message_id INTEGER,        -- for reference
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL
);
```

### 6.6 New files
- `db/proposals.py` — CRUD for pending proposals (save, get, delete, cleanup)
- `services/views.py` — Discord UI views (`DedupConfirmView`, `MaintenanceConfirmView`)

### 6.7 AGENTS.md maintenance rules updated
Removed "Potential duplicates" from auto-fix list. Added explicit boundary:
- Maintenance handles structural issues (empty topics, untagged concepts)
- Dedup handles duplicate detection (separate sub-agent)
- Destructive actions are proposals, not auto-executed

---

## 7. Discord 2000-Character Limit Overflow
**Date:** 2026-03-15

### 7.1 Symptom
Clicking "Add concept" on a confirmation button crashed with:
```
discord.errors.HTTPException: 400 Bad Request (error code: 50035): Invalid Form Body
In data.content: Must be 2000 or fewer in length.
```

### 7.2 Root cause
`AddConceptConfirmView.accept` in `services/views.py` appended a status note to the original message without checking combined length:
```python
original = interaction.message.content or ""  # up to 1900 chars
await interaction.response.edit_message(content=original + note, view=self)  # note ~60-130 chars
```
Total: 1900 + 130 = 2030 > 2000. Same pattern existed in the text-reply confirmation path in `bot.py` and `_QuizDoneButton`.

### 7.3 All affected locations (fixed)

| File | Location | Pattern | Risk |
|------|----------|---------|------|
| `services/views.py` | `AddConceptConfirmView.accept` | `original + note` | **Crash (reported)** |
| `bot.py` | Text-reply "yes" handler | `orig.content + note` | **Crash (same pattern)** |
| `services/views.py` | `_QuizDoneButton.callback` | `original + "✋ Quiz session ended."` | Moderate |
| `bot.py` | `/learn` with `pending_action` | `send(response, view=view)` — no truncation | Moderate |
| `services/scheduler.py` | Review DM send | `f"📚 **Learning Review**\n{message}"` | Moderate |
| `services/scheduler.py` | Fallback review DM | `f"📚 **Learning Review** — Time to review:\n{payload}"` | Low |
| `services/views.py` | `DedupConfirmView._finalize` | `edit(content=result_text)` | Defensive |
| `services/views.py` | `MaintenanceConfirmView._finalize` | Same | Defensive |
| `services/views.py` | `ApproveGroupButton` / `RejectGroupButton` | Status text edit | Defensive |
| `services/views.py` | `_QuizExplainButton` / `_send_quiz_response` | Hardcoded `[:2000]` | Normalized |

### 7.4 Fix: `services/formatting.py`
Created a shared utility module with:
- `DISCORD_CHAR_LIMIT = 2000` — replaces magic `[:2000]` slices
- `truncate_for_discord(text, max_len)` — truncate with `…` ellipsis
- `truncate_with_suffix(original, suffix, max_len)` — truncates `original` to preserve `suffix`; handles suffix-only overflow

Used by `views.py`, `bot.py`, and `scheduler.py`. Not imported by `api.py` or any pipeline/db module — this is a Discord transport concern.

### 7.5 Convention: 1900 vs 2000

| Constant | Value | Used for |
|----------|-------|----------|
| `config.MAX_MESSAGE_LENGTH` | 1900 | Initial sends — conservative buffer for Discord overhead |
| `formatting.DISCORD_CHAR_LIMIT` | 2000 | Edits / appends — hard limit, every char counts |

### 7.6 Architecture note
`api.py` (FastAPI) is unaffected — it returns raw JSON with no character limit. The React Native app (PLAN.md Phase 3) will handle its own display constraints client-side. The truncation helpers live in `services/formatting.py` (pure string ops, no discord.py dependency) so they can be reused for future mobile push notification truncation (FCM has its own limits).