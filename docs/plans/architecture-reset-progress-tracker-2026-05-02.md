## Architecture Reset Progress Tracker

Use this document as the session handoff ledger for the architecture reset work. It records what is already done, what is validated, what was simplified on purpose, and what the next session should pick up without having to reconstruct the whole branch history.

## Current Status

- Branch: `refactor/architecture-reset`
- Strategy: single-user modular monolith with a few shared boundaries, not a microservice split
- Refactor style: small validated slices, checkpoint frequently, do not widen scope before a focused check passes
- Latest completed direction: finish Milestone 3 by making durable approvals explicit across Discord, scheduler, and browser/API while keeping lightweight confirms intentionally lightweight
- Immediate next milestone: Milestone 4
- Immediate next slice: shrink scheduler review decision ownership without reopening the approval model or the turn gateway

## Completed Planning Baseline

- Master plan written and frozen in [architecture-reset-master-plan-2026-05-02.md](c:/Users/user/OneDrive/Documents/PA/learning_agent/docs/plans/architecture-reset-master-plan-2026-05-02.md)
- Companion docs written for invariants, roadmap, debt register, target architecture, workflow map, and canonical state models
- The program-level decision is already made: keep the LLM-first workflow, preserve data, keep one shared conversation across Discord and browser, and refactor toward the smallest boundaries that remove real duplication

## Completed Implementation Slices

### Slice 1: Proposal and Concept Ownership

- Scoped pending proposals by `user_id`
- Scoped concept title uniqueness by user instead of globally
- Added migration coverage for proposal and concept ownership changes
- Result: proposal state and concept dedup rules no longer assume one global user

### Slice 2: Relation and Adapter User Activation

- Scoped relation repository behavior through concept ownership joins
- Added `current_user_scope` as the runtime entry-point primitive
- Activated explicit user scope across Discord commands, message handling, views, and local API chat
- Result: repositories and adapters stopped silently relying on the ambient default user in the main message flows

### Slice 3: Scheduler Boundary Simplification

- Simplified scheduler identity binding at the job execution boundary instead of threading user scope through each reminder helper
- Added a central rule that user-targeted jobs do not run when the scheduler has no bound user
- Result: scheduler ownership logic is simpler, less duplicated, and safer for API-hosted shared jobs

## Current Reset Scope

- Keep the existing multi-user groundwork as dormant infrastructure unless a later product decision revives it.
- Do not spend reset budget on browser identity UX or full multi-user activation.
- Spend reset budget on the real simplification targets: durable shared turn coordination, one canonical review lifecycle, and a clearer approval split.

### Slice 4: API Identity Boundary Simplification

- Moved API user scoping into the auth dependency so one request-level rule covers the full route surface
- Removed chat-only duplicate user scoping from the API adapter
- Added lightweight explicit API identity support through `X-Learning-User`
- Added browser client support for that header in the shared frontend API client
- Result: API identity is now a centralized boundary, not a route-by-route convention

### Slice 5: Durable Shared Turn Gateway

- Replaced the process-only chat serializer with a hybrid coordination model
- Kept the in-process mutex as a fast local guard
- Added a durable session-state lease as the authoritative cross-process turn lock
- Preserved the existing adapter call surface so Discord, API, and scheduler callers did not need new wiring
- Result: shared conversation work is no longer protected only by process-local state

### Slice 6: Shared Review Quiz Generation

- Extracted the repeated review payload to quiz-message flow into a shared helper in `services/review_flow.py`
- Moved chat, Discord `/review`, and scheduler review-send paths onto the same quiz-generation helper
- Kept delivery, reminder persistence, and transport-specific UI behavior at the caller boundary
- Result: the highest-duplication review generation path is now centralized without introducing a heavy Review service too early

### Slice 7: Review Resolution Simplification

- Reused the existing review-state resolver instead of hand-clearing pending review and reminder state in multiple places
- Collapsed repeated stored quiz-metadata reads inside `services/tools_assess.py`
- Collapsed repeated last-assess session stashes into one helper
- Result: assess and skip paths are smaller, less drift-prone, and still preserve the existing lifecycle split between pipeline-managed assess cleanup and skip-owned cleanup

### Slice 8: Review Recovery Helper Extraction

- Centralized single-quiz context binding in `services/review_state.py`
- Moved assess concept recovery onto one shared helper instead of repeating anchor, active-concept, and chat-history fallback logic inline
- Reused the same binding helper from review generation, pending-review recovery, and scheduler reminder resend paths
- Result: late-answer recovery and reminder-resolution paths now share the same core review-context behavior without introducing a heavyweight Review service

### Slice 9: Review Delivery Ownership Convergence

