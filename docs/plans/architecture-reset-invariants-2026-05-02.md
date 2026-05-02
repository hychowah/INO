# Architecture Reset Invariants

## Purpose

This document freezes the non-negotiable rules for the architecture reset described in [architecture-reset-master-plan-2026-05-02.md](architecture-reset-master-plan-2026-05-02.md). These invariants exist to prevent a clean-looking refactor from breaking the actual product.

The system may change structure, modules, and internal frameworks. It may not violate the behavioral rules below without an explicit product decision.

## Product Identity

The target system is a user-scoped modular monolith.

- One backend owns learning state, review state, approvals, scheduler state, and LLM orchestration.
- Discord, FastAPI/browser, and scheduler workers are adapters over shared application services.
- The browser remains local-first for now, but the architecture must not block near-term multi-user activation.
- The system remains strongly LLM-driven for teaching, quiz generation, and action suggestion, but code owns validation, execution boundaries, and safety-critical workflow control.

## Conversation And Turn Invariants

- Discord and browser share one cross-surface conversation/session model.
- The long-term concurrency target is one active learning turn per user.
- A turn must not overlap with another turn for the same user in a way that can corrupt quiz state, confirmation state, or tool execution state.
- Removing the current global serialization is allowed only after per-user isolation and per-user turn ownership are in place.
- Cross-user activity must run in parallel without leaking state between users.

## LLM Boundary Invariants

- Raw provider output must never reach users, chat history, or tool execution without passing the output-contract boundary.
- The LLM may suggest actions, but deterministic code must validate action shape, allowed fields, and execution safety.
- Hidden retries and repair paths may change internally, but the boundary must remain fail-closed.
- Prompt changes are not a substitute for safety guards when the model can mutate persistent state.

## Review And Quiz Invariants

- Every assessment must be attributable to the intended quiz instance and intended concept.
- Quiz state must survive the normal failure modes already supported today: follow-up fetches, stale context, retries, and process restarts where applicable.
- Manual review, scheduled review, Discord review, and browser review must use the same canonical review lifecycle.
- Reminder delivery, reminder resend policy, and late-answer recovery must be durable and user-scoped.
- Any rewrite must preserve score integrity, review scheduling continuity, and the ability to recover the right concept after delayed answers.

## Approval And Safety Invariants

- Destructive or semi-destructive actions require durable approval records.
- Discord and browser may present approvals differently, but they must resolve against the same underlying approval lifecycle.
- Maintenance and taxonomy flows must not silently modify learning scores or scheduling fields.
- The distinction between safe auto-executed actions and approval-required actions must remain explicit.

## Multi-User Invariants

- Every entry point that reads or writes user-scoped data must set explicit user context.
- No new runtime path may depend on implicit fallback to the default user once multi-user activation begins.
- A migration to full user scoping must fix known schema holes before cutover, especially any globally unique fields that should become user-scoped.
- Cross-user isolation must cover knowledge, reviews, reminders, approvals, and in-flight turn ownership.

## Scheduler And Automation Invariants

- Shared background jobs must have one durable owner across running processes.
- Review reminders remain durable per user and separate from shared job-ownership state.
- Scheduler timing, scheduler ownership, and notification transport are separable responsibilities and may not be re-braided during refactor.
- API-hosted shared jobs and Discord-only delivery behavior must not silently drift apart.

## Taxonomy And Maintenance Invariants

- Taxonomy and maintenance remain first-class product capabilities.
- Destructive taxonomy and maintenance proposals must preserve approval gates and auditability.
- Taxonomy preview/apply safety may be reimplemented, but preview/apply equivalence and replay integrity must remain intact.
- A simplification that weakens graph safety is a regression, not a cleanup.

## Data And Migration Invariants

- The reset is data-preserving. Existing knowledge, reviews, reminders, proposals, relations, and meaningful conversation continuity must survive migration.
- Temporary compatibility layers are acceptable only when they point toward one canonical model.
- Dual-write bridges are temporary. They must be explicitly retired once the canonical path is proven.
- No milestone is complete until migration rehearsal succeeds against copied real data or equivalent high-fidelity fixtures.

## Test And Acceptance Invariants

The following behavioral surfaces are rewrite blockers and must remain covered throughout the reset:

- Output-contract enforcement.
- Quiz anchor and assess safety.
- Reminder lifecycle and scheduler ownership.
- Durable approval flows.
- Taxonomy preview/apply integrity.
- Cross-surface chat/review parity.
- Multi-user isolation.

Primary acceptance anchors today:

- [../../tests/test_output_contract.py](../../tests/test_output_contract.py)
- [../../tests/test_quiz_anchor.py](../../tests/test_quiz_anchor.py)
- [../../tests/test_assess_no_quiz_guard.py](../../tests/test_assess_no_quiz_guard.py)
- [../../tests/test_scheduler_full.py](../../tests/test_scheduler_full.py)
- [../../tests/test_scheduler_state.py](../../tests/test_scheduler_state.py)
- [../../tests/test_taxonomy_shadow_rebuild.py](../../tests/test_taxonomy_shadow_rebuild.py)
- [../../tests/test_api.py](../../tests/test_api.py)

## Allowed Changes

- Split or merge modules.
- Extract application services.
- Replace direct DB access in adapters with repository or service boundaries.
- Replace process-global coordination with per-user coordination.
- Replace compatibility storage paths with canonical models after validation.
- Replace transport-specific orchestration with shared use-case services.

## Forbidden Shortcuts

- Removing validation because the model is "usually correct".
- Simplifying review state by dropping delayed-answer recovery.
- Collapsing approvals into transient in-memory UI state.
- Activating multi-user entry points while still relying on default-user fallbacks.
- Rewriting taxonomy safety into a best-effort prompt-only flow.
- Claiming a milestone is done without parity checks across Discord, browser, scheduler, and migration rehearsal.

## Decision Gates

The following decisions are fixed for this reset unless explicitly reopened:

- Keep Discord, browser/FastAPI, scheduler-driven reminders, maintenance, and taxonomy.
- Keep browser local-first for now.
- Keep one shared cross-surface conversation/session model.
- Target one active learning turn per user.
- Keep the system strongly LLM-driven.
- Allow major subsystem replacement if data is preserved.

If any of these decisions change, the master plan and roadmap must be re-baselined instead of patched ad hoc.