# Learning Agent — Architecture Documentation

> Last updated: 2026-04-04

## Overview

The Learning Agent is a Discord-based spaced repetition system where **all learning intelligence lives in modular runtime skill files** under `data/skills/`, not in code. The codebase provides thin CRUD plumbing and a pipeline that shuttles messages between user ↔ LLM ↔ database.

**Entry points:**
- `bot.py` is a thin wrapper that starts the Discord bot
- `bot/` contains the actual Discord bot logic (`app.py`, `handler.py`, `commands.py`, `events.py`, `messages.py`)
- `api.py` is a thin wrapper for the FastAPI app defined in `api/app.py`
- `api/routes/` contains the REST route modules registered by `api/app.py`

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
│      │         │  │   llm.py     │               │                    │
│      │         │  │ (providers)  │               │                    │
│      │         │  └──────┬───────┘               │                    │
│      │         │         │                       │                    │
│      │         │         ▼                       │                    │
│      │         │  ┌──────────────┐               │                    │
│      │         │  │ kimi CLI or  │               │                    │
│      │         │  │ OpenAI compat│               │                    │
│      │         │  │ backend      │               │                    │
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
│   │  core.py · migrations.py · topics.py · concepts.py │             │
│   │  reviews.py · chat.py · diagnostics.py             │             │
│   └──────────┬────────────────────────┬────────────────┘             │
│              ▼                        ▼                              │
│   ┌──────────────────┐   ┌───────────────────┐  ┌────────────────┐  │
│   │  knowledge.db    │   │  chat_history.db   │  │  Qdrant        │  │
│   │  (topics,        │   │  (conversations,   │  │  (embedded)    │  │
│   │   concepts,      │   │   session state)   │  │  data/vectors/ │  │
│   │   reviews,       │   │                    │  │  768-dim       │  │
│   │   remarks)       │   │                    │  │  embeddings    │  │
│   └──────────────────┘   └───────────────────┘  └────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

**LLM provider note:** the system prompt is assembled from `data/skills/*.md`, the active persona, and `data/preferences.md`. With `LLM_PROVIDER="openai_compat"`, that assembled prompt is sent directly in the API request. With `LLM_PROVIDER="kimi"`, the provider prepends file references for `AGENTS.md`, the active persona file, and `data/preferences.md` before invoking the CLI.

---

## File Map

