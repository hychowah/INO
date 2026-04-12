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
| `data/skills/quiz.md` | Interactive, Review | Quiz/assess actions, scoring rubric, adaptive quiz evolution |
| `data/skills/knowledge.md` | Interactive, Maintenance | Topic/concept CRUD, casual Q&A, overlap detection |
| `data/skills/maintenance.md` | Maintenance only | Maintenance mode behavioral rules |
| `data/skills/taxonomy.md` | Taxonomy, /reorganize | Topic tree restructuring, grouping rules, rename criteria, suppression |
| `data/skills/preferences.md` | preference-edit (/preference text mode) | Isolated fenced-output editor — apply requested change and return full updated preferences file |
| `data/skills/quiz_generator.md` | Scheduled quiz P1 only | Question generation instructions for the reasoning model; Prompt 1 also receives Active Persona + User Preferences and returns structured JSON including `formatted_question` (not loaded via SKILL_SETS) |

**Skill sets by mode:**
- **interactive** (COMMAND/REPLY): core + quiz + knowledge
- **review** (REVIEW-CHECK): core + quiz
- **maintenance** (MAINTENANCE): core + maintenance + knowledge
- **taxonomy** (TAXONOMY-MODE, /reorganize): taxonomy
- **preference-edit** (/preference text edit path): preferences only

Scheduled quiz delivery no longer uses an LLM packaging stage. `package_quiz_for_discord()` is now a deterministic compatibility wrapper over the P1 output.

See `docs/index.md` for the full knowledge base map.
