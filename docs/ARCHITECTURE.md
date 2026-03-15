# Learning Agent — Architecture Documentation

> Last updated: 2026-03-18

## Overview

The Learning Agent is a Discord-based spaced repetition system where **all learning intelligence lives in an LLM prompt** (AGENTS.md), not in code. The codebase provides thin CRUD plumbing and a pipeline that shuttles messages between user ↔ LLM ↔ database.

```
┌──────────────────────────────────────────────────────────────────────┐
│                         User Interfaces                              │
│   ┌──────────────┐              ┌──────────────────────────────┐    │
│   │  Discord Bot  │              │  Web UI (read-only browser)  │    │
│   │  (bot.py)     │              │  (webui/server.py :8050)      │    │
│   └──────┬───────┘              └──────────────┬───────────────┘    │
│          │                                      │                    │
├──────────┼──────────────────────────────────────┼────────────────────┤
│          │ Pipeline Layer                       │                    │
│          ▼                                      │                    │
│   ┌──────────────────────┐                      │                    │
│   │  pipeline.py         │                      │                    │
│   │  (orchestrator)      │                      │                    │
│   │  context → LLM →     │                      │                    │
│   │  parse → execute     │                      │                    │
│   └──┬─────────┬────┬───┘                      │                    │
│      │         │    │                            │                    │
│      │         │    ▼                            │                    │
│      │         │  ┌──────────────┐               │                    │
│      │         │  │  kimi.py     │               │                    │
│      │         │  │  (subprocess)│               │                    │
│      │         │  └──────┬───────┘               │                    │
│      │         │         │                       │                    │
│      │         │         ▼                       │                    │
│      │         │  ┌──────────────┐               │                    │
│      │         │  │  kimi-cli    │               │                    │
│      │         │  │  (external)  │               │                    │
│      │         │  │  Reads:      │               │                    │
│      │         │  │  AGENTS.md   │               │                    │
│      │         │  │  preferences │               │                    │
│      │         │  └──────────────┘               │                    │
│      │         │                                 │                    │
│      ▼         ▼                                 │                    │
│   ┌────────┐ ┌───────────┐                       │                    │
│   │context │ │  tools.py  │                      │                    │
│   │  .py   │ │  (action   │                      │                    │
│   │(prompt)│ │  executor) │                      │                    │
│   └───┬────┘ └─────┬─────┘                      │                    │
│       │             │                            │                    │
├───────┼─────────────┼────────────────────────────┼────────────────────┤
│       │    Data Layer│                            │                    │
│       ▼             ▼                            ▼                    │
│   ┌────────────────────────────────────────────────────┐             │
│   │                  db/ package                       │             │
│   │  core.py · topics.py · concepts.py                 │             │
│   │  reviews.py · chat.py · diagnostics.py             │             │
│   └──────────┬────────────────────────┬────────────────┘             │
│              ▼                        ▼                              │
│   ┌──────────────────┐     ┌──────────────────┐                     │
│   │  knowledge.db    │     │  chat_history.db  │                    │
│   │  (topics,        │     │  (conversations)  │                    │
│   │   concepts,      │     │                   │                    │
│   │   reviews,       │     │                   │                    │
│   │   remarks)       │     │                   │                    │
│   └──────────────────┘     └──────────────────┘                     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## File Map

| File | Lines | Role |
|:-----|------:|:-----|
| `AGENTS.md` | ~540 | System prompt — ALL learning intelligence (quiz strategy, difficulty tiers, SM-2 rubric, topic management rules) |
| `preferences.md` | ~20 | User learning preferences (interests, style) |
| `bot.py` | ~300 | Discord bot entry point — events, commands, message routing |
| `config.py` | ~80 | Tokens, paths, timeouts, intervals |
| `context.py` | ~370 | Prompt/context construction — builds the dynamic context injected into every LLM call |
| `tools.py` | ~490 | Action executor — maps LLM JSON actions to `db.*` CRUD calls |
| `db/` | ~1175 | Database package — see submodules below |
| `agent.py` | ~310 | CLI entry point for standalone testing (not used by the bot at runtime) |
| `webui/server.py` | ~530 | Zero-dependency HTTP UI — interactive topic tree, static file serving |
| `webui/static/style.css` | ~170 | Extracted CSS — dark theme, tree components, responsive layout |
| `webui/static/tree.js` | ~150 | Vanilla JS — expand/collapse, search/filter, state persistence |
| **db/ package** | | |
| `db/core.py` | ~310 | Connection helpers, `init_databases()`, migrations, datetime utils |
| `db/topics.py` | ~240 | Topic CRUD, topic maps, hierarchical maps |
| `db/concepts.py` | ~260 | Concept CRUD, search, detail view |
| `db/reviews.py` | ~100 | Review log, remarks |
| `db/chat.py` | ~105 | Chat history, session state |
| `db/diagnostics.py` | ~140 | Maintenance diagnostics, title similarity |
| `db/__init__.py` | ~120 | Re-exports all public functions (backward compat) |
| **services/** | | |
| `services/pipeline.py` | ~342 | Core orchestrator — context → kimi-cli → parse → execute, with fetch loop |
| `services/parser.py` | ~180 | LLM response parsing — `parse_llm_response`, `process_output`, `extract_llm_action` |
| `services/repair.py` | ~90 | Action-name repair sub-agent (ephemeral kimi session) |
| `services/dedup.py` | ~140 | Dedup check and merge execution |
| `services/kimi.py` | ~83 | Thin subprocess wrapper around kimi-cli (the only subprocess in the system) |
| `services/scheduler.py` | ~200 | Background task — review checks every 15 min, maintenance every 24 h |
| `services/state.py` | ~10 | Shared mutable state (e.g. `last_activity_at`) between bot and scheduler |
| **tests/** | | |
| `tests/test_maintenance.py` | ~160 | Test maintenance diagnostics and dedup sub-agent |
| `tests/test_dedup.py` | ~35 | Quick test for title similarity and duplicate detection |

---

## Core Design Principle: LLM-First

The LLM (via AGENTS.md) makes **all** decisions:
- What to teach, when to quiz, how to adapt difficulty
- Whether to create topics/concepts from casual conversation
- How to assess answers (SM-2 quality 0–5)
- When to restructure the knowledge graph (merge topics, split oversized ones)
- What remarks to write for its own future self

The code is intentionally "dumb" — it provides CRUD primitives and a pipeline, nothing more. To change a behavior, **edit AGENTS.md**, not code.

---

## Interaction Flows

### Flow 1: User sends a Discord message

```
  User types in Discord
         │
         ▼
  bot.py: on_message or /learn command
         │
         ▼
  bot._handle_user_message(text, author)
         │
         ▼
  pipeline.call_with_fetch_loop("command", text, author)     ← async
         │
         ├─── context.build_prompt_context(text, "command")  ← direct call
         │         │
         │         ├── db.get_hierarchical_topic_map()
         │         ├── db.get_due_concepts(limit=5)
         │         ├── db.get_review_stats()
         │         └── db.get_chat_history(limit=20)
         │
         ├─── Assemble prompt:
         │      "Read AGENTS.md at <path>"
         │      "Read preferences.md at <path>"
         │      + dynamic context (topics, due, chat history)
         │      + "User said: <text>"
         │
         ├─── kimi.run_kimi(prompt)                          ← only subprocess
         │         │
         │         └── kimi-cli reads AGENTS.md + preferences.md from disk
         │             returns structured response (JSON action, REPLY:, etc.)
         │
         ├─── pipeline.extract_llm_action(raw_output)
         │         └── strips echoed prompt, finds last JSON or prefix
         │
         ├─── Is it a FETCH action? ─── YES ──┐
         │                                      │
         │    (up to 3 iterations)              ▼
         │                            tools.execute_action('fetch', params)
         │                                      │
         │                            context.format_fetch_result(data)
         │                                      │
         │                            append to extra_context, re-call kimi ──┘
         │
         └─── Final non-fetch LLM response (string)
                    │
                    ▼
  pipeline.execute_llm_response(text, llm_response, "command")  ← sync
         │
         ├── pipeline.parse_llm_response(llm_response)
         │       → (prefix, message, action_data)
         │
         ├── If action_data:
         │       pipeline.execute_action(action_data)
         │           → tools.execute_action(action, params)
         │               → db.<crud_operation>(...)
         │
         ├── db.add_chat_message('user', text)
         ├── db.add_chat_message('assistant', result)
         │
         └── return "PREFIX: message"
                    │
                    ▼
  pipeline.process_output(final_result)
         → (msg_type, message)
                    │
                    ▼
  bot.send_long(ctx, message)
         → Discord reply to user