- Centralized successful interactive review delivery registration in `services/review_state.py`
- Moved scheduler review-send registration behind the same shared review-state boundary
- Moved scheduler reminder resend delivery updates behind the same shared helper instead of manual rebinding and counter updates in the scheduler
- Updated Discord button-driven review resend flows to register pending review state after successful send
- Result: manual review start, scheduled review send, reminder resend, and Discord button-driven quiz delivery now converge on one canonical review-state boundary without adding a heavyweight Review service

### Slice 10: Shared Learn Turn Execution

- Extracted the repeated command-turn execution sequence into a shared helper in `services/learn_turn.py`
- Moved both Discord message handling and browser/API learn-message handling onto the same fetch, parse, intercept, execute, and metadata path
- Kept caller-owned side effects such as intercepted-history writes at the adapter boundary instead of broadening the helper into a larger service layer
- Result: interactive command turns no longer drift across Discord and browser/API, while the boundary stays small and concrete

### Slice 11: Approval Source Alignment

- Replaced maintenance-only approved-action execution semantics with a shared source-aware executor
- Propagated proposal source through Discord views, browser/API action handling, and scheduler-delivered taxonomy proposals
- Stopped taxonomy approvals from executing and logging under maintenance semantics
- Result: durable approval behavior now preserves policy source where it matters without adding a heavyweight proposal service

### Slice 12: Durable Browser/API Proposal Actions

- Switched browser/API maintenance, taxonomy, and dedup proposal-review buttons from inline executable payloads to durable `proposal_id` plus stable `proposal_item_id` references
- Added proposal-payload update support in `db/proposals.py` so partial approve/reject operations can update the remaining durable row instead of deleting everything
- Reused existing pending proposal rows in browser/API `/maintain` and `/reorganize` flows instead of only mentioning them or creating duplicate rows
- Kept the existing frontend action envelope shape so the web client continues treating action payloads as opaque
- Result: durable proposal handling is now shared across Discord, scheduler, and browser/API, satisfying the Milestone 3 approval split without frontend runtime churn

## Verified State

The following checks passed for the current branch state before this tracker was written:

- `python -m pytest tests/test_scheduler_runtime.py tests/test_scheduler.py tests/test_scheduler_full.py tests/test_review_fallback.py -q -o "addopts="`
- Result: `25 passed`

- `python -m pytest tests/test_user_context_entrypoints.py tests/test_api.py -q -o "addopts="`
- Result: `91 passed`

- `npm test -- --run src/api.test.ts` from [frontend](c:/Users/user/OneDrive/Documents/PA/learning_agent/frontend)
- Result: `2 passed`

Additional focused checks passed after the latest slices:

- `python -m pytest tests/test_state_lock.py -q -o "addopts="`
- Result: `3 passed`

- `python -m pytest tests/test_user_context_entrypoints.py tests/test_scheduler_runtime.py -q -o "addopts="`
- Result: `11 passed`

- `python -m pytest tests/test_review_fallback.py -q -o "addopts="`
- Result: `5 passed`

- `python -m pytest tests/test_assess_no_quiz_guard.py tests/test_messages.py tests/test_quiz_views.py -q -o "addopts=" -k "assess or stale_quiz_answered or skip_quiz_clears_stale_active_concept or skip_quiz_blocked_when_no_active_quiz"`
- Result: `14 passed, 11 deselected`

- `python -m pytest tests/test_review_fallback.py tests/test_quiz_anchor.py tests/test_assess_no_quiz_guard.py tests/test_scheduler_full.py -q -o "addopts="`
- Result: `40 passed`

- `python -m pytest tests/test_review_fallback.py tests/test_scheduler.py tests/test_scheduler_full.py tests/test_quiz_views.py tests/test_messages.py tests/test_assess_no_quiz_guard.py tests/test_quiz_anchor.py -q -o "addopts="`
- Result: `61 passed`

- `python -m pytest tests/test_proposals.py tests/test_api.py -q -o "addopts="`
- Result: `93 passed`

- `python -m pytest c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_proposals.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_api.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_messages.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler_full.py -q -o "addopts="`
- Result: `106 passed`

- `npm test -- --run src/App.test.tsx -t "removes a proposal review item after a successful durable action"` from [frontend](c:/Users/user/OneDrive/Documents/PA/learning_agent/frontend)
- Result: `1 passed`

## Intentional Simplifications

- Scheduler user binding is handled once in [services/scheduler.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/scheduler.py), not spread across each job helper
- API request user binding is handled once in [api/auth.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/api/auth.py), not repeated in each route
- Browser/API identity is still local-first. The existing header path remains a lightweight bridge, not a reset driver
- Durable proposals are reserved for destructive or long-running flows; lightweight same-turn confirmations remain intentionally lightweight
- Browser/API proposal-review blocks keep the same outer action envelope; only the server-side payload changed from raw executable actions to durable proposal references

