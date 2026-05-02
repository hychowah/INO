# Architecture Reset Debt Register

## Purpose

This document turns the architecture review into a prioritized debt register. It is not a bug list. It is a map of the structural liabilities that make the current system harder to evolve toward a user-scoped, multi-surface, multi-user-ready product.

Use this register to decide what must be removed, what must be isolated, and what must be preserved during the reset.

## Severity Model

- Critical: blocks the target architecture or creates high risk of silent data or workflow corruption.
- High: materially increases feature cost, behavioral drift, or refactor risk.
- Medium: adds friction or ambiguity but can remain temporarily if bounded.
- Low: cleanup-worthy but not a rewrite driver.

## Debt 1: Review Lifecycle Duplication

- Severity: Critical
- Problem: one logical review lifecycle is implemented separately across Discord, browser/API chat, and scheduler delivery.
- Symptoms:
  - Concept selection, quiz generation, reminder registration, and delayed-answer recovery have multiple orchestration paths.
  - Behavior parity must be defended with several transport-specific tests.
- Root cause: review is a product core use case, but it never received one canonical application-service boundary.
- Main evidence:
  - [../../bot/commands.py](../../bot/commands.py)
  - [../../services/chat_session.py](../../services/chat_session.py)
  - [../../services/scheduler.py](../../services/scheduler.py)
  - [../../services/pipeline.py](../../services/pipeline.py)
- Consequence if left alone: every future review change fans out across three adapters and three failure surfaces.
- Reset direction: extract one Review service and route all surfaces through it.

## Debt 2: Reminder State Bridge

- Severity: Critical
- Problem: reminder state is mirrored across typed reminder rows and legacy session-state blobs.
- Symptoms:
  - Review state correctness depends on synchronization between multiple stores.
  - Recovery behavior is hard to reason about because scheduler and assess flows do not consume the same state directly.
- Root cause: the system evolved from one session-state model to a durable typed reminder model without fully retiring the original representation.
- Main evidence:
  - [../../services/review_state.py](../../services/review_state.py)
  - [../../db/review_reminders.py](../../db/review_reminders.py)
  - [../../db/chat.py](../../db/chat.py)
- Consequence if left alone: reminder drift and delayed-answer regressions remain a constant risk.
- Reset direction: design one canonical reminder model and demote compatibility paths to temporary reads only.

## Debt 3: Split Approval Models

- Severity: High
- Problem: Discord and browser/API use different confirmation and proposal lifecycles.
- Symptoms:
  - Discord uses durable proposal records and persistent views.
  - Browser/API uses a separate confirm flow and UI payload model.
- Root cause: approvals were introduced transport-first instead of service-first.
- Main evidence:
  - [../../services/views.py](../../services/views.py)
  - [../../services/chat_actions.py](../../services/chat_actions.py)
  - [../../services/chat_session.py](../../services/chat_session.py)
  - [../../db/proposals.py](../../db/proposals.py)
- Consequence if left alone: approval semantics, restart behavior, and auditability continue to drift across surfaces.
- Reset direction: create one Proposal service with transport-specific presentation only.

## Debt 4: Dormant Multi-User Runtime

- Severity: Critical
- Problem: storage and context groundwork for multi-user exists, but runtime entry points still behave as effectively single-user.
- Symptoms:
  - Default-user fallbacks remain live.
  - Browser/API still behaves as a single hardcoded actor.
  - Some schema surfaces are still implicitly scoped or globally unique.
- Root cause: schema groundwork landed before entry-point activation and before all ownership assumptions were cleaned up.
- Main evidence:
  - [../../db/core.py](../../db/core.py)
  - [../../services/state.py](../../services/state.py)
  - [../../api/routes/chat.py](../../api/routes/chat.py)
  - [../../db/relations.py](../../db/relations.py)
- Consequence if left alone: multi-user activation becomes dangerous because partial cutover can silently leak writes into the default user.
- Reset direction: fix remaining schema gaps first, then activate explicit per-user context at every entry point.

## Debt 5: Process-Global Turn Coordination

- Severity: High
- Problem: the current system relies on process-global serialization because conversation and review state are not yet isolated per user.
- Symptoms:
  - One lock protects behavior that should eventually be user-scoped.
  - Adapters and scheduler flows must avoid overlapping mutable state indirectly.
- Root cause: the current runtime still shares too much workflow state globally.
- Main evidence:
  - [../../services/state.py](../../services/state.py)
  - [../../bot/handler.py](../../bot/handler.py)
  - [../../api/routes/chat.py](../../api/routes/chat.py)
- Consequence if left alone: concurrency remains a bottleneck and multi-user activation becomes structurally awkward.
- Reset direction: move to one active turn per user with explicit user-scoped coordination.

## Debt 6: Oversized Pipeline Ownership

- Severity: High
- Problem: one runtime module owns too many distinct responsibilities.
- Symptoms:
  - Prompt assembly, fetch loop control, review helpers, maintenance loops, taxonomy loops, and preference-edit behavior are intertwined.
  - Workflow-specific policy lives inside infrastructure-like runtime code.
- Root cause: new product capabilities were added into the existing orchestrator instead of being pulled outward into use-case services.
- Main evidence:
  - [../../services/pipeline.py](../../services/pipeline.py)
  - [../../services/context.py](../../services/context.py)
- Consequence if left alone: refactors become risky because one file is both runtime boundary and application controller.
- Reset direction: shrink the pipeline into a pure LLM runtime and move use-case orchestration into services.

## Debt 7: Browser/API Controller Drift

- Severity: High
- Problem: browser/API chat owns too much workflow behavior instead of acting as a transport adapter.
- Symptoms:
  - One controller handles commands, confirmations, payload formatting, maintenance/taxonomy flows, and DB-adjacent behavior.
  - Web behavior is similar to Discord behavior but not actually derived from the same use-case boundary.
