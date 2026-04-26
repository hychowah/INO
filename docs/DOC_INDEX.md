# Documentation Index — Learning Agent

> Central reference for all documentation. See `docs/DOC_STANDARD.md` for update rules and ownership.

---

## For AI Coding Assistants (Copilot, Claude, Cursor)

Read these **before making any code changes**.

| Path | Purpose | Read when |
|------|---------|-----------|
| `CODING.md` | Development instructions, project structure, import conventions, async/sync rules, how to add actions/endpoints | Every coding task |
| `docs/DEVNOTES.md` | Bug history, architecture decisions, institutional memory | Before touching a module with a known quirk; § numbers referenced in comments |
| `docs/ARCHITECTURE.md` | File map, data flow diagrams, module responsibilities, DB schema, vector search, spaced repetition logic | Before adding a module or refactoring across layers |
| `docs/API.md` | Full API surface: Discord commands, REST endpoints, FastAPI-served browser routes, auth, env vars | Before changing or adding any public interface |
| `AGENTS.md` | Pointer file — maps skill files to modes; **do not add runtime instructions here** | When adding or modifying a skill file or pipeline mode |
| `docs/index.md` | Runtime LLM knowledge base map — skill files, persona files, loading logic | When changing skill sets, adding a skill file, or modifying pipeline mode routing |

**Quick reference by task type** — see `docs/DOC_STANDARD.md` for what to update.

---

## For the Runtime LLM

Do not edit these casually — every word affects bot behaviour.

| Path | Purpose | Loaded when |
|------|---------|------------|
| `data/skills/core.md` | Role, philosophy, response format, universal actions, rules | Every LLM call |
| `data/skills/quiz.md` | Quiz/assess actions, scoring rubric, adaptive quiz evolution | Interactive + review modes |
| `data/skills/knowledge.md` | Topic/concept CRUD, casual Q&A, overlap detection | Interactive + maintenance modes |
| `data/skills/maintenance.md` | Maintenance mode behavioural rules, triage priorities | Maintenance mode only |
| `data/skills/taxonomy.md` | Taxonomy reorganisation rules — topic tree restructuring, grouping, suppressed renames | Taxonomy mode only (`/reorganize`, shared scheduler) |
| `data/skills/preferences.md` | Preference editor — fenced-output format, apply-only instruction set | `preference-edit` mode only (`/preference <text>`) |
| `data/skills/quiz_generator.md` | P1 question generation — question types, difficulty, JSON output format | Structured review-quiz P1 for scheduler, `/review`, and shared chat review |
| `data/preferences.md` | Runtime user preferences (git-ignored, auto-copied from template on first startup) | Every LLM call |
| `data/preferences.template.md` | Tracked default preferences file | Repository only |
| `data/personas/*.md` | Persona presets (`mentor`, `coach`, `buddy`) — communication style only | Every LLM call (one active at a time) |

---

## For Human Developers / Operators

| Path | Purpose |
|------|---------|
| `docs/SETUP.md` | Step-by-step local development setup guide |
| `CHANGELOG.md` | Key changes, newest first |
| `docs/TAXONOMY_REBUILD.md` | Manual operator guide for previewing and applying taxonomy rebuilds — preview vs apply, aggressive vs conservative, rollback, Windows/OneDrive troubleshooting |
| `.github/workflows/tests.yml` | Python CI workflow — dependency install, pytest collection guard, full matrix run |
| `.github/workflows/lint.yml` | Ruff CI workflow |
| `.github/workflows/frontend.yml` | Frontend CI workflow — typecheck, Vitest, Playwright |
| `docs/plans/ci-test-suite-overhaul-2026-04-15.md` | Active CI and test-suite overhaul implementation plan |

---

## Meta

| Path | Purpose |
|------|---------|
| `docs/DOC_INDEX.md` | This file — system-wide documentation index |
| `docs/DOC_STANDARD.md` | Doc ownership map, update protocol, style rules, LLM navigation guidance |
