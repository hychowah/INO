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
| `preferences.md` | User learning preferences | Every LLM call |
| `data/personas/*.md` | Persona presets (mentor, coach, buddy) | Every LLM call (one active) |

## Developer Documentation

| Path | Purpose |
|---|---|
| `CODING.md` | Development instructions for AI coding assistants |
| `docs/ARCHITECTURE.md` | System architecture, file map, data flow, diagrams |
| `docs/DEVNOTES.md` | Bug history, architecture decisions, institutional memory |
| `docs/PLAN.md` | Feature planning and roadmap |
| `docs/CONCEPT_RELATIONS_PLAN.md` | Concept relations feature design |

## Skill Sets by Mode

```
COMMAND / REPLY  → interactive → core + quiz + knowledge
REVIEW-CHECK     → review      → core + quiz
MAINTENANCE      → maintenance → core + maintenance + knowledge
```

Loading logic: `services/pipeline.py` → `_mode_to_skill_set()` → `SKILL_SETS` dict → `_get_base_prompt(skill_set)`.

## Editing Guidelines

- **Skill files** (`data/skills/*.md`): These are the LLM's runtime instructions. Every word affects behavior. Test changes by chatting with the bot. Preserve `<!-- DO NOT REMOVE -->` comments — they prevent formatting regressions (see DEVNOTES.md §1).
- **AGENTS.md**: Pointer file only. Do not put instructions here — edit skill files instead.
- **Persona files**: Communication style only — no action formats or scoring rules. ~600 token budget per file.
