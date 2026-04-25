# Learning Agent — Architecture Documentation

> Last updated: 2026-04-25

## Overview

The Learning Agent is a Discord and web-based spaced repetition system where **all learning intelligence lives in modular runtime skill files** under `data/skills/`, not in code. The codebase provides thin CRUD plumbing and a pipeline that shuttles messages between user ↔ LLM ↔ database. Browser access is now centered on a React/TypeScript/Vite frontend under `frontend/`, organized around a nested `AppShell` with Dashboard, Chat, Knowledge, and Progress as the primary surfaces. FastAPI serves the built SPA through an HTML catch-all for non-reserved paths on port 8080, while the Vite dev server serves the same client-routed app on port 5173 during local development.

**Entry points:**
- `bot.py` is a thin wrapper that starts the Discord bot
- `bot/` contains the actual Discord bot logic (`app.py`, `handler.py`, `commands.py`, `events.py`, `messages.py`)
- `api.py` is a thin wrapper for the FastAPI app defined in `api/app.py`
- `api/routes/` contains the REST route modules registered by `api/app.py`

```
┌──────────────────────────────────────────────────────────────────────┐
│                         User Interfaces                              │
│   ┌──────────────┐              ┌──────────────────────────────┐    │
│   │  Discord Bot  │              │  Browser UI                  │    │
│   │  (bot.py)     │              │  (FastAPI + React / Vite)    │    │
│   └──────┬───────┘              └──────────────┬───────────────┘    │
│          │                                      │                    │
├──────────┼──────────────────────────────────────┼────────────────────┤
│          │ Pipeline Layer                       │                    │
│          ▼                                      ▼                    │
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
│      │         │  │ OpenAI compat│               │                    │
│      │         │  │ backend      │               │                    │
│      │         │  │ (main +      │               │                    │
│      │         │  │ reasoning)   │               │                    │
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
│   │                  db/ package                               │      │
│   │  core.py · migrations.py · topics.py · concepts.py        │      │
│   │  reviews.py · chat.py · diagnostics.py · relations.py     │      │
│   │  proposals.py · action_log.py · preferences.py            │      │
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

**LLM provider note:** the system prompt is assembled from `data/skills/*.md`, the active persona, and the runtime `data/preferences.md` file. That runtime file is git-ignored and auto-copied from tracked `data/preferences.template.md` on first bot startup. The runtime now uses OpenAI-compatible chat completions only, so the fully assembled prompt is sent directly in the API request.

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
| `data/skills/preferences.md` | ~30 | Preference-edit skill — isolated fenced-output editor used by `/preference` text edits |
| `data/skills/quiz_generator.md` | ~80 | P1 quiz generation — question type/difficulty selection plus structured JSON output including `formatted_question` (scheduled quiz P1 only) |
| `data/preferences.template.md` | ~30 | Tracked default preferences file copied to the runtime file on first bot startup |
| `data/preferences.md` | ~20 | Runtime user preferences copy (git-ignored, injected into every LLM call) |
| `bot.py` | ~62 | Thin Discord bot entry point wrapper |
| `bot/app.py` | ~40 | Bot client setup and shared application instance |
| `bot/auth.py` | ~20 | Authorization decorator that gates Discord commands to the configured user |
| `bot/handler.py` | ~110 | Core message handler — orchestrates pipeline calls and returns `(response, pending_action, assess_meta, quiz_meta)` |
| `bot/commands.py` | ~545 | Slash command implementations (`/learn`, `/review`, `/maintain`, `/backup`, `/reorganize`, `/preference`, etc.) |
| `bot/events.py` | ~220 | Discord event handlers (`on_message`, startup hooks, command errors) |
| `bot/messages.py` | ~40 | Message splitting and view attachment helpers |
| `api/app.py` | ~55 | FastAPI app assembly and route registration |
| `api/auth.py` | ~20 | Bearer-token dependency for REST endpoints; localhost requests on `API_PORT` bypass token checks; `/api/health` is always public |
| `api/schemas.py` | ~60 | Pydantic request and response models used by REST routes |
| `config.py` | ~80 | Tokens, paths, timeouts, intervals |
| `services/context.py` | ~640 | Prompt/context construction — builds the dynamic context injected into every LLM call |
| `services/tools.py` | ~550 | Action executor — maps LLM verbs → DB calls; quiz/assess handlers extracted to `tools_assess.py` |
| `services/tools_assess.py` | ~360 | Assessment and quiz action handlers (`_handle_quiz`, `_handle_assess`, etc.) extracted from `tools.py` |
| `services/formatting.py` | ~80 | Discord message formatting — `truncate_for_discord`, `truncate_with_suffix`, `format_quiz_metadata` |
| `services/chat_actions.py` | ~60 | Shared confirmation helpers and action whitelists used by the browser/API chat flows |
| `services/chat_session.py` | ~430 | Shared chat-session controller used by FastAPI chat routes and the React browser flow |
| `services/views.py` | ~560 | Persistent Discord UI views for confirmations, quiz navigation, skip buttons, and preference edits |
| `db/` | ~2715 | Database package — see submodules below |
| `scripts/agent.py` | ~310 | CLI entry point for standalone testing (not used by the bot at runtime) |
| `frontend/src/api.ts` | ~? | Typed frontend API client for JSON and SSE browser calls |
| `frontend/src/routes.tsx` | ~? | Route ownership for the React browser shell |
| `frontend/src/pages/` | | Route components for dashboard, chat, topics, concepts, graph, reviews, forecast, and activity |
| `frontend/src/components/` | | Shared React layout and UI components |
| `frontend/e2e/` | | Playwright smoke coverage for the browser UI |
| **db/ package** | | |
| `db/core.py` | ~230 | Connection helpers, `init_databases()`, datetime utils |
| `db/migrations.py` | ~265 | Schema migration blocks extracted from `core.py` |
| `db/topics.py` | ~240 | Topic CRUD, topic maps, hierarchical maps |
| `db/concepts.py` | ~555 | Concept CRUD, search, detail view, forecast bucket queries |
| `db/reviews.py` | ~100 | Review log, remarks |
| `db/chat.py` | ~105 | Chat history, session state |
| `db/diagnostics.py` | ~140 | Maintenance diagnostics, title similarity; vector nearest-neighbor for relation candidates |
| `db/relations.py` | ~110 | Concept relation CRUD and graph assembly helpers |
| `db/proposals.py` | ~95 | Pending proposal persistence for Discord confirmation views |
| `db/action_log.py` | ~150 | Action log reads/writes and rename-suppression support |
| `db/preferences.py` | ~55 | Active persona selection and available preset discovery |
| `db/vectors.py` | ~210 | Qdrant wrapper — upsert/delete/search for concepts+topics, `find_nearest_concepts`, `reindex_all`, `close_client` |
| `db/__init__.py` | ~120 | Re-exports all public functions; `VECTORS_AVAILABLE` flag for graceful degradation |
| **services/** | | |
| `services/pipeline.py` | ~1040 | Core orchestrator — skill loading, context → LLM → validate/retry → parse → execute, with fetch loop + session isolation; includes isolated `preference-edit` flow that bypasses normal conversation-history injection |
| `services/llm.py` | ~330 | LLM provider abstraction — owns the OpenAI-compatible chat-completions adapter, structured-output fallback when `response_format` is rejected, and reasoning-provider selection |
| `services/parser.py` | ~180 | LLM output boundary and presentation guard — `validate_llm_output`, `parse_llm_response`, `process_output`, `extract_llm_action`, `guard_user_message` |
| `services/action_contracts.py` | ~290 | Lightweight LLM action schema/validation — required params, param-type checks, action JSON schema for structured output mode |
| `services/repair.py` | ~90 | Action-name repair sub-agent (ephemeral isolated LLM session) |
| `services/dedup.py` | ~140 | Dedup check and merge execution |
| `services/backup.py` | ~185 | Backup service — SQLite online-backup + Qdrant copytree snapshots; `perform_backup`, `prune_old_backups`, `get_latest_backup_datetime`, `run_backup_cycle` |
| `services/scheduler.py` | ~520 | Persisted background scheduler — bot-owned reviews every 15 min plus shared taxonomy/backup/proposal-cleanup jobs with optional maintenance/dedup passes |
| `services/state.py` | ~65 | Process-local runtime coordination — shared pipeline lock helpers, `last_activity_at`, and ContextVar-based current-user identity |
| `services/embeddings.py` | ~80 | Embedding service — lazy-loaded `all-mpnet-base-v2` singleton, `embed_text`, `embed_batch` |
| `scripts/taxonomy_shadow_rebuild.py` | ~400 | Operator workflow — preview taxonomy rebuilds on shadow copies, replay safe actions on live data after backup, export before/after structure snapshots |
| `scripts/dev_all.py` | ~120 | Cross-platform dev launcher — starts `api.py`, `npm run dev` in `frontend/`, and `bot.py`; `--no-bot` and `--no-ui` flags |
| `scripts/migrate_vectors.py` | ~90 | Bulk reindex script — reads all SQLite concepts/topics, writes into Qdrant |
| `scripts/maintenance_smoke.py` | ~160 | Manual maintenance and dedup smoke script; intentionally kept outside automated pytest/CI runs |
| `scripts/live_output_contract_smoke.py` | ~280 | Manual real-provider smoke script for `.env`-backed output-contract validation and retry-path checks |
| `scripts/test_prompts.py` | ~180 | Prompt-debugging harness for maintenance, reorganize, and quiz prompt assembly |
| `scripts/test_quiz_generator.py` | ~120 | Manual test harness for the two-prompt quiz generation pipeline |
| `scripts/test_similarity.py` | ~200 | Interactive similarity test harness — configurable concept pairs with scored output |
| **tests/** | | |
| `tests/test_api.py` | ~1000 | Backend API/chat/auth coverage for REST routes and shared chat controller behavior |
| `tests/test_api_pages.py` | ~155 | FastAPI-served SPA alias and HTML-fallback coverage for browser routes |
| `tests/test_concept_dedup_tools.py` | ~235 | Tool- and DB-level concept dedup guard coverage |
| `tests/test_tools_topics.py` | ~75 | Topic handler guard coverage (`delete_topic`) |
| `tests/test_tools_relations.py` | ~40 | Relation handler coverage (`remove_relation`) |
| `tests/test_quiz_views.py` | ~310 | Discord quiz view delivery, navigation metadata, and skip-button regression coverage |
| `tests/test_topic_parent_heuristics.py` | ~165 | Topic auto-parenting and candidate-parent heuristic coverage |
| `tests/test_taxonomy_shadow_rebuild.py` | ~150 | Focused coverage for taxonomy shadow rebuild helpers, replay validation, and structure snapshot exports |
| **frontend/** | | |
| `frontend/src/routes.tsx` | — | React Router entry point — owns nested shell routes for `/`, `/chat`, `/knowledge`, `/knowledge/concepts`, `/knowledge/graph`, `/progress`, `/progress/forecast`, `/actions`, detail routes, and legacy redirects; `GraphPage` is lazy-loaded via `React.lazy` + `Suspense` |
| `frontend/src/App.tsx` | — | Compatibility re-export for the chat page plus `resolveBackendHref()` |
| `frontend/src/components/AppShell.tsx` | — | Router-owned shell wrapper — hosts the Activity drawer, Command palette, and routed content outlet |
| `frontend/src/components/AppLayout.tsx` | — | Presentational desktop shell — sidebar, header, badges, and bounded content regions |
| `frontend/src/components/ActivityDrawer.tsx` | — | Shell-owned Activity drawer used from the utility navigation flow |
| `frontend/src/components/CommandPalette.tsx` | — | `cmdk`-based shell command palette opened with `Ctrl+K` |
| `frontend/src/components/ui/*` | — | Local shadcn-style UI primitives used by the React app shell and migrated pages |
| `frontend/src/components/ui/resizable-panels.tsx` | — | Shared wrapper around `react-resizable-panels` used by the embedded Knowledge split layouts |
| `frontend/src/pages/*.tsx` | — | Migrated React pages: dashboard, activity compatibility page, chat, knowledge, progress, topic/concept detail, and supporting list/graph views |
| `frontend/src/pages/*.test.tsx` | — | Vitest + Testing Library coverage for the migrated React pages |
| `frontend/src/types.ts` | — | Shared TypeScript types for chat, topics, concepts, forecast, graph, reviews, and activity payloads |
| `frontend/src/api.ts` | — | Fetch helpers for chat plus dashboard, knowledge, progress, graph, review, and activity API bundles |
| `frontend/src/styles.css` | — | Tailwind layers plus shared app-level styles for the React SPA |
| `frontend/tailwind.config.ts` | — | Tailwind configuration for the React SPA |
| `frontend/components.json` | — | Local component metadata for the shadcn-style UI setup |
| `frontend/vite.config.ts` | — | Vite dev server on port 5173; proxies backend/static requests to FastAPI on 8080 |
| `frontend/playwright.config.ts` | — | Playwright preview-server config for Chromium browser smoke tests |
| `frontend/e2e/*.spec.ts` | — | Browser smoke tests for the built SPA against mocked `/api/*` responses |
| `frontend/package.json` | — | npm scripts (`dev`, `build`, `test`, `test:e2e`) and dependencies (React, TypeScript, Vite, Tailwind, Vitest, Testing Library, Playwright) |

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
         │      → loads data/skills/* + active persona + runtime preferences.md
         │      + dynamic context (topics, due, chat history)
         │      + "User said: <text>"
         │
         ├─── llm_provider.send(prompt, system_prompt, response_format)  ← provider abstraction
         │         │
         │         ├── openai_compat: sends assembled prompt directly in API messages
         │         └── if endpoint rejects response_format, retries once without it
         │
         ├─── parser.validate_llm_output(raw_output)
         │         ├── validates prefix/action envelope before execution/history/display
         │         └── invalid output → private log + clear contaminated session + one hidden retry
         │
         ├─── pipeline.extract_llm_action(validated_output)
         │         └── strips echoed prompt, finds last JSON or prefix
         │
         ├─── Is it a FETCH action? ─── YES ──┐
         │                                      │
         │    (up to 3 iterations)              ▼
         │                            tools.execute_action('fetch', params)
         │                                      │
         │                            context.format_fetch_result(data)
         │                                      │
         │                            append to extra_context, re-call provider ──┘
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

### Flow 2: Scheduled review check (every 15 minutes, bot-owned)

```
  scheduler._review_loop()
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
  ┌─ P1 generation + deterministic delivery (with fallback) ──┐
  │                                                            │
  │  P1: pipeline.generate_quiz_question(concept_id)           │
  │    Provider: REASONING_LLM_* (or main provider fallback)   │
  │    System prompt: quiz_generator.md + Active Persona +      │
  │                   runtime preferences.md                    │
  │    Input: concept detail + related concepts                │
  │    Output: JSON {question, formatted_question, difficulty, │
  │             question_type, target_facet, reasoning,        │
  │             concept_ids}                                   │
  │    Cached in: concepts.last_quiz_generator_output          │
  │                       │                                    │
  │                       ▼                                    │
  │  Delivery: pipeline.package_quiz_for_discord(p1_result)    │
  │    Deterministic compatibility wrapper                     │
  │    Input: P1 JSON                                          │
  │    Output: REPLY string using formatted_question           │
  │                                                            │
  │  Fallback: If P1 fails → pipeline.call_with_fetch_loop()   │
  │            mode="review-check" single-prompt flow          │
  └────────────────────────────────────────────────────────────┘
         │
         ▼
  DM user: "📚 Learning Review\n<quiz question>"
```

### Flow 3: Shared maintenance jobs (persisted wall-clock cadence)

```
    scheduler._shared_loop()
      │
      ▼ (owner lock acquired in either bot.py or api.py)
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
         ├── pipeline.call_maintenance_loop(context)
         │       └── pipeline.call_action_loop(
         │              mode="maintenance",
         │              safe_actions=SAFE_MAINTENANCE_ACTIONS,
         │              max_actions=5
         │          )
         │
         └── DM user: "🔧 Knowledge Base Maintenance\n<report>"
```

Maintenance runs only when `LEARN_ENABLE_MAINTENANCE=1`.

```
  (same scheduler, independent taxonomy cadence)
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

  (same scheduler, independent dedup cadence)
         │
         ▼
  scheduler._check_dedup()           ← dedup sub-agent; proposes merges via DM

Dedup runs only when `LEARN_ENABLE_DEDUP=1`.

         │
         ▼ (independent backup cadence)
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
  db.cleanup_expired_proposals()               ← default every 24h
```

### Flow 4: Browser UI (FastAPI + React)

FastAPI serves the built React SPA for any HTML request outside the reserved prefixes `/api`, `/assets`, and `/static` when `frontend/dist/index.html` exists. During local frontend development, Vite serves the same SPA on port 5173 and proxies only `/api`, `/assets`, and `/static` back to FastAPI on port 8080.

```
    Browser → http://localhost:8080   or   http://localhost:5173
         │
         ▼
    FastAPI routes + built SPA / Vite dev server
         │
   ├── /                        → React dashboard surface
   ├── /chat                    → React chat surface
   ├── /knowledge               → Knowledge surface (topics tab)
   ├── /knowledge/concepts      → Knowledge surface (concepts tab)
   ├── /knowledge/graph         → Knowledge surface (graph tab)
   ├── /progress                → Progress surface
   ├── /progress/forecast       → Progress forecast tab
   ├── /topic/{id}              → Standalone topic detail compatibility route
   ├── /concept/{id}            → Standalone concept detail compatibility route
   ├── /actions                 → Standalone Activity compatibility route
   ├── /topics, /concepts,
   │   /graph, /reviews,
   │   /forecast                → SPA compatibility redirects
      ├── /api/chat                → JSON chat endpoint
      ├── /api/chat/stream         → SSE chat endpoint
      ├── /api/chat/confirm        → Confirm pending action
      ├── /api/chat/decline        → Decline pending action
      ├── /api/chat/action         → Execute structured UI action
      ├── /api/concepts/{id}       → JSON concept detail (and DELETE for concept removal)
      ├── /api/stats               → JSON: review stats
      ├── /api/topics              → JSON: full topic map
      ├── /api/due                 → JSON: due concepts
         ├── /api/actions             → JSON: paginated action log
         ├── /api/forecast?range=     → JSON: forecast bucket summary
         └── /api/forecast/concepts   → JSON: concepts in one forecast bucket
         │
         └── Most non-chat routes read directly from the db/ package
           (no pipeline, no LLM — pure DB ➜ JSON, plus explicit SPA entry serving)
           Chat and chat-confirmation routes go through
           services/chat_session.py → pipeline → LLM / action execution
```

---

## Database Schema

### knowledge.db

```
topics
  ├── id (PK)
  ├── title
  ├── description
  ├── user_id
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
  ├── interval_days    (exponential: e^(score×SR_INTERVAL_EXPONENT), default 0.075)
  ├── next_review_at   (ISO datetime)
  ├── last_reviewed_at
  ├── review_count
  ├── remark_summary
  ├── remark_updated_at
  ├── last_quiz_generator_output
  ├── user_id
  ├── created_at
  └── updated_at

concept_topics (many-to-many — concepts can belong to multiple topics)
  ├── concept_id → concepts.id
  └── topic_id   → topics.id

concept_remarks (LLM's persistent memory per concept)
  ├── id (PK)
  ├── concept_id → concepts.id
  ├── content       ← strategy notes, user observations, next-quiz plans
  ├── user_id
  └── created_at

review_log (audit trail of every quiz interaction)
  ├── id (PK)
  ├── concept_id → concepts.id
  ├── question_asked
  ├── user_response
  ├── quality        (0–5, LLM-assessed)
  ├── llm_assessment
  ├── user_id
  └── reviewed_at

concept_relations (symmetric concept-to-concept edges)
  ├── id (PK)
  ├── concept_id_low  → concepts.id
  ├── concept_id_high → concepts.id
  ├── relation_type
  ├── note
  └── created_at

pending_proposals (DB-backed confirmation queue)
  ├── id (PK)
  ├── proposal_type
  ├── payload
  ├── discord_message_id
  ├── created_at
  └── expires_at

users
  ├── id (PK)
  ├── display_name
  ├── discord_id
  └── created_at
```

### chat_history.db

```
conversations
  ├── id (PK)
  ├── session_id  (always 'learn')
  ├── role        ('user' | 'assistant')
  ├── content
  ├── user_id
  └── timestamp

session_state
  ├── user_id
  ├── key
  ├── value
  ├── updated_at
  └── PK(user_id, key)
```

Current runtime behavior is still single-user because the Discord bot, REST API, browser frontend, and scheduler do not yet set a non-default current user. The db layer is prepared for future activation via `services/state.py` + `db.core._uid()`, so all existing callers continue to resolve to `user_id='default'` until entry points start calling `set_current_user()`.

---

## Module Responsibilities

### bot.py + bot/ — Discord Interface
- `bot.py` is a thin startup wrapper that loads env/config and launches the shared bot instance from `bot.app`
- `bot/commands.py` registers the active hybrid commands: `/learn`, `/review`, `/due`, `/topics`, `/persona`, `/maintain`, `/reorganize`, `/preference`, `/backup`, `/clear`, `/ping`, and `/sync` (`/maintain` returns a disabled message unless `LEARN_ENABLE_MAINTENANCE=1`)
- `bot/auth.py` provides the `@authorized_only()` decorator used to gate commands to the configured Discord user
- Fast-path commands such as `/due`, `/topics`, `/clear`, `/persona`, `/backup`, and `/ping` avoid the LLM and read config or DB state directly
- `bot/events.py` routes authorized plain messages through the learning pipeline, tracks `last_activity_at`, copies the runtime preferences file on startup if needed, and starts the scheduler on `on_ready`
- `bot/messages.py` and `services/views.py` handle Discord-safe chunking plus persistent button views for confirmations, quiz navigation, and preference edits
- Interactive bot entry points serialize against the shared process-local pipeline lock in `services/state.py` so the Discord path does not interleave with browser/API chat state

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

1. **`call_with_fetch_loop(mode, text, author)`** — Main entry point. Builds context, calls the active LLM provider, handles fetch loop (up to 3 iterations), returns final LLM response string.
2. **`execute_llm_response(user_input, llm_response, mode)`** — Parses the LLM response, executes any action, saves chat history. Returns prefixed result string.
3. **`_call_llm(mode, text, author, extra_context)`** — Assembles the prompt (file refs + dynamic context), requests structured output when configured, calls `provider.send()`, and validates the raw completion before execution/history/display.
4. **`_validate_or_retry_llm_output(...)`** — Contract boundary for raw provider completions. Invalid outputs are written to `data/llm_failures/`, provider session history is cleared, one hidden retry is attempted, and repeated failures become a controlled user-visible formatting error.
5. **`_main_response_format()` / `_append_structured_output_hint(...)`** — Runtime structured-output controls for the main interactive path. Support `LEARN_LLM_OUTPUT_MODE=auto|json_object|json_schema|legacy`; `json_schema` is built from `services/action_contracts.py`.
6. **`handle_review_check()`** — Direct DB read for due concepts. Returns formatted review payload strings.
7. **`handle_maintenance()`** — Direct DB diagnostics. Returns context string or None.
8. **Parsing utilities** — `validate_llm_output()`, `parse_llm_response()`, `extract_llm_action()`, `process_output()`, `guard_user_message()`.
9. **`is_quiz_active()`** — Authoritative quiz-state check. Returns `True` when either `quiz_anchor_concept_id` (single-quiz) or `active_concept_ids` (multi-quiz) is set in session. Used as a guard in `execute_action` to block stale `assess`/`multi_assess` calls.
10. **`execute_action` assess guard** — Before dispatching `assess` or `multi_assess`, `execute_action` calls `is_quiz_active()`. If no quiz is active the action is short-circuited: scores and logs are **not** mutated and `REPLY: (assessment skipped -- no active quiz)` is returned. This guard is enforced identically in `scripts/agent.py`.
11. **`call_action_loop(mode, safe_actions, max_actions, context, preamble, continuation_context_limit=1500, action_journal=None)`** — Generic LLM action loop shared by maintenance and taxonomy modes. Iterates up to `max_actions` rounds; auto-executes safe actions, collects unsafe actions as proposals, and can optionally append structured entries into `action_journal` for operator workflows such as taxonomy shadow rebuild. Taxonomy mode also injects a stable isolated session into `call_with_fetch_loop()` so all action-loop turns stay in the same taxonomy session.
12. **`call_maintenance_loop(diagnostic_context)`** — Thin wrapper around `call_action_loop()` for maintenance mode: uses `SAFE_MAINTENANCE_ACTIONS` and `MAX_MAINTENANCE_ACTIONS = 5`.
13. **`call_taxonomy_loop(taxonomy_context, max_actions=15, continuation_context_limit=1500, action_journal=None, operator_directive=None)`** — Thin wrapper around `call_action_loop()` for taxonomy mode (`"taxonomy-mode"` skill set): uses `SAFE_TAXONOMY_ACTIONS`, supports larger operator-controlled action budgets, can journal replayable actions for the shadow rebuild script, and can inject a script-only operator directive without changing the base taxonomy skill file.
14. **`handle_taxonomy()`** — Entry point called by `scheduler._check_taxonomy()` and `/reorganize`. Returns taxonomy context string, or `None` if no topics exist.

### services/llm.py — Provider Integration
- Owns the OpenAI-compatible chat-completions provider and the optional reasoning-provider override used by scheduled quiz P1
- For `openai_compat`, session history is provider-managed and existing session reads return a copy to avoid accidental live-list mutation
- When structured output mode is enabled, the provider sends `response_format` and retries once without it if an endpoint rejects that option, preserving portability across OpenAI-compatible backends

### services/state.py + services/chat_actions.py — Shared Runtime Coordination
- `services/state.py` owns the process-local `PIPELINE_LOCK`, async/sync lock helpers, `last_activity_at`, and the ContextVar-backed current-user identity
- Bot message handling, API chat routes, Discord button/reply confirmation paths, and direct maintenance/taxonomy approval callbacks all serialize through this shared boundary
- `services/scheduler.py` uses the non-blocking helper so review and any enabled shared jobs skip a cycle when the pipeline is busy rather than interleave with active chat work
- `services/chat_actions.py` centralizes confirmation whitelists and history-entry formatting for the FastAPI browser/API chat surfaces

### services/scheduler.py — Background Tasks
- Starts from both `bot.py` and `api.py`; review delivery remains bot-owned while shared jobs coordinate through a DB-backed owner heartbeat row
- Review check: every 15 minutes (configurable), calls `pipeline.handle_review_check()` → sends quiz DMs
- **Suppresses reviews** when user has been active within `SESSION_TIMEOUT_MINUTES` to avoid interrupting conversations
- Review and any enabled shared jobs skip their current cycle when the shared pipeline lock is busy, so background work yields to active interactive traffic
- Maintenance: optional, every `LEARN_MAINTENANCE_INTERVAL_HOURS` when `LEARN_ENABLE_MAINTENANCE=1`; calls `pipeline.handle_maintenance()` → LLM triages issues → sends report DM
- Taxonomy: every `LEARN_TAXONOMY_INTERVAL_HOURS`, calls `pipeline.handle_taxonomy()` → LLM restructures topic tree → sends report DM
- Dedup: optional, every `LEARN_DEDUP_INTERVAL_HOURS` when `LEARN_ENABLE_DEDUP=1`; proposes merges via DM
- Backup: every `LEARN_BACKUP_INTERVAL_HOURS` (24h default), calls `backup_service.run_backup_cycle()` via thread executor; due-checks use the newest timestamped backup directory on disk rather than scheduler DB state
- Proposal cleanup: every `LEARN_PROPOSAL_CLEANUP_INTERVAL_HOURS` (24h default)

### agent.py — CLI (not used by bot)
- Standalone entry point for testing: `python agent.py --mode=command --input="quiz me"`
- Supports `--context-only`, `--fetch`, `--mode=review-check`, `--mode=maintenance`
- Imports from `context.py` and `tools.py` (same modules the bot uses)
- **Not called by the bot** — pipeline.py calls the modules directly

### frontend/ — Browser Frontend
- React/TypeScript/Vite SPA under `frontend/`
- Served by FastAPI from `frontend/dist` on port 8080 when built
- Served by Vite on port 5173 during local development
- Owns the main browser surfaces for Dashboard, Chat, Knowledge, Progress, and Activity compatibility entry
- Uses `AppShell` for shell-owned behavior such as the Activity drawer and `Ctrl+K` command palette
- Uses resizable split panels in Knowledge for embedded Topic and Concept detail workflows
- Talks to FastAPI JSON and SSE endpoints instead of reading the databases directly
- Uses shared typed API helpers from `frontend/src/api.ts` and route components under `frontend/src/pages/`

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
- **`services/tools_assess.py`** writes the review log and updates score/interval via `db.add_review()` and `db.update_concept()`
- **Interval:** `max(1, round(e^(score × config.SR_INTERVAL_EXPONENT)))` — exponential spacing (default exponent `0.075`)

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

Directories older than `BACKUP_RETENTION_DAYS` (default: 14) are pruned automatically
after each run. The `backups/` directory is `.gitignore`d and never committed.

On Windows, the final temp-dir → timestamped-dir promotion now retries when sync/indexing tools
(most notably OneDrive) briefly lock freshly copied vector-store files. This preserves the atomic
backup model without requiring administrator privileges.

---

## Configuration Summary

| Setting | Default | Source |
|:--------|:--------|:-------|
| Bot token | env `LEARN_BOT_TOKEN` | config.py |
| Authorized user | env `LEARN_AUTHORIZED_USER_ID` | config.py |
| LLM provider | `"openai_compat"` | config.py |
| LLM timeout | 120 seconds | config.py |
| Review check interval | 15 minutes | config.py |
| Maintenance enabled | `0` (disabled) | `LEARN_ENABLE_MAINTENANCE` / config.py |
| Dedup enabled | `0` (disabled) | `LEARN_ENABLE_DEDUP` / config.py |
| Maintenance interval | 168 hours (when enabled) | `LEARN_MAINTENANCE_INTERVAL_HOURS` / config.py |
| Taxonomy interval | 168 hours | `LEARN_TAXONOMY_INTERVAL_HOURS` / config.py |
| Dedup interval | 168 hours (when enabled) | `LEARN_DEDUP_INTERVAL_HOURS` / config.py |
| Backup interval | 24 hours | `LEARN_BACKUP_INTERVAL_HOURS` / config.py |
| Proposal cleanup interval | 24 hours | `LEARN_PROPOSAL_CLEANUP_INTERVAL_HOURS` / config.py |
| Max fetch iterations | 3 | pipeline.py |
| Chat history in context | 12 messages | context.py |
| Max Discord message | 1900 chars | config.py |
| API / React chat port | 8080 | api.py / FastAPI |
| React dev server port | 5173 | Vite (`cd frontend && npm run dev`) |
| Built frontend assets | `frontend/dist/assets` | api.py / FastAPI static mount |
| Data directory | `learning_agent/data/` | config.py |
| Vector store path | `data/vectors/` | `LEARN_VECTOR_STORE_PATH` / config.py |
| Embedding model | `all-mpnet-base-v2` | `LEARN_EMBEDDING_MODEL` / config.py |
| Vector search limit | 10 | `LEARN_VECTOR_SEARCH_LIMIT` / config.py |
| Dedup similarity threshold | 0.92 | `LEARN_SIM_DEDUP` / config.py |
| Relation similarity threshold | 0.50 | `LEARN_SIM_RELATION` / config.py |
| Backup directory | `backups/` (repo root) | `LEARN_BACKUP_DIR` / config.py |
| Backup retention | 14 days | `LEARN_BACKUP_RETENTION_DAYS` / config.py |
