# Learning Agent — Knowledge Base Map

> This file is the central reference for understanding the project's documentation structure.
> See `AGENTS.md` (root) for how skill files are loaded at runtime.

## Runtime LLM Instructions

| Path | Purpose | Loaded when |
|---|---|---|
| `AGENTS.md` | Pointer file — table of contents only | Read by developers/Copilot |
| `data/skills/core.md` | Role, philosophy, response format, universal actions, rules | Every LLM call |
| `data/skills/quiz.md` | Quiz/assess actions, scoring rubric, adaptive quiz evolution | Interactive + review modes |
| `data/skills/knowledge.md` | Topic/concept CRUD, casual Q&A, overlap detection | Interactive + maintenance modes |
| `data/skills/maintenance.md` | Maintenance mode behavioral rules, triage priorities | Maintenance mode only |
| `data/skills/taxonomy.md` | Taxonomy reorganization rules — topic tree restructuring, grouping, rename criteria, suppression | Taxonomy mode only (`/reorganize`) |
| `data/skills/preferences.md` | Preference editor instructions and fenced output format | `preference-edit` mode only (`/preference` with text) |
| `data/skills/quiz_generator.md` | P1 question generation instructions for reasoning model | Scheduled quiz P1 only (not loaded via SKILL_SETS) |
| `data/preferences.template.md` | Tracked default preferences file copied on first startup | Repository only |
| `data/preferences.md` | Runtime user preferences copy (git-ignored) | Every LLM call |
| `data/personas/*.md` | Persona presets (mentor, coach, buddy) | Every LLM call (one active) |

## Developer Documentation

| Path | Purpose |
|---|---|
| `CODING.md` | Development instructions for AI coding assistants |
| `docs/SETUP.md` | Step-by-step local development setup guide |
| `docs/API.md` | API reference: Discord commands, REST endpoints, Web UI pages |
| `docs/ARCHITECTURE.md` | System architecture, file map, data flow, diagrams; **§ Semantic Search & Vector Store** |
| `docs/DEVNOTES.md` | Bug history, architecture decisions, institutional memory; **§12 Hybrid Vector Search** |
| `docs/TAXONOMY_REBUILD.md` | Manual operator guide for previewing and applying taxonomy rebuilds |
| `docs/plans/` | Active feature design plans (see directory for current files) |

## Skill Sets by Mode

```
COMMAND / REPLY  → interactive    → core + quiz + knowledge
REVIEW-CHECK     → review         → core + quiz
MAINTENANCE      → maintenance    → core + maintenance + knowledge
quiz-packaging   → quiz-packaging → core + quiz  (P2 scheduled quiz packaging)
TAXONOMY-MODE    → taxonomy       → taxonomy only   (/reorganize, weekly scheduler)
preference-edit  → preference-edit → preferences only   (/preference text edit path)
```

Loading logic: `services/pipeline.py` → `_mode_to_skill_set()` → `SKILL_SETS` dict → `_get_base_prompt(skill_set)`. The `/preference` edit path is the exception: it calls `_get_base_prompt("preference-edit")` directly and bypasses `_mode_to_skill_set()` and `_call_llm()`.

## Editing Guidelines

- **Skill files** (`data/skills/*.md`): These are the LLM's runtime instructions. Every word affects behavior. Test changes by chatting with the bot. Preserve `<!-- DO NOT REMOVE -->` comments — they prevent formatting regressions (see DEVNOTES.md §1).
- **AGENTS.md**: Pointer file only. Do not put instructions here — edit skill files instead.
- **Persona files**: Communication style only — no action formats or scoring rules. ~600 token budget per file.