```

### Flow 2: Scheduled review check (every 15 minutes)

```
  scheduler._loop()
         │
         ▼ (every REVIEW_CHECK_INTERVAL_MINUTES)
  pipeline.handle_review_check()               ← sync, direct DB
         │
         ├── db.get_due_concepts(limit=5)
         ├── db.get_concept_detail(concept_id)
         └── return ["id|context_string", ...]   (or [] if nothing due)
                    │
                    ▼
  scheduler._send_review_quiz(payload)
         │
         ▼
  pipeline.call_with_fetch_loop(               ← async, calls kimi-cli
      mode="reply",
      text="[SCHEDULED_REVIEW] Generate a review quiz for: <payload>",
      author=user_id
  )
         │
         ▼
  DM user: "📚 Learning Review\n<quiz question>"
```

### Flow 3: Scheduled maintenance (every 24 hours)

```
  scheduler._loop()
         │
         ▼ (every MAINTENANCE_INTERVAL_HOURS)
  pipeline.handle_maintenance()                ← sync, direct DB
         │
         ├── context.build_maintenance_context()
         │       ├── db.get_maintenance_diagnostics()
         │       ├── db.get_review_stats()
         │       └── db.get_hierarchical_topic_map()
         │
         └── return diagnostic_context (or None if healthy)
                    │
                    ▼
  scheduler._send_maintenance_report(context)
         │
         ├── pipeline.call_with_fetch_loop(    ← LLM triages issues
         │       "[MAINTENANCE] Triage these DB issues..."
         │   )
         │
         ├── pipeline.execute_llm_response(    ← LLM may fix something
         │       llm_response
         │   )
         │
         └── DM user: "🔧 Knowledge Base Maintenance\n<report>"