## Current Code Areas Touched In The Latest Validated Slice

- [services/state.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/state.py)
- [db/chat.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/db/chat.py)
- [services/review_flow.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/review_flow.py)
- [services/chat_session.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/chat_session.py)
- [bot/commands.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/bot/commands.py)
- [services/scheduler.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/scheduler.py)
- [services/tools_assess.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/tools_assess.py)
- [services/review_state.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/review_state.py)
- [tests/test_state_lock.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_state_lock.py)
- [tests/test_review_fallback.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_review_fallback.py)
- [tests/test_assess_no_quiz_guard.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_assess_no_quiz_guard.py)
- [tests/test_messages.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_messages.py)
- [tests/test_quiz_anchor.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_quiz_anchor.py)
- [tests/test_scheduler_full.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler_full.py)
- [services/views.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/views.py)
- [tests/test_quiz_views.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_quiz_views.py)
- [services/learn_turn.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/learn_turn.py)
- [db/proposals.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/db/proposals.py)
- [tests/test_proposals.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_proposals.py)
- [frontend/src/App.test.tsx](c:/Users/user/OneDrive/Documents/PA/learning_agent/frontend/src/App.test.tsx)

## Next Session Starting Point

Milestone 3 is complete. The next major decision is how far to shrink scheduler and runtime workflow ownership in Milestone 4 without prematurely inventing heavyweight services.

### New Session Bootstrap

Start the next session from this exact posture:

1. Treat Milestone 3 as done unless a regression falsifies it.
2. Do not reopen the turn gateway design; the durable lease-backed boundary is already landed.
3. Do not redesign the approval model; durable proposals and lightweight same-turn confirms are already intentionally split.
4. Start from `services/scheduler.py` and only step outward if the scheduler still owns a workflow decision that already exists elsewhere.
5. Validate the first scheduler slice before touching `services/pipeline.py`.

### First Milestone 4 Question

Which scheduler decisions still belong somewhere else?

Use this falsifiable test:

- If the scheduler is deciding review lifecycle policy that is already represented in `services/review_state.py`, `services/review_flow.py`, or `services/tools_assess.py`, move that decision out.
- If the scheduler is only deciding cadence, ownership, due-time triggering, or transport dispatch timing, keep it in the scheduler.

Recommended next options, in order:

1. Shrink remaining scheduler review decision branches so the scheduler owns cadence and dispatch, not review workflow policy.
2. Move more business-specific orchestration out of `services/pipeline.py` now that review and approval boundaries are stabilized.
3. Re-evaluate whether `services/learn_turn.py` needs any further simplification only if a third caller or materially different turn shape appears.

### Recommended First Milestone 4 Slice

- Start with scheduler review decision cleanup, not another service map.
- Use [services/scheduler.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/scheduler.py), [services/review_state.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/review_state.py), [services/review_flow.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/review_flow.py), and [services/tools_assess.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/tools_assess.py) as the first anchors.
- Keep owner election, cadence, and due-time checks in the scheduler.
- Move only workflow decisions that still duplicate logic already present in shared review helpers.
- Re-run [tests/test_scheduler_full.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler_full.py), [tests/test_scheduler.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler.py), [tests/test_review_fallback.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_review_fallback.py), and [tests/test_quiz_anchor.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_quiz_anchor.py) after the first scheduler slice.

### Explicit Non-Goals For The Next Session

- Do not introduce a new `ReviewService` class unless helper-level extraction clearly fails.
- Do not change browser identity, auth UX, or full multi-user activation.
- Do not replace the durable proposal store with a new proposal subsystem.
- Do not move generic prompt assembly or output validation out of `services/pipeline.py` until the first scheduler slice is validated.

### Ready-To-Run Validation Set

Use this narrow command after the first scheduler cleanup slice:

- `python -m pytest c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler_full.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_review_fallback.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_quiz_anchor.py -q -o "addopts="`

Use this broader checkpoint only after that narrow slice is green:

- `python -m pytest c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_proposals.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_api.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_messages.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler_full.py -q -o "addopts="`

## Guardrails For The Next Session

- Do not reintroduce route-level or helper-level scoping or coordination rules if a boundary-level solution exists.
- Prefer one binding rule per boundary: adapter boundary, request boundary, scheduler job boundary, turn boundary.
- Preserve the local-first deployment assumption unless there is a deliberate product decision to widen scope.
- Keep validating in narrow slices before widening to larger suites.