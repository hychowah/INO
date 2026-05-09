# Architecture Simplification Master Plan

## Purpose

This plan governs the architecture simplification effort for the Learning Agent.
The goal is to reduce accidental complexity without weakening the core learning loop,
LLM safety boundaries, or transport parity between Discord and the browser.

## Problem Statement

The repository is not primarily suffering from classitis.
The current issue is orchestration spread: one core learning loop is surrounded by
multiple transport-owned workflow branches, optional runtime subsystems, and a few
oversized gateway modules.

## Baseline Summary

| Metric | Baseline |
|---|---:|
| Runtime LOC total (`services/`, `bot/`, `api/`, `db/`, `frontend/src/`) | 18,941 |
| Production classes | 42 |
| Confirmed synthetic slash-to-chat routes | 2 |
| Confirmed duplicate review entry flows | 2 |

## Scope

| Included | Excluded for now |
|---|---|
| Shared-core ownership cleanup | Replacing FastAPI or Discord frameworks |
| Transport thinning for Discord and browser | Rewriting the LLM-first product model |
| Hotspot reduction in large modules | Removing LLM output-contract validation |
| Review, quiz, and proposal flow consolidation | Removing confirmation safety guards |
| Optional subsystem de-emphasis | Expanding multi-user architecture |

## Success Model

Line count is a guardrail, not the sole KPI.
A good refactor should reduce runtime LOC over completed phases while also making
ownership clearer and duplicated paths fewer.

| Metric | Why it matters | Rule |
|---|---|---|
| Runtime LOC total | Detects long-term code growth | Must trend downward across completed phases |
| Hotspot LOC | Exposes oversized modules directly | Priority files should shrink or split with clear ownership gains |
| Synthetic command routes | Measures transport indirection | Should trend toward zero |
| Duplicate workflow entries | Measures duplicated orchestration | Should trend downward each phase |
| Transport-owned business logic | Measures adapter thickness | Should move into shared services |
| Production classes | Secondary guardrail | Track only; do not optimize for this alone |
| Focused regression coverage | Prevents simplification regressions | Every phase needs a recorded validation step |

## Hotspot Files

These files are the first tracking targets because they currently carry a large
share of the accidental complexity.

| Path | Baseline LOC |
|---|---:|
| `services/pipeline.py` | 1,113 |
| `services/context.py` | 816 |
| `frontend/src/pages/ChatPage.tsx` | 698 |
| `db/concepts.py` | 664 |
| `services/views.py` | 620 |
| `services/scheduler.py` | 587 |
| `services/tools.py` | 584 |
| `services/tools_assess.py` | 466 |
| `services/chat_session.py` | 424 |
| `bot/commands.py` | 398 |
| `api/routes/chat.py` | 124 |

## Decision Rules

| Rule | Decision |
|---|---|
| New files | Allowed only when they retire a hotspot or create a clearer ownership boundary |
| Temporary LOC increase | Acceptable only inside an active phase that also removes the old path before the phase closes |
| File splits | Count as success only if duplication drops or ownership becomes materially clearer |
| Transport parity | Discord and browser remain equal peers, but they should become thinner adapters |
| Multi-user groundwork | Keep it dormant and narrow; do not expand it during this effort |
| Optional subsystems | Treat vector search, taxonomy, maintenance, dedup, and backup as candidates for clearer operator-only boundaries |

## Canonical Core Boundary

The core runtime path to protect during simplification is:

1. One transport entrypoint receives user input.
2. `services.learn_turn.run_learn_turn()` resolves command versus reply mode.
3. `services.llm_runtime.call_with_fetch_loop()` handles prompt/runtime/fetch-loop orchestration, and `services.pipeline.execute_llm_response()` handles parse-and-execute orchestration.
4. `services.tools` and `services.tools_assess` execute actions.
5. `db` modules persist knowledge, review, and session state.

Everything outside that path should justify itself as either adapter code,
operator workflow, or optional enhancement.

## Phases

| Phase | Goal | Exit criteria | Status |
|---|---|---|---|
| 0 | Create planning artifacts in `docs/plans/` | Master plan and progress tracker exist and are linked from doc indexes | Completed |
| 1 | Lock the canonical core boundary | Core path and protected seams are documented and accepted | Not started |
| 2 | Capture the baseline | Tracker records area LOC, hotspot LOC, duplication counts, and validation targets | Completed |
| 3 | Flatten transport orchestration | Discord and browser call shared command services directly for the targeted flows | In progress |
| 4 | Split `services/pipeline.py` by responsibility | Public behavior preserved while internal ownership is cleaner | In progress |
| 5 | Consolidate review, quiz, and proposal ownership | Shared services own the behavior; transports only render it | In progress |
| 6 | Right-size optional runtime subsystems | Operator-only and optional boundaries are clearer | Not started |
| 7 | Reduce UI boilerplate and page hotspots | Discord view and browser chat hotspots shrink without behavior loss | Not started |
| 8 | Reassess framework fit | Keep-both-equal decision is re-evaluated using post-refactor facts | Not started |

## First Confirmed Simplification Targets

| Target | Current evidence |
|---|---|
| Synthetic chat command routes in `bot/commands.py` | First target completed: `/maintain` and `/reorganize` now use direct shared request entrypoints |
| Duplicate review entry orchestration | Second target completed: shared review request orchestration now lives in `services/chat_session.py`, with the bot projecting the shared result |
| Confirmed review and proposal execution ownership | Third target completed: confirmed `maintenance_review` and `taxonomy_review` execution now lives in `services/chat_admin.py` instead of `services/chat_session.py` |
| Discord confirm and preference ownership | Later Phase 5 slices moved reply confirms, button confirms, and `/preference` approval onto shared confirm and pending-action surfaces instead of adapter-owned callbacks |
| Discord quiz follow-up ownership | Later Phase 5 slices moved skip execution and quiz follow-up dispatch onto shared `chat_quiz` / `chat_session` action owners, with Discord rebuilding quiz views from shared action payloads |
| Remaining orchestration hotspot in `services/pipeline.py` | Parse-and-execute orchestration, admin loops, and preference edit still live together even after fetch loop, contract retry, and review-specific helpers moved into shared owners |

## Validation Policy

| Phase type | Minimum validation |
|---|---|
| Transport and service refactor | Focused backend tests for chat, review, and turn routing |
| Pipeline split | Contract-sensitive tests plus targeted review generation checks |
| UI cleanup | Relevant Discord regression tests and frontend tests |
| End of phase | Tracker updated with LOC delta, removed paths, added paths, and regression result |

## Ownership

This document owns the architecture simplification strategy.
The companion tracker in `docs/plans/architecture-simplification-progress.md`
owns baseline numbers, current status, progress deltas, and next actions.