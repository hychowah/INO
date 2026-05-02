# Architecture Reset Roadmap

## Purpose

This roadmap turns the master plan in [architecture-reset-master-plan-2026-05-02.md](architecture-reset-master-plan-2026-05-02.md) into milestone-sized execution slices with exit criteria. The sequence is designed to reduce architectural risk before code churn starts.

## Summary

- Strategy: data-preserving architecture reset.
- Target shape: local-first single-user modular monolith with a few shared boundaries.
- Product posture: shared conversation across Discord and browser/API, single-user core.
- Concurrency target: one active learning turn enforced durably rather than process-locally.
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

## Milestone 1: Target Narrowing And Turn Coordination

### Goal

Replace the over-broad target architecture with the minimum boundaries needed to move code safely.

### Deliverables

1. Revised target architecture sketch centered on Turn Gateway, Review service, approval policy split, LLM runtime, and db/infrastructure.
2. Simplified canonical conversation state model focused on shared history plus durable turn ownership.
3. Simplified canonical proposal state model focused on durable approvals only.
4. Initial implementation design for the durable single-user turn gateway.

### Exit Criteria

- The architecture target no longer depends on unnecessary service layers.
- The implementation team can start the turn-gateway slice without reopening product decisions.
- Shared conversation behavior is preserved as a hard requirement.

### Main Risks

- Replacing the global lock with another implicit or process-local mechanism.
- Accidentally broadening the turn gateway into a catch-all runtime state bag.

## Milestone 2: Shared Review Extraction

### Goal

Remove the highest-value workflow duplication first.

### Deliverables

1. Canonical Review service covering manual review start, scheduled review send, quiz setup, assess, skip, reminder registration, reminder resend, and delayed-answer recovery.
2. Migration plan for moving reminder ownership out of transport and scheduler branches.
3. Focused regression harness for review extraction.

### Exit Criteria

- Review logic is no longer implemented separately per surface.
- Reminder ownership is converging on one canonical boundary.
- Quiz-anchor and assess-safety semantics remain intact.

### Main Risks

- Breaking delayed-answer recovery while centralizing reminder state.
- Leaving the compatibility bridge in place long enough for new drift to appear.

## Milestone 3: Approval Split And Scheduler Cleanup

### Goal

Make approval ownership explicit and reduce scheduler workflow ownership.

### Deliverables

1. One shared approval policy that distinguishes durable proposals from lightweight same-turn confirms.
2. Durable proposal path reused for maintenance, taxonomy, and dedup.
3. Lightweight confirmation helpers reused across Discord and browser/API.
4. Scheduler runner changes so review and durable approval behavior call shared boundaries instead of owning workflow logic.

### Exit Criteria

- Durable approval behavior is unified where it matters.
- Lightweight confirmation behavior no longer drifts across surfaces.
- Scheduler timing stays stable while workflow ownership shrinks.

### Main Risks

- Forcing lightweight confirms into durable storage and increasing friction.
- Moving too much scheduler code at once and obscuring job ownership bugs.

## Milestone 4: Runtime And Automation Cleanup

### Goal

Shrink oversized orchestrators only after behavior is centralized.

### Deliverables

1. Scheduler runner cleanup that leaves owner election and due checks intact while removing remaining workflow-specific branches.
2. LLM runtime cleanup that retains prompt assembly, fetch loop, output validation, repair, and tool execution while shedding business-specific orchestration.
3. A reusable automation-runner pattern for maintenance and taxonomy where shared behavior is real.

### Exit Criteria

- Scheduler no longer doubles as a workflow controller.
- The LLM runtime is a true runtime boundary, not the owner of every use case.
- Maintenance and taxonomy do not require heavyweight peer services just to stay clean.

### Main Risks

- Double-running jobs during scheduler cutover.
- Moving workflow policy out of the runtime without updating prompt and tool contracts.

## Milestone 5: Surface Hardening, Bridge Retirement, And Final Cutover

### Goal

Make the adapters thin and retire transitional architecture.

### Deliverables

1. HTTP adapters built around typed service contracts instead of ad hoc envelopes.
2. Discord adapters reduced to transport concerns.
3. Retirement of reminder dual-write, transport-specific confirmation state, and legacy direct DB access from adapters.
4. Acceptance suite execution and migration rehearsal against the narrowed architecture.

### Exit Criteria

- Adapters no longer own domain workflow.
- Temporary compatibility bridges are removed after verification.
- Browser and Discord behavior remains aligned through the shared boundaries.
- Migration rehearsal preserves data and workflow continuity.

### Main Risks

- Leaving compatibility bridges in place because they appear harmless.
- Reintroducing surface-specific special cases during cleanup.
- Declaring completion from code shape alone.
- Skipping migration rehearsal because tests passed.

## Suggested Execution Order

`Milestone 0 -> Milestone 1 -> Milestone 2 -> Milestone 3 -> Milestone 4 -> Milestone 5`

Parallel guidance:

- Milestone 0 artifacts can be refined in parallel, but sign-off must happen together.
- Milestone 1 target narrowing and turn-gateway design can overlap.
- Milestone 3 approval-policy cleanup and scheduler cleanup can proceed together once the Review boundary is stable.
- Milestone 4 scheduler and runtime cleanup can proceed together once review and approval ownership are stable.
- Acceptance work starts early, but Milestone 5 only closes after migration rehearsal.

## First Execution Slice

Implementation begins here, not with more architecture sprawl.

1. Rewrite the reset documents to match the narrowed architecture.
2. Design and implement the durable single-user turn gateway.
3. Validate shared conversation behavior before starting review extraction.

Only after those three are stable should the Review extraction widen the code change surface.