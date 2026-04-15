# Documentation Standard — Learning Agent

> Audience: AI coding assistants and human developers. Follow these rules when making any change that touches public interfaces, modules, or the LLM system prompt.

---

## 1. Doc Ownership Map

Each concern has one owning document. Cross-links are fine; duplication is not.

| Concern | Owner | Also update |
|---------|-------|-------------|
| Public REST endpoints | `docs/API.md` | `docs/ARCHITECTURE.md` (file map if new module) |
| Discord bot commands | `docs/API.md` | — |
| Browser SPA routes | `docs/API.md` | `docs/ARCHITECTURE.md` (Flow 4 diagram) |
| Module structure / file roles | `docs/ARCHITECTURE.md` | `CODING.md` (project structure tree) |
| Test layout / CI workflows / manual smoke scripts | `docs/SETUP.md` | `docs/ARCHITECTURE.md`, `docs/index.md`, `docs/DOC_INDEX.md` |
| Runtime LLM skill files | `AGENTS.md` (table) | `docs/index.md`, `docs/ARCHITECTURE.md` (file map) |
| Pipeline mode routing | `docs/index.md` | `AGENTS.md` (Skill sets section) |
| Import conventions / async rules | `CODING.md` | — |
| Bug history / architecture decisions | `docs/DEVNOTES.md` | Reference by section number from code comments |
| Key changes summary | `CHANGELOG.md` | — |
| Operator runbooks | `docs/TAXONOMY_REBUILD.md` or new file in `docs/` | — |
| Feature designs / plans | `docs/plans/<feature>.md` | — |

---

## 2. Update Protocol by Task Type

### New REST endpoint
1. Add row to the correct table in `docs/API.md` (Chat / Topics / Concepts / etc.)
2. If the route lives in a new file: add row to `docs/ARCHITECTURE.md` file map
3. Add one-line entry to `CHANGELOG.md` under the current date section

### New module or package
1. Add row to `docs/ARCHITECTURE.md` file map (path, line count, role)
2. Add entry to the `CODING.md` project structure tree
3. Add one-line entry to `CHANGELOG.md`

### New bot slash command
1. Add row to the Discord Commands table in `docs/API.md`
2. Add one-line entry to `CHANGELOG.md`

### New browser page or route
1. Add row to the browser routes table in `docs/API.md`
2. Add the route to Flow 4 in `docs/ARCHITECTURE.md`
3. If a new page module was added: update `ARCHITECTURE.md` file map and `CODING.md` tree

### New skill file (`data/skills/*.md`)
1. Add row to the skill file table in `AGENTS.md`
2. Add the corresponding **Skill sets by mode** bullet in `AGENTS.md`
3. Add row to the Runtime LLM table in `docs/index.md`
4. Add row to the `docs/ARCHITECTURE.md` file map

### Bug fix
1. Add one-line entry to `CHANGELOG.md` under Fixed

### Refactor (module split or rename)
1. Update `docs/ARCHITECTURE.md` file map (remove old row, add new rows)
2. Update `CODING.md` project structure tree
3. Add entry to `CHANGELOG.md` under Refactored

### Test suite or CI workflow change
1. Update `docs/SETUP.md` for the command surface, CI-equivalent local checks, and any manual smoke scripts
2. If tests or scripts were moved/renamed: update `docs/ARCHITECTURE.md` file map
3. If the docs inventory or active plan changed: update `docs/index.md` and `docs/DOC_INDEX.md`
4. Add one-line entry to `CHANGELOG.md` under Changed or Refactored

### New environment variable
1. Add row to the Environment Variables table in `docs/API.md`
2. Add to `config.py` docstring / inline comment

---

## 3. Style Rules

- **Tables for reference information.** Use prose only for explanations that require narrative.
- **Relative paths everywhere.** Never use absolute paths in documentation.
- **No dates in file bodies** except `CHANGELOG.md`.
- **No version numbers in runtime skill files** (`data/skills/*.md`) — they are hot-reloaded and version-pinning causes confusion.
- **Keep file map line counts approximate** (`~N`) — update when a file grows or shrinks by more than ~50 lines.
- **One fact, one file.** If the same detail appears in two docs, one of them is wrong. Point to the owner with a cross-reference.
- **`docs/plans/` lifecycle** — one file per active feature. Remove or archive a plan file once the feature ships. Do not list stale plan files in `docs/index.md` or `CODING.md`.
- **`docs/DEVNOTES.md` sections** — reference by section number from code comments (e.g. `# see DEVNOTES §12`). Do not inline the detail in both places.

---

## 4. LLM Navigation Guide

Use this to know which file to open first for common tasks.

| Task | Start here |
|------|-----------|
| Adding or changing a route | `docs/API.md` → `api/routes/` |
| Understanding the pipeline flow | `docs/ARCHITECTURE.md` § Interaction Flows |
| Changing quiz or assess behaviour | `data/skills/quiz.md`, `services/tools_assess.py` |
| Changing maintenance behaviour | `data/skills/maintenance.md`, `services/scheduler.py` |
| Touching the DB schema | `db/core.py` + `db/migrations.py`; read `docs/DEVNOTES.md` first |
| Adding a new DB function | `db/<module>.py`; check `db/__init__.py` re-exports |
| Understanding score/interval math | `docs/ARCHITECTURE.md` § Spaced Repetition |
| Debugging a quirky edge case | `docs/DEVNOTES.md` |
| Changing what the LLM can do | `data/skills/core.md` (actions) or mode-specific skill file |
| Adding a new mode | `services/pipeline.py` (`SKILL_SETS`, `_mode_to_skill_set`), then update `AGENTS.md` + `docs/index.md` |

---

## 5. Files You Should NOT Edit Casually

| File | Risk | Notes |
|------|------|-------|
| `data/skills/*.md` | High | Every word affects LLM behaviour; test by chatting with bot |
| `db/core.py` + `db/migrations.py` | High | Schema changes require migration blocks and may corrupt data |
| `services/pipeline.py` | Medium | Core orchestration; quiz guard and mode routing live here |
| `AGENTS.md` | Low | Pointer file only; put instructions in skill files |
| `data/preferences.template.md` | Medium | Template is git-tracked; runtime `data/preferences.md` is git-ignored |
| `data/personas/*.md` | Medium | Style files; ~600 token budget; no action formats or scoring rules |