```

### Flow 4: Web UI (read-only)

```
  Browser → http://localhost:8050
         │
         ▼
  webui/server.py: BaseHTTPRequestHandler
         │
         ├── /static/*      → Serves CSS/JS from webui/static/
         ├── /              → Dashboard (stats, due concepts, topic tree)
         ├── /topics        → Interactive topic tree (expand/collapse, search, subtree stats)
         ├── /topic/<id>    → Topic detail + breadcrumb + child cards + concept table
         ├── /concept/<id>  → Concept detail + remarks + review log
         ├── /concepts      → All concepts sorted by next review
         ├── /reviews       → Recent review history
         ├── /api/stats     → JSON: review stats
         ├── /api/topics    → JSON: full topic map
         └── /api/due       → JSON: due concepts
         │
         └── All read directly from db.py
             (no pipeline, no LLM — pure DB ➜ HTML)
```

---

## Database Schema

### knowledge.db

```
topics
  ├── id (PK)
  ├── title
  ├── description
  ├── created_at
  └── updated_at

topic_relations (DAG — topics can have multiple parents)
  ├── parent_id → topics.id
  ├── child_id  → topics.id
  └── created_at

concepts
  ├── id (PK)
  ├── title
  ├── description
  ├── mastery_level    (0–5, SM-2)
  ├── ease_factor      (float, SM-2, default 2.5)
  ├── interval_days    (SM-2 review interval)
  ├── next_review_at   (ISO datetime)
  ├── last_reviewed_at
  ├── review_count
  ├── created_at
  └── updated_at

concept_topics (many-to-many — concepts can belong to multiple topics)
  ├── concept_id → concepts.id
  └── topic_id   → topics.id

concept_remarks (LLM's persistent memory per concept)
  ├── id (PK)
  ├── concept_id → concepts.id
  ├── content       ← strategy notes, user observations, next-quiz plans
  └── created_at

review_log (audit trail of every quiz interaction)
  ├── id (PK)
  ├── concept_id → concepts.id
  ├── question_asked
  ├── user_response
  ├── quality        (0–5, SM-2)
  ├── llm_assessment
  └── reviewed_at
```

### chat_history.db

```
conversations
  ├── id (PK)
  ├── session_id  (always 'learn')
  ├── role        ('user' | 'assistant')
  ├── content
  └── created_at
```

---

## Module Responsibilities

### bot.py — Discord Interface
- Creates the Discord bot with `commands.Bot`
- Registers `/learn`, `/due`, `/topics`, `/review`, `/clear`, `/ping`, `/sync` hybrid commands (also work as `!` prefix)
- Fast-path commands (`/due`, `/topics`, `/clear`) read DB directly — no LLM call
- Routes **every** plain message from the authorized user through the learning pipeline
- Handles message chunking for Discord's 2000-char limit
- Single authorized user (config.AUTHORIZED_USER_ID)
- Tracks `last_activity_at` for session awareness
- Starts the scheduler on `on_ready`

### context.py — Prompt Construction
| Function | Purpose |
|:---------|:--------|
| `build_lightweight_context(mode)` | Assembles conditional context based on mode: COMMAND/REPLY get full context (topic map, due, stats, chat); REVIEW-CHECK gets only due concepts; MAINTENANCE returns empty. Skips all sections when DB is empty. |
| `build_prompt_context(text, mode)` | Wraps lightweight context + mode declaration. Note: user message is NOT included (pipeline appends it separately to avoid duplication). |
| `build_full_prompt(text, mode)` | Includes AGENTS.md + preferences.md content inline. Used by the CLI for standalone testing. |
| `format_fetch_result(data)` | Formats fetch data (topic/concept/search) into markdown. Caps concept remarks to 3, truncates review text to 200 chars. |
| `build_maintenance_context()` | Runs `db.get_maintenance_diagnostics()` and formats the diagnostic report. |

### tools.py — Action Executor
- Maps 17 action verbs to database operations via `ACTION_HANDLERS` dict
- Each handler receives `params` dict, returns `(msg_type, result)` tuple
- Pure CRUD — no LLM logic, no prompt building

| Action | Handler | DB Operation |
|:-------|:--------|:-------------|
| `fetch` | `_handle_fetch` | Read topic/concept/search/due/stats |
| `add_topic` | `_handle_add_topic` | `db.add_topic()` |
| `update_topic` | `_handle_update_topic` | `db.update_topic()` |
| `delete_topic` | `_handle_delete_topic` | `db.delete_topic()` |
| `link_topics` | `_handle_link_topics` | `db.link_topics()` |
| `list_topics` | `_handle_list_topics` | `db.get_hierarchical_topic_map()` |
| `add_concept` | `_handle_add_concept` | `db.add_concept()` + optional remark |
| `update_concept` | `_handle_update_concept` | `db.update_concept()` |
| `delete_concept` | `_handle_delete_concept` | `db.delete_concept()` |
| `link_concept` | `_handle_link_concept` | `db.link_concept_to_topics()` |
| `unlink_concept` | `_handle_unlink_concept` | `db.unlink_concept_from_topic()` |
| `remark` | `_handle_remark` | `db.add_remark()` |
| `quiz` | `_handle_quiz` | Passthrough (question is in `message`) |
| `assess` | `_handle_assess` | `db.add_review()` + SM-2 update |
| `suggest_topic` | `_handle_suggest_topic` | Formats suggestion (no DB write) |
| `none` / `reply` | `_handle_none` | Passthrough |

### services/pipeline.py — Orchestrator
The core brain of the system. Coordinates everything:

1. **`call_with_fetch_loop(mode, text, author)`** — Main entry point. Builds context, calls kimi-cli, handles fetch loop (up to 3 iterations), returns final LLM response string.
2. **`execute_llm_response(user_input, llm_response, mode)`** — Parses the LLM response, executes any action, saves chat history. Returns prefixed result string.
3. **`_call_kimi(mode, text, author, extra_context)`** — Assembles the prompt (file refs + dynamic context), calls `kimi.run_kimi()`, extracts the action from raw output.
4. **`handle_review_check()`** — Direct DB read for due concepts. Returns formatted review payload strings.
5. **`handle_maintenance()`** — Direct DB diagnostics. Returns context string or None.
6. **Parsing utilities** — `parse_llm_response()`, `extract_llm_action()`, `process_output()`.

### services/kimi.py — LLM Subprocess (the only one)
- Wraps `kimi-cli` as a subprocess via `asyncio.to_thread(subprocess.run, ...)`
- Handles encoding (UTF-8), timeout, stderr filtering
- This is the **single point** where the system crosses a process boundary

### services/scheduler.py — Background Tasks
- Starts as a `bot.loop.create_task` on bot ready
- Review check: every 15 minutes (configurable), calls `pipeline.handle_review_check()` → sends quiz DMs
- **Suppresses reviews** when user has been active within `SESSION_TIMEOUT_MINUTES` to avoid interrupting conversations
- Maintenance: every 24 hours, calls `pipeline.handle_maintenance()` → LLM triages issues → sends report DM

### agent.py — CLI (not used by bot)
- Standalone entry point for testing: `python agent.py --mode=command --input="quiz me"`
- Supports `--context-only`, `--fetch`, `--mode=review-check`, `--mode=maintenance`
- Imports from `context.py` and `tools.py` (same modules the bot uses)
- **Not called by the bot** — pipeline.py calls the modules directly

### webui/ — Web Dashboard
- Zero-dependency HTTP server on port 8050 (`webui/server.py`)
- Static file serving for extracted CSS and JS (`webui/static/`)
- Interactive topic tree with expand/collapse, search/filter, and subtree stats
- Topic detail pages with breadcrumb navigation and child topic cards
- Computes aggregated subtree stats (own + total concepts) via post-order DFS
- Imports `db.py` directly — completely independent of the bot/pipeline

---

## The Fetch Loop

The fetch loop is the mechanism that allows the LLM to "look before it leaps." On any given turn, the LLM receives only a lightweight context (root topics + 5 due concepts). If it needs more detail, it responds with a `fetch` action instead of a final answer.

```
Turn 1: User says "quiz me on stainless steel"
  → LLM sees: topic #7 "Stainless Steel" in Knowledge Map
  → LLM responds: fetch { topic_id: 7 }
  → Pipeline executes fetch → gets concept list
  → Appends formatted result to context

Turn 2: (automatic, same user turn)
  → LLM now sees all concepts under topic #7
  → LLM responds: fetch { concept_id: 12 }
  → Pipeline executes fetch → gets full concept detail + remarks + reviews
  → Appends to context

Turn 3: (automatic, same user turn)
  → LLM now has everything it needs
  → LLM responds: quiz { concept_id: 12, message: "In a coastal plant, why choose 316L over 304?" }
  → Pipeline returns this as the final response
```

**Max 3 fetch iterations per user message.** The user only sees the final response — the fetch loop is invisible.

---

## LLM Response Format

The LLM must respond in exactly one of these formats (enforced by AGENTS.md):

| Format | Example | Pipeline Handling |
|:-------|:--------|:------------------|
| **JSON action** | `{"action":"add_concept","params":{...},"message":"Added X"}` | → `tools.execute_action()` → DB write → user sees `message` |
| **Fetch action** | `{"action":"fetch","params":{"topic_id":3}}` | → Fetch loop re-calls LLM with enriched context |
| **REPLY:** | `REPLY: Stainless steel resists rust because...` | → Passthrough to user |
| **ASK:** | `ASK: Which topic did you mean?` | → Passthrough to user |
| **REVIEW:** | `REVIEW: Time to test... 🧠 <question>` | → Passthrough (used in scheduler DMs) |

---

## Spaced Repetition (SM-2)

The SM-2 algorithm is implemented as a collaboration between the LLM and the database:

- **LLM decides** the quality score (0–5) based on the user's answer, guided by the SM-2 rubric in AGENTS.md
- **LLM calculates** new `ease_factor` and `interval_days` per the rubric
- **LLM outputs** an `assess` action with `quality`, `new_ease_factor`, `new_interval_days`
- **tools.py** writes the review log and updates the concept's scheduling fields via `db.add_review()`
- **db.py** handles the actual SQL update + sets `next_review_at`

Initial values for new concepts: mastery=0, ease=2.5, interval=1 day.

---

## Remarks: The LLM's Persistent Memory

Remarks (`concept_remarks` table) are the key mechanism that makes the system adaptive without hardcoded logic. The LLM:

1. **Writes** a remark after every assessment: what the user got right/wrong, what question type worked, what to try next
2. **Reads** its own past remarks before generating the next quiz question (via fetch)
3. **Plans ahead**: "Next time try synthesis questions" / "User struggles with the chemistry aspect"

This creates a self-improving loop entirely through prompt instructions — no code changes needed to evolve quiz strategy.

---

## Configuration Summary

| Setting | Default | Source |
|:--------|:--------|:-------|
| Bot token | env `LEARN_BOT_TOKEN` | config.py |
| Authorized user | env `LEARN_AUTHORIZED_USER_ID` | config.py |
| kimi-cli path | `"kimi"` | config.py |
| LLM timeout | 120 seconds | config.py |
| Review check interval | 15 minutes | config.py |
| Maintenance interval | 24 hours | config.py |
| Max fetch iterations | 3 | pipeline.py |
| Chat history in context | 12 messages | context.py |
| Max Discord message | 1900 chars | config.py |
| Web UI port | 8050 | webui/server.py |
| Static assets | `webui/static/` | webui/server.py |
| Data directory | `learning_agent/data/` | db.py |