| File | Lines | Role |
|:-----|------:|:-----|
| `AGENTS.md` | ~25 | Pointer file — references `data/skills/` for modular skill loading (see `docs/index.md`) |
| `data/skills/core.md` | ~155 | Core skill — role, philosophy, response format, universal actions, rules (loaded for all modes) |
| `data/skills/quiz.md` | ~200 | Quiz skill — quiz/assess actions, scoring rubric, adaptive quiz evolution (interactive + review) |
| `data/skills/knowledge.md` | ~170 | Knowledge skill — topic/concept CRUD, casual Q&A, overlap detection (interactive + maintenance) |
| `data/skills/maintenance.md` | ~50 | Maintenance skill — triage rules, safe/unsafe actions, priority order (maintenance only) |
| `data/skills/taxonomy.md` | ~80 | Taxonomy skill — topic tree restructuring, grouping rules, rename criteria, suppressed-rename tracking (taxonomy mode only) |
| `data/skills/quiz_generator.md` | ~80 | P1 quiz generation — question type/difficulty selection, JSON output format (scheduled quiz P1 only) |
| `data/preferences.md` | ~20 | User learning preferences (interests, style) |
| `bot.py` | ~62 | Thin Discord bot entry point wrapper |
| `bot/app.py` | ~40 | Bot client setup and shared application instance |
| `bot/handler.py` | ~110 | Core message handler — orchestrates pipeline calls and returns `(response, pending_action, assess_meta, quiz_meta)` |
| `bot/commands.py` | ~435 | Slash command implementations (`/learn`, `/review`, `/maintain`, `/backup`, `/reorganize`, etc.) |
| `bot/events.py` | ~220 | Discord event handlers (`on_message`, startup hooks, command errors) |
| `bot/messages.py` | ~40 | Message splitting and view attachment helpers |
| `config.py` | ~80 | Tokens, paths, timeouts, intervals |
| `services/context.py` | ~640 | Prompt/context construction — builds the dynamic context injected into every LLM call |
| `services/tools.py` | ~550 | Action executor — maps LLM verbs → DB calls; quiz/assess handlers extracted to `tools_assess.py` |
| `services/tools_assess.py` | ~360 | Assessment and quiz action handlers (`_handle_quiz`, `_handle_assess`, etc.) extracted from `tools.py` |
| `services/formatting.py` | ~80 | Discord message formatting — `truncate_for_discord`, `truncate_with_suffix`, `format_quiz_metadata` |
| `db/` | ~2715 | Database package — see submodules below |
| `scripts/agent.py` | ~310 | CLI entry point for standalone testing (not used by the bot at runtime) |
| `webui/server.py` | ~220 | Zero-dependency HTTP server — routing, Handler class, static file serving, forecast routes |
| `webui/helpers.py` | ~145 | HTML helpers (`score_bar`, `layout`, `_esc`, etc.) extracted from `server.py` |
| **webui/pages/** | | Page renderers split into package modules (~950 total lines) |
| `webui/pages/__init__.py` | ~25 | Re-exports all 10 page functions |
| `webui/pages/dashboard.py` | ~190 | `page_dashboard`, `compute_subtree_stats`, `render_tree_node` |
| `webui/pages/topics.py` | ~160 | `page_topics`, `page_topic_detail`, `build_breadcrumb` |
| `webui/pages/concepts.py` | ~230 | `page_concepts`, `page_concept_detail` |
| `webui/pages/reviews.py` | ~70 | `page_reviews`, `page_404`, `page_forecast` |
| `webui/pages/activity.py` | ~200 | `page_actions` |
| `webui/pages/graph.py` | ~75 | `page_graph` |
| `webui/static/style.css` | ~170 | Extracted CSS — dark theme, tree components, responsive layout |
| `webui/static/tree.js` | ~150 | Vanilla JS — expand/collapse, search/filter, state persistence |
| `webui/static/forecast.js` | ~245 | D3 v7 bar chart — bucketed review forecast with drill-down |
| **db/ package** | | |
| `db/core.py` | ~230 | Connection helpers, `init_databases()`, datetime utils |
| `db/migrations.py` | ~265 | Schema migration blocks extracted from `core.py` |
| `db/topics.py` | ~240 | Topic CRUD, topic maps, hierarchical maps |
| `db/concepts.py` | ~555 | Concept CRUD, search, detail view, forecast bucket queries |
| `db/reviews.py` | ~100 | Review log, remarks |
| `db/chat.py` | ~105 | Chat history, session state |
| `db/diagnostics.py` | ~140 | Maintenance diagnostics, title similarity; vector nearest-neighbor for relation candidates |
| `db/vectors.py` | ~210 | Qdrant wrapper — upsert/delete/search for concepts+topics, `find_nearest_concepts`, `reindex_all`, `close_client` |
| `db/__init__.py` | ~120 | Re-exports all public functions; `VECTORS_AVAILABLE` flag for graceful degradation |
| **services/** | | |
| `services/pipeline.py` | ~675 | Core orchestrator — skill loading, context → LLM → parse → execute, with fetch loop + session isolation |
| `services/llm.py` | ~330 | LLM provider abstraction — kimi CLI integration and OpenAI-compatible chat-completions adapter |
| `services/parser.py` | ~180 | LLM response parsing — `parse_llm_response`, `process_output`, `extract_llm_action` |
| `services/repair.py` | ~90 | Action-name repair sub-agent (ephemeral kimi session) |
| `services/dedup.py` | ~140 | Dedup check and merge execution |
| `services/kimi.py` | ~83 | Thin subprocess wrapper around kimi-cli (the only subprocess in the system) |
| `services/backup.py` | ~185 | Backup service — SQLite online-backup + Qdrant copytree snapshots; `perform_backup`, `prune_old_backups`, `run_backup_cycle` |
| `services/scheduler.py` | ~520 | Background task — review checks every 15 min, maintenance/taxonomy/dedup/backup every 168 h (weekly) |
| `services/state.py` | ~10 | Shared mutable state (e.g. `last_activity_at`) between bot and scheduler |
| `services/embeddings.py` | ~80 | Embedding service — lazy-loaded `all-mpnet-base-v2` singleton, `embed_text`, `embed_batch` |
| `scripts/migrate_vectors.py` | ~90 | Bulk reindex script — reads all SQLite concepts/topics, writes into Qdrant |
| `scripts/test_similarity.py` | ~200 | Interactive similarity test harness — configurable concept pairs with scored output |
| **tests/** | | |
| `tests/test_maintenance.py` | ~160 | Test maintenance diagnostics and dedup sub-agent |
| `tests/test_dedup.py` | ~35 | Quick test for title similarity and duplicate detection |

---

## Core Design Principle: LLM-First

The LLM (via the assembled runtime skill prompt) makes **all** decisions:
- What to teach, when to quiz, how to adapt difficulty
- Whether to create topics/concepts from casual conversation
- How to assess answers (score-based, 0–100)
- When to restructure the knowledge graph (merge topics, split oversized ones)
- What remarks to write for its own future self

The code is intentionally "dumb" — it provides CRUD primitives and a pipeline, nothing more. To change runtime behavior, **edit `data/skills/*.md`**, not the root `AGENTS.md` pointer file.

---

## Interaction Flows

### Flow 1: User sends a Discord message

```
  User types in Discord
         │
         ▼
    bot/events.py:on_message or bot/commands.py:/learn
         │
         ▼
    bot/handler.py:_handle_user_message(text, author)
         │  returns tuple[str, dict|None, dict|None, dict|None]
         │  (response, pending_action, assess_meta, quiz_meta)
         ▼
  pipeline.call_with_fetch_loop("command", text, author)     ← async
         │
         ├─── context.build_prompt_context(text, "command")  ← direct call
         │         │
         │         ├── db.get_hierarchical_topic_map()
         │         ├── db.get_due_concepts(limit=5)
         │         ├── db.get_review_stats()
         │         ├── _append_active_concept_detail()  (auto-includes if active_concept_id set)
         │         ├── _append_chat_history()  (session-based continuation: skip entirely)
         │         └── _append_active_quiz_context()  (auto-clears if stale > 15min)
         │
         ├─── If mode not MAINTENANCE/REVIEW-CHECK:
         │         └── _preload_mentioned_concept()  (exact title match → concept detail + relations)
         │
         ├─── Assemble prompt:
         │      build_system_prompt(mode)
         │      → loads data/skills/* + active persona + preferences.md
         │      + dynamic context (topics, due, chat history)
         │      + "User said: <text>"
         │
         ├─── llm_provider.send(prompt, system_prompt)       ← provider abstraction
         │         │
         │         ├── openai_compat: sends assembled prompt directly in API messages
         │         └── kimi: prepends file refs (AGENTS.md + persona + preferences)
         │             before invoking the CLI subprocess
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
         │           → if action in ('assess','multi_assess') and not is_quiz_active():
         │               short-circuit → return "REPLY: (assessment skipped -- no active quiz)"
         │           → tools.execute_action(action, params)
         │               → db.<crud_operation>(...)
         │           → if action in _QUIZ_CLEARING_ACTIONS: clear quiz context
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
  ┌─ Two-prompt pipeline (with fallback) ──────────────────────┐
  │                                                            │
  │  P1: pipeline.generate_quiz_question(concept_id)           │
  │    Provider: REASONING_LLM_* (or main provider fallback)   │
  │    System prompt: data/skills/quiz_generator.md             │
  │    Input: concept detail + related concepts                │
  │    Output: JSON {question, difficulty, question_type,      │
  │             target_facet, reasoning, concept_ids}           │
  │    Cached in: concepts.last_quiz_generator_output          │
  │                       │                                    │
  │                       ▼                                    │
  │  P2: pipeline.package_quiz_for_discord(p1_result, cid)     │
  │    Provider: main LLM provider                             │
  │    Skill set: "quiz-packaging" (core + quiz)               │
  │    Input: P1 JSON + concept context                        │
  │    Output: quiz action with persona voice                  │
  │                                                            │
  │  Fallback: If P1 fails → pipeline.call_with_fetch_loop()   │
  │            (single-prompt, same as before)                  │
  └────────────────────────────────────────────────────────────┘
         │
         ▼
  DM user: "📚 Learning Review\n<quiz question>"
```

### Flow 3: Scheduled maintenance & taxonomy (every 168 hours / weekly)

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

```
  (same weekly cycle, after maintenance)
         │
         ▼
  scheduler._check_taxonomy()         ← taxonomy reorganization agent
         │
         ├── pipeline.handle_taxonomy()
         │       └── context.build_taxonomy_context()
         │               ├── db.get_topic_map()
         │               ├── db.get_review_stats()
         │               └── db.get_rejected_renames(days=90)
         │
         └── pipeline.call_taxonomy_loop(context)  ← LLM restructures topic tree
                    │
                    └── DM user: "🌿 Taxonomy Reorganization\n<proposals>"

  (same weekly cycle, after taxonomy)
         │
         ▼
  scheduler._check_dedup()           ← dedup sub-agent; proposes merges via DM

         │
         ▼ (after dedup — captures post-maintenance DB state)
  scheduler._check_backup()
         │
         └── backup_service.run_backup_cycle()   ← in thread executor
               ├── perform_backup()  → backups/TIMESTAMP_microseconds/
               │       ├── knowledge.db  (sqlite3.Connection.backup)
               │       ├── chat_history.db
               │       └── vectors/      (shutil.copytree; Qdrant client closed first)
               └── prune_old_backups()  → deletes dirs > BACKUP_RETENTION_DAYS

         │
         ▼
  db.cleanup_expired_proposals()
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
  ├── mastery_level    (0–100, score-based)
  ├── ease_factor      (float, frozen — not used)
  ├── interval_days    (exponential: e^(score×0.05))
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
  ├── quality        (0–5, LLM-assessed)
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
| `build_lightweight_context(mode, is_new_session)` | Assembles conditional context based on mode: COMMAND/REPLY get full context (topic map, due concepts with relation lines, stats, active concept detail, chat history); REVIEW-CHECK gets only due concepts; MAINTENANCE returns empty. Skips all sections when DB is empty. |
| `build_prompt_context(text, mode, is_new_session)` | Wraps lightweight context + mode declaration + concept pre-fetch. For non-maintenance/non-review-check modes, calls `_preload_mentioned_concept()` to auto-include concept detail when user message exactly matches a concept title. Note: user message is NOT included (pipeline appends it separately to avoid duplication). |
| `_append_chat_history(parts, is_new_session)` | Includes recent chat history. For session-based providers (OpenAI-compat), skips entirely on continuation turns (`is_new_session=False`) since the provider already accumulates messages. New sessions and stateless providers always get history. |
| `_append_active_concept_detail(parts)` | When `active_concept_id` is set and not stale, auto-includes full concept detail (description, score, remark, recent reviews, relations). Eliminates a fetch round-trip. |
| `_append_active_quiz_context(parts)` | Injects active quiz/multi-quiz context with relation lines per concept. Auto-clears if stale > 15min. |
| `_preload_mentioned_concept(user_message)` | Exact case-insensitive title match. Returns formatted concept detail + relations. Guarded by topic relevance filter (skips if matched concept is in a different topic than the active concept). Max 200 char messages only. |
| `_is_quiz_stale()` | Shared helper: checks if `active_concept_id` was last updated more than `QUIZ_STALENESS_TIMEOUT_MINUTES` ago. |
| `_format_relations_snippet(concept_id, max_rels)` | Shared helper: formats top N relation lines as `↳ relation_type #id title (score, "note")`. Used by due concepts, quiz context, active concept detail, and quiz generator. |
| `format_fetch_result(data)` | Formats fetch data (topic/concept/search) into markdown. Caps concept remarks to 3, truncates review text to 200 chars. |
| `build_maintenance_context()` | Runs `db.get_maintenance_diagnostics()` and formats the diagnostic report. |
| `build_taxonomy_context()` | Builds topic tree context for the taxonomy agent. Calls `db.get_topic_map()`, `db.get_review_stats()`, and `db.get_rejected_renames(days=90)` to include suppressed renames. |
| `build_quiz_generator_context(concept_id)` | Builds pre-loaded context for P1 quiz generation. Includes concept detail + enriched related concepts (descriptions, remarks, review Q&As). |

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
| `assess` | `_handle_assess` | `db.add_review()` + score update |
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
7. **`is_quiz_active()`** — Authoritative quiz-state check. Returns `True` when either `quiz_anchor_concept_id` (single-quiz) or `active_concept_ids` (multi-quiz) is set in session. Used as a guard in `execute_action` to block stale `assess`/`multi_assess` calls.
8. **`execute_action` assess guard** — Before dispatching `assess` or `multi_assess`, `execute_action` calls `is_quiz_active()`. If no quiz is active the action is short-circuited: scores and logs are **not** mutated and `REPLY: (assessment skipped -- no active quiz)` is returned. This guard is enforced identically in `scripts/agent.py`.
9. **`call_action_loop(mode, safe_actions, max_actions, context, preamble)`** — Generic LLM action loop shared by maintenance and taxonomy modes. Iterates up to `max_actions` rounds; auto-executes safe actions, collects unsafe actions as proposals. Returns `(final_result_str, proposed_actions_list)`.
10. **`call_maintenance_loop(diagnostic_context)`** — Thin wrapper around `call_action_loop()` for maintenance mode: uses `SAFE_MAINTENANCE_ACTIONS` and `MAX_MAINTENANCE_ACTIONS = 5`.
11. **`call_taxonomy_loop(taxonomy_context)`** — Thin wrapper around `call_action_loop()` for taxonomy mode (`"taxonomy-mode"` skill set): uses `SAFE_TAXONOMY_ACTIONS` and `MAX_TAXONOMY_ACTIONS = 15`.
12. **`handle_taxonomy()`** — Entry point called by `scheduler._check_taxonomy()` and `/reorganize`. Returns taxonomy context string, or `None` if no topics exist.

### services/kimi.py — LLM Subprocess (the only one)
- Wraps `kimi-cli` as a subprocess via `asyncio.to_thread(subprocess.run, ...)`
- Handles encoding (UTF-8), timeout, stderr filtering
- This is the **single point** where the system crosses a process boundary

### services/scheduler.py — Background Tasks
- Starts as a `bot.loop.create_task` on bot ready
- Review check: every 15 minutes (configurable), calls `pipeline.handle_review_check()` → sends quiz DMs
- **Suppresses reviews** when user has been active within `SESSION_TIMEOUT_MINUTES` to avoid interrupting conversations
- Maintenance: every 168 hours (weekly), calls `pipeline.handle_maintenance()` → LLM triages issues → sends report DM
- Taxonomy: every 168 hours (same weekly cycle, after maintenance), calls `pipeline.handle_taxonomy()` → LLM restructures topic tree → sends report DM
- Backup: every 168 hours (same weekly cycle, after dedup), calls `backup_service.run_backup_cycle()` via thread executor — runs after dedup, before proposal cleanup

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

## Spaced Repetition (Score-Based)

Replaced SM-2 with an asymmetric score system (0–100). See DEVNOTES.md §3 for full details.

- **LLM decides** quality (0–5) and `question_difficulty` (0–100)
- **Code calculates** score delta based on gap (difficulty − current score) with asymmetric rules:
  - Correct: score increases (bigger gain for harder questions)
  - Wrong + above level: no penalty (probe)
  - Wrong + at/below level: proportional decrease
- **`tools.py`** writes the review log and updates score/interval via `db.add_review()`
- **Interval:** `max(1, round(e^(score × 0.05)))` — exponential spacing

Initial values for new concepts: score=0, interval=1 day. `ease_factor` column frozen (not used).

---

## Semantic Search & Vector Store

### What it is

A **hybrid search layer** sitting alongside SQLite. It is *not* RAG in the classical sense — no document chunks are retrieved and injected into the LLM prompt. Instead, vector similarity is used to:

1. **Improve search** — `search_concepts(q)` and `search_topics(q)` use semantic matching instead of keyword matching
2. **Find relation candidates** — `_get_relationship_candidates()` uses nearest-neighbor instead of string similarity
3. **Group related concepts for multi-quiz** — `fetch cluster` fetches semantically similar concepts to form a synthesis quiz

### Architecture

```
User adds/updates concept
        │
        ▼
  SQLite (source of truth)          ← always written first
        │
        ▼ (best-effort, non-fatal)
  services/embeddings.py
  embed_text(title + " — " + description)
        │
        ▼
  768-dim float vector
        │
        ▼
  db/vectors.py  →  Qdrant (embedded, data/vectors/)
                    collections: "concepts", "topics"
```

### Sync hooks

Each CRUD function in `db/concepts.py` and `db/topics.py` calls a `_vector_upsert()` or `_vector_delete()` helper **after** the SQL write. All vector calls are wrapped in `try/except` — if Qdrant or the embedding model fails, the SQL operation still succeeds.

### Search flow

```
search_concepts(query)
    │
    ├─ try: vector similarity search (Qdrant)
    │       → get top-N concept IDs by cosine similarity
    │       → fetch full rows from SQLite preserving similarity order
    │       → return
    │
    ├─ except: FTS5 keyword search (SQLite)
    │
    └─ except: LIKE fallback
```

### Multi-concept quiz flow

```
LLM issues: {"action": "fetch", "params": {"cluster": true, "concept_id": 12}}
        │
        ▼
  _handle_fetch_cluster()
  → get primary concept from SQLite
  → find_nearest_concepts(12, limit=6, score_threshold=0.4)
  → bias toward due concepts
  → return concept_cluster list
        │
        ▼
  LLM reads cluster, generates synthesis question spanning all concepts
        │
        ▼
  {"action": "multi_quiz", "params": {"concept_ids": [12, 7, 3], ...}}
  → stores active_concept_ids in session
        │
        ▼
  {"action": "multi_assess", "params": {"assessments": [{concept_id, quality}, ...]}}
  → scores each concept independently
  → updates mastery/schedule/reviews per concept
  → clears session state
```

### Similarity thresholds

| Threshold | Default | Config key | Purpose |
|:----------|:--------|:-----------|:--------|
| `SIMILARITY_THRESHOLD_DEDUP` | 0.92 | `LEARN_SIM_DEDUP` | Blocks near-duplicate concept adds |
| `SIMILARITY_THRESHOLD_RELATION` | 0.50 | `LEARN_SIM_RELATION` | Minimum score for relation candidate suggestions |
| Cluster search | 0.40 | hardcoded in `_handle_fetch_cluster` | Minimum score to include in a multi-quiz cluster |

Use `python scripts/test_similarity.py` to measure real scores for your concept pairs before tuning these.

### Graceful degradation

`db.VECTORS_AVAILABLE` is `True` only when `qdrant-client` is importable. If not installed:
- All search falls back to FTS5/LIKE
- `_get_relationship_candidates()` falls back to title string similarity
- Multi-quiz cluster falls back to explicit `concept_relations` edges
- All existing functionality is unaffected

### Migration

When first deploying with an existing SQLite database, run:
```bash
python scripts/migrate_vectors.py          # full reindex
python scripts/migrate_vectors.py --check  # count only
```
New concepts/topics are auto-synced on write; the migration script is only needed once for existing data.

---

## Remarks: The LLM's Persistent Memory

Remarks (`concept_remarks` table) are the key mechanism that makes the system adaptive without hardcoded logic. The LLM:

1. **Writes** a remark after every assessment: what the user got right/wrong, what question type worked, what to try next
2. **Reads** its own past remarks before generating the next quiz question (via fetch)
3. **Plans ahead**: "Next time try synthesis questions" / "User struggles with the chemistry aspect"

This creates a self-improving loop entirely through prompt instructions — no code changes needed to evolve quiz strategy.

---

## Backup Storage

Created at runtime under `config.BACKUP_DIR` (default: `<project root>/backups/`).
Each run of `services/backup.run_backup_cycle()` produces one timestamped subdirectory:

```
backups/
└── 2026-04-06_14-30-00_123456/
    ├── knowledge.db        # SQLite online-backup copy (sqlite3.Connection.backup())
    ├── chat_history.db     # SQLite online-backup copy
    └── vectors/            # shutil.copytree of data/vectors/ (Qdrant client closed first)
```

Directories older than `BACKUP_RETENTION_DAYS` (default: 7) are pruned automatically
after each run. The `backups/` directory is `.gitignore`d and never committed.

---

## Configuration Summary

| Setting | Default | Source |
|:--------|:--------|:-------|
| Bot token | env `LEARN_BOT_TOKEN` | config.py |
| Authorized user | env `LEARN_AUTHORIZED_USER_ID` | config.py |
| kimi-cli path | `"kimi"` | config.py |
| LLM timeout | 120 seconds | config.py |
| Review check interval | 15 minutes | config.py |
| Maintenance interval | 168 hours (weekly) | config.py |
| Max fetch iterations | 3 | pipeline.py |
| Chat history in context | 12 messages | context.py |
| Max Discord message | 1900 chars | config.py |
| Web UI port | 8050 | webui/server.py |
| Static assets | `webui/static/` | webui/server.py |
| Data directory | `learning_agent/data/` | db.py |
| Vector store path | `data/vectors/` | `LEARN_VECTOR_STORE_PATH` / config.py |
| Embedding model | `all-mpnet-base-v2` | `LEARN_EMBEDDING_MODEL` / config.py |
| Vector search limit | 10 | `LEARN_VECTOR_SEARCH_LIMIT` / config.py |
| Dedup similarity threshold | 0.92 | `LEARN_SIM_DEDUP` / config.py |
| Relation similarity threshold | 0.50 | `LEARN_SIM_RELATION` / config.py |
| Backup directory | `backups/` (repo root) | `LEARN_BACKUP_DIR` / config.py |
| Backup retention | 7 days | `LEARN_BACKUP_RETENTION_DAYS` / config.py |