- Root cause: browser support was added as a shared controller instead of a thin adapter over canonical services.
- Main evidence:
  - [../../services/chat_session.py](../../services/chat_session.py)
  - [../../api/routes/chat.py](../../api/routes/chat.py)
- Consequence if left alone: browser and Discord continue to evolve in parallel rather than together.
- Reset direction: replace the browser controller with HTTP adapters over Conversation, Review, and Proposal services.

## Debt 8: Scheduler Transport Coupling

- Severity: High
- Problem: scheduler ownership, job timing, and notification transport are not cleanly separated.
- Symptoms:
  - Shared jobs can run under one host while reporting expectations remain tied to another transport.
  - Scheduler code mixes due checks, business behavior, and Discord delivery concerns.
- Root cause: the scheduler grew from a delivery mechanism into a general automation engine without being re-layered.
- Main evidence:
  - [../../services/scheduler.py](../../services/scheduler.py)
  - [../../api/app.py](../../api/app.py)
- Consequence if left alone: background jobs and delivery semantics will keep drifting as surfaces evolve.
- Reset direction: split scheduler runner, job execution, and notification transport.

## Debt 9: Local-First Browser With Partial Platform Signals

- Severity: Medium
- Problem: the browser remains local-first, but several layers imply a larger deployment model without supporting it cleanly.
- Symptoms:
  - Localhost auth bypasses are central.
  - Browser/API contracts are broad and loosely typed.
  - The surface is easy to run locally but not cleanly shaped for future remote access.
- Root cause: the product posture is local-first, but some implementation layers were generalized just enough to add ambiguity without actually solving the hosted case.
- Main evidence:
  - [../../api/auth.py](../../api/auth.py)
  - [../../frontend/src/api.ts](../../frontend/src/api.ts)
  - [../../api/schemas.py](../../api/schemas.py)
- Consequence if left alone: browser architecture discussions keep mixing immediate needs with hypothetical remote deployment needs.
- Reset direction: keep the browser explicitly local-first in this reset, but shape the HTTP layer around typed service contracts.

## Debt 10: Context And Provider Abstraction Leakage

- Severity: Medium
- Problem: prompt/context construction knows too much about provider session behavior.
- Symptoms:
  - Context logic makes decisions based on runtime provider/session internals.
  - The runtime boundary is harder to reason about because history ownership is not clearly contained.
- Root cause: provider-managed conversation behavior and context-building rules evolved together without a clean interface boundary.
- Main evidence:
  - [../../services/context.py](../../services/context.py)
  - [../../services/llm.py](../../services/llm.py)
- Consequence if left alone: swapping or simplifying session handling stays harder than necessary.
- Reset direction: define explicit runtime interfaces for prompt context versus provider session history.

## Debt 11: Compatibility Layers That Risk Becoming Permanent

- Severity: High
- Problem: several compatibility bridges are useful today but dangerous if normalized into the permanent design.
- Symptoms:
  - Dual-write or mirrored state persists beyond its original migration purpose.
  - Adapters retain legacy direct DB access because it still works.
- Root cause: compatibility paths were added pragmatically, but there is no hard retirement gate unless the rewrite enforces one.
- Main evidence:
  - [../../services/review_state.py](../../services/review_state.py)
  - [../../services/chat_session.py](../../services/chat_session.py)
  - [../../bot/commands.py](../../bot/commands.py)
- Consequence if left alone: the reset becomes additive instead of simplifying the architecture.
- Reset direction: treat every bridge as temporary and pair it with explicit retirement criteria.

## Debt 12: Acceptance Coverage Not Yet Framed As Rewrite Gates

- Severity: Medium
- Problem: strong tests exist, but the architecture reset still needs a clearly named blocker suite and parity matrix.
- Symptoms:
  - Existing coverage protects many behaviors, but not all of it is yet framed as mandatory cutover evidence.
  - Teams could still claim structural completion without workflow proof.
- Root cause: the test suite evolved around bugs and regressions, not around an explicit rewrite acceptance strategy.
- Main evidence:
  - [../../tests/test_output_contract.py](../../tests/test_output_contract.py)
  - [../../tests/test_quiz_anchor.py](../../tests/test_quiz_anchor.py)
  - [../../tests/test_assess_no_quiz_guard.py](../../tests/test_assess_no_quiz_guard.py)
  - [../../tests/test_scheduler_full.py](../../tests/test_scheduler_full.py)
  - [../../tests/test_scheduler_state.py](../../tests/test_scheduler_state.py)
  - [../../tests/test_taxonomy_shadow_rebuild.py](../../tests/test_taxonomy_shadow_rebuild.py)
  - [../../tests/test_api.py](../../tests/test_api.py)
- Consequence if left alone: the rewrite can look cleaner while still regressing behavior.
- Reset direction: define the blocker suite and parity checklist before code cutover.

## Priority Order

1. Review lifecycle duplication.
2. Reminder state bridge.
3. Dormant multi-user runtime.
4. Split approval models.
5. Process-global turn coordination.
6. Oversized pipeline ownership.
7. Browser/API controller drift.
8. Scheduler transport coupling.
9. Compatibility layers becoming permanent.
10. Acceptance coverage not yet framed as rewrite gates.
11. Context/provider abstraction leakage.
12. Local-first browser with partial platform signals.

## What This Register Implies

- The first target is shared use-case extraction, not framework replacement.
- The second target is canonical state ownership, not cosmetic renaming.
- Multi-user activation must be deliberate and staged.
- The scheduler and runtime should be decomposed only after the Review, Conversation, and Proposal service boundaries are real.