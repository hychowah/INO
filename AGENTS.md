# AGENTS.md — Learning Agent System Prompt

<!-- DEV NOTE: This file is the TABLE OF CONTENTS. Full instructions are assembled
     from data/skills/ at runtime by pipeline.py. Edit the source files there.
     Copilot/coding assistants: read docs/DEVNOTES.md before editing code.
     Runtime LLM instructions belong in data/skills/*.md, not this file. -->

This file is the entry point for the runtime LLM system prompt.

Instructions are split into modular skill files loaded per-mode:

| Skill file | Loaded for | Contents |
|---|---|---|
| `data/skills/core.md` | All modes | Role, philosophy, response format, universal actions, rules |
| `data/skills/quiz.md` | Interactive, Review, Quiz-packaging | Quiz/assess actions, scoring rubric, adaptive quiz evolution, packaging |
| `data/skills/knowledge.md` | Interactive, Maintenance | Topic/concept CRUD, casual Q&A, overlap detection |
| `data/skills/maintenance.md` | Maintenance only | Maintenance mode behavioral rules |
| `data/skills/quiz_generator.md` | Scheduled quiz P1 only | Question generation instructions for reasoning model (not loaded via SKILL_SETS) |

**Skill sets by mode:**
- **interactive** (COMMAND/REPLY): core + quiz + knowledge
- **review** (REVIEW-CHECK): core + quiz
- **maintenance** (MAINTENANCE): core + maintenance + knowledge
- **quiz-packaging** (Scheduled quiz P2): core + quiz

See `docs/index.md` for the full knowledge base map.
