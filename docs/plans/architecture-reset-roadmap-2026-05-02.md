# Architecture Reset Roadmap

## Purpose

This roadmap turns the master plan in [architecture-reset-master-plan-2026-05-02.md](architecture-reset-master-plan-2026-05-02.md) into milestone-sized execution slices with exit criteria. The sequence is designed to reduce architectural risk before code churn starts.

## Summary

- Strategy: data-preserving architecture reset.
- Target shape: user-scoped modular monolith.
- Product posture: local-first browser now, multi-user soon.
- Concurrency target: one active learning turn per user.
- Rewrite rule: preserve invariants first, then simplify structure.

## Milestone 0: Freeze Rewrite Boundaries

### Goal

Prevent false starts by locking the behavioral rules and the target shape.

### Deliverables

1. The master plan.
2. The invariants brief.
3. A reviewed debt register grouped by workflow, state, and ownership boundary.
4. A target architecture sketch showing adapters, application services, LLM runtime, and repositories/infrastructure.

### Exit Criteria

- The team agrees on what must not regress.
- The team agrees on the target module boundaries.
- The rewrite can be evaluated against explicit invariants instead of taste.

### Main Risks

- Premature coding before the boundaries are frozen.
- Debating frameworks instead of ownership boundaries.

## Milestone 1: Current-State Map And Canonical Models

### Goal

Replace fuzzy understanding with one explicit map of the current control flow and one explicit design for future canonical state.

### Deliverables

1. Current-state workflow map covering Discord, browser/API, scheduler, maintenance, and taxonomy.
2. Canonical state design for conversation/session state.
3. Canonical state design for review/reminder state.
4. Canonical state design for proposal/approval state.
5. A bridge-retirement plan for existing compatibility layers.

### Exit Criteria

- Every duplicated state path is identified.
- Every future write path has one intended canonical owner.
- Compatibility bridges are classified as temporary, not permanent architecture.

### Main Risks

- Keeping dual-write logic indefinitely.
- Designing canonical state without accounting for restart recovery and late-answer flows.

## Milestone 2: Multi-User Activation Prep

### Goal

Make the system genuinely ready for user-scoped execution before changing orchestration.

### Deliverables

1. Explicit entry-point user-context design for Discord, browser/API, scheduler, and background jobs.
2. Schema-gap inventory and fixes for user scoping.
3. Detection or logging for any path still writing as the default user during transition.
4. Multi-user smoke plan covering knowledge, reminders, approvals, and turn isolation.

### Exit Criteria

- No new code depends on implicit default-user writes.
- Known user-scoping holes are either fixed or explicitly blocked from activation.
- The team can activate per-user context without silent data leakage.

### Main Risks

- Partial activation that creates mixed default-user and explicit-user writes.
- Hidden implicitly scoped tables surviving the cutover.

## Milestone 3: Shared Review, Conversation, And Proposal Services

### Goal

Remove the highest-value workflow duplication first.

### Deliverables

1. Canonical Review service covering selection, quiz generation, anchors, assessment, reminders, and delayed-answer recovery.
2. Canonical Conversation service covering chat/session state, command dispatch, confirmation markers, history persistence, and per-user turn serialization.
3. Canonical Proposal service covering creation, expiry, audit, approval, rejection, and execution handoff.
4. Adapter integration plan for Discord, browser/API, and scheduler.

### Exit Criteria

- Review logic is no longer implemented separately per surface.
- Proposal semantics are unified across Discord and browser.
- Conversation behavior is shared instead of transport-owned.

### Main Risks

- Breaking delayed-answer recovery while consolidating review state.
- Preserving old adapters in parallel long enough to create drift.

## Milestone 4: Scheduler And LLM Runtime Decomposition

### Goal

Shrink oversized orchestrators and separate timing, policy, and transport responsibilities.

### Deliverables

1. Scheduler runner design that separates owner election, due checks, job execution, and notification transport.
2. LLM runtime design that retains prompt assembly, fetch loop, output validation, repair, and tool execution while shedding workflow-specific orchestration.
3. Migration plan for moving maintenance, taxonomy, review, and preference flows out of the oversized runtime modules.

### Exit Criteria

- Scheduler no longer doubles as a workflow controller.
- The LLM runtime is a true runtime boundary, not the owner of every use case.
- API-hosted shared jobs and Discord-only delivery cannot silently diverge.

### Main Risks

- Double-running jobs during scheduler cutover.
- Moving workflow policy out of the runtime without updating prompt and tool contracts.

## Milestone 5: Surface Hardening And Bridge Retirement

### Goal

Make the adapters thin and retire transitional architecture.

### Deliverables

1. HTTP adapters built around typed service contracts instead of ad hoc envelopes.
2. Discord adapters reduced to transport concerns.
3. Retirement of reminder dual-write, transport-specific confirmation state, and legacy direct DB access from adapters.
4. Local-first browser hardening that stays compatible with future multi-user rollout.

### Exit Criteria

- Adapters no longer own domain workflow.
- Temporary compatibility bridges are removed after verification.
- Browser and Discord behavior remains aligned through shared services.

### Main Risks

- Leaving compatibility bridges in place because they appear harmless.
- Reintroducing surface-specific special cases during cleanup.

## Milestone 6: Final Cutover And Acceptance

### Goal

Prove the reset preserved the product while reducing structural debt.

### Deliverables

1. Acceptance suite execution against the rewrite blockers.
2. Parity matrix for Discord, browser, scheduler, maintenance, and taxonomy flows.
3. Migration rehearsal against copied real data or equivalent fixtures.
4. Post-cutover cleanup list for residual minor debt.

### Exit Criteria

- Rewrite blockers pass.
- Migration rehearsal preserves data and workflow continuity.
- No adapter bypasses the shared services for core workflows.

### Main Risks

- Declaring completion from code shape alone.
- Skipping migration rehearsal because tests passed.

## Suggested Execution Order

`Milestone 0 -> Milestone 1 -> Milestone 2 -> Milestone 3 -> Milestone 4 -> Milestone 5 -> Milestone 6`

Parallel guidance:

- Milestone 0 artifacts can be refined in parallel, but sign-off must happen together.
- Milestone 1 workflow mapping and canonical-state design can overlap.
- Milestone 3 Review, Conversation, and Proposal service design can proceed together after Milestone 2.
- Milestone 4 scheduler and LLM runtime decomposition can proceed together once service boundaries are stable.
- Acceptance work starts early, but Milestone 6 only closes after migration rehearsal.

## First Execution Slice

The immediate next slice should stay in planning and architecture-definition mode, not code churn.

1. Finish the debt register and current-state workflow map.
2. Produce the target architecture sketch.
3. Define the canonical state models.
4. Identify the exact schema and entry-point blockers for multi-user activation.

Only after those four are reviewed should implementation begin.