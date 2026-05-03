## Architecture Reset Progress Tracker

Use this document as the session handoff ledger for the architecture reset work. It records what is already done, what is validated, what was simplified on purpose, and what the next session should pick up without having to reconstruct the whole branch history.

## Current Status

- Branch: `refactor/architecture-reset`
- Strategy: single-user modular monolith with a few shared boundaries, not a microservice split
- Refactor style: small validated slices, checkpoint frequently, do not widen scope before a focused check passes
- Latest completed direction: Milestone 5 is complete after explicit chat-envelope hardening, typed-only reminder state cutover, shared Discord proposal execution, slash-command delegation onto the shared chat controller, final acceptance, and shadow-data rehearsal
- Immediate next milestone: none required for the reset
- Immediate next slice: monitor for regressions or start post-reset work on a new plan

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

### Slice 13: Canonical Local Identity And Runtime Sessions

- Added `LEARN_LOCAL_USER_ID` as the canonical local-first single-user alias
- Bound API default user resolution, Discord command/message flows, views, and scheduler jobs to that alias instead of scattering raw user-id decisions across adapters
- Scoped interactive provider conversation sessions per current user in `services/pipeline.py` instead of keeping one process-global session cache
- Result: local-first single-user identity is now explicit at the boundary, and provider-session continuity no longer leaks across scoped users

### Slice 14: Shared Interactive Turn Preamble

- Added `begin_interactive_turn()` in `services/state.py` to centralize activity heartbeat and `quiz_answered` reset
- Reused that helper from Discord message handling and browser/API chat handling instead of duplicating the pre-turn setup inline
- Moved chat serialization ownership inward to the shared chat controller so API routes stop wrapping the same service calls manually
- Result: turn-entry bookkeeping is smaller, less drift-prone, and owned by one boundary-level rule instead of repeated adapter code

### Slice 15: Lightweight Approval Parity

- Added shared lightweight confirm/decline executors for `add_concept` and `suggest_topic` in `services/chat_actions.py`
- Reused the same approval side effects from browser/API chat confirmation, Discord button views, and reply-based Discord pending confirmations
- Preserved transport-specific rendering at the edges while forcing domain outcome and audit/history markers through one path
- Result: lightweight confirmation behavior now matches across surfaces without widening into a generic proposal framework

### Slice 16: Review Payload And Reminder Policy Extraction

- Extracted canonical single-concept review payload construction into `services/pipeline.py`
- Reused the same payload builder from both interactive review selection and scheduler due-only review selection while preserving the intended fallback difference
- Moved scheduler reminder-policy decisions into `services/review_state.py`, including deleted-concept cancellation and cooldown/expiry decisions
- Result: scheduler keeps cadence and delivery ownership, while shared review helpers own the last meaningful reminder-state policy branches

### Slice 17: Milestone 4 Validation And Rebaseline

- Re-ran focused validation after each identity, turn-entry, approval, and scheduler slice
- Confirmed the broader milestone checkpoint for identity/session handling, approvals, review/scheduler behavior, output-contract safety, and proposal persistence
- Rebased the architecture reset docs to mark Milestone 5 as the active workstream
- Result: Milestone 4 is complete in code and documented as such for the next session

### Slice 18: Explicit Chat Envelope Contract

- Tightened `api/schemas.py` so the chat envelope is explicit instead of open-ended
- Added route-level response filtering so optional fields remain omitted on the wire unless set
- Preserved the existing browser/API payload shape while removing backend contract drift
- Result: the HTTP chat surface now has one concrete envelope boundary instead of ad hoc permissiveness

### Slice 19: Typed-Only Review Reminder State

- Moved active-review reads onto `scheduled_review_reminders` as the sole durable source of truth
- Stopped writing new `pending_review` session blobs for interactive or scheduler delivery
- Removed the final legacy import bridge so delayed-answer recovery, prompt context injection, scheduler resend, and reminder resolution all operate on the typed reminder row only
- Result: review recovery and reminder cadence now share one state model instead of a mirrored bridge

### Slice 20: Discord Proposal Execution Delegation

- Routed Discord proposal views through the shared chat-action dispatcher instead of duplicating proposal application, rejection logging, and remaining-item persistence in `services/views.py`
- Kept Discord button UI state at the edge while moving proposal outcomes onto the same domain path already used by browser/API
- Result: proposal execution now has one owner across browser/API, Discord buttons, and scheduler-delivered proposals

### Slice 21: Slash Command Workflow Cutover

- Moved Discord `/maintain` and `/reorganize` onto the shared chat controller rather than keeping transport-local workflow orchestration in `bot/commands.py`
- Added a thin Discord-only proposal-block renderer that reconstructs Discord views from durable proposal rows returned by the shared controller
- Preserved the richer Discord `/review` transport flow because replacing it would not have delivered proportional simplification
- Result: the remaining high-value slash-command workflow duplication is removed without introducing a new adapter framework

### Slice 22: Milestone 5 Closeout Validation And Rehearsal

- Re-ran the broad Python acceptance checkpoint after the final reminder-state, proposal, slash-command, and migration-init fixes
- Re-ran the targeted frontend chat/API tests for the explicit chat envelope and durable proposal UI behavior
- Performed a safe shadow-data rehearsal by copying `data/knowledge.db`, `data/chat_history.db`, and `data/vectors` into a temp directory, booting the repo against those copies via env overrides, and verifying schema migration plus representative table counts on the copied data
- Fixed one real migration-init defect exposed by that rehearsal: user-id-dependent indexes were being created before migrations had added the needed columns on older databases
- Result: Milestone 5 now has a validation record and a shadow-data rehearsal record, so the reset can be considered complete

## Verified State

Historical validated results preserved from earlier slices:

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

Latest working-tree validation recorded for the current slice set:

- `python -m pytest tests/test_user_context_entrypoints.py tests/test_pipeline_sessions.py tests/test_api.py tests/test_quiz_views.py -q -o "addopts="`
- Result: `108 passed`

- `python -m pytest tests/test_api.py tests/test_concept_confirm.py tests/test_suggest_topic_confirm.py tests/test_quiz_views.py -q -o "addopts="`
- Result: `126 passed`

- `python -m pytest tests/test_scheduler.py tests/test_scheduler_full.py tests/test_review_fallback.py tests/test_quiz_anchor.py -q -o "addopts="`
- Result: `36 passed`

- `python -m pytest tests/test_user_context_entrypoints.py tests/test_pipeline_sessions.py tests/test_api.py tests/test_concept_confirm.py tests/test_suggest_topic_confirm.py tests/test_messages.py tests/test_quiz_views.py tests/test_scheduler.py tests/test_scheduler_full.py tests/test_review_fallback.py tests/test_quiz_anchor.py tests/test_output_contract.py tests/test_proposals.py -q -o "addopts="`
- Result: `192 passed`

Latest Milestone 5 slice validation:

- `python -m pytest tests/test_api.py -q -o "addopts="`
- Result: `89 passed`

- `python -m pytest tests/test_review_fallback.py tests/test_quiz_anchor.py tests/test_assess_no_quiz_guard.py tests/test_scheduler.py tests/test_scheduler_full.py tests/test_quiz_views.py -q -o "addopts="`
- Result: `56 passed`

- `python -m pytest tests/test_proposals.py tests/test_scheduler.py tests/test_review_fallback.py -q -o "addopts="`
- Result: `21 passed`

- `python -m pytest tests/test_api.py tests/test_review_fallback.py tests/test_quiz_anchor.py tests/test_assess_no_quiz_guard.py tests/test_scheduler.py tests/test_scheduler_full.py tests/test_quiz_views.py -q -o "addopts="`
- Result: `147 passed`

- `python -m pytest c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_api.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_review_fallback.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_quiz_anchor.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_assess_no_quiz_guard.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler_full.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_quiz_views.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_proposals.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_messages.py -q -o "addopts="`
- Result: `159 passed`

- `npm test -- --run src/api.test.ts src/App.test.tsx` from [frontend](c:/Users/user/OneDrive/Documents/PA/learning_agent/frontend)
- Result: `12 passed`

- Shadow-data rehearsal: copied local `data/knowledge.db`, `data/chat_history.db`, and `data/vectors` to a temp directory, set `LEARN_DB_PATH`, `LEARN_CHAT_DB_PATH`, and `LEARN_VECTOR_STORE_PATH` to those copies, ran `db.init_databases()`, and verified schema version `18` plus representative counts (`topics=45`, `concepts=117`, `review_log=668`, `scheduled_review_reminders=1`, `pending_proposals=0`, `conversations=105`, `session_state=13`)

## Intentional Simplifications

- Scheduler user binding is handled once in [services/scheduler.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/scheduler.py), not spread across each job helper
- API request user binding is handled once in [api/auth.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/api/auth.py), not repeated in each route
- Browser/API identity remains local-first. `LEARN_LOCAL_USER_ID` is the canonical default alias, and `X-Learning-User` stays a lightweight override rather than a reset driver
- Interactive turn setup is handled once in [services/state.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/state.py), not reimplemented per adapter
- Durable proposals are reserved for destructive or long-running flows; lightweight same-turn confirmations remain intentionally lightweight
- Browser/API proposal-review blocks keep the same outer action envelope; only the server-side payload changed from raw executable actions to durable proposal references
- The existing `call_action_loop()` plus `execute_approved_actions()` pair is already the automation-runner pattern; no extra maintenance/taxonomy service layer was introduced
- Review reminders are now typed-only; `pending_review` no longer participates in new writes or late-answer recovery
- Discord proposal views and slash maintenance/taxonomy commands now reuse the shared chat controller or shared chat-action dispatcher instead of owning duplicate proposal workflow

## Current Code Areas Touched In The Latest Validated Slice

- [config.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/config.py)
- [api/auth.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/api/auth.py)
- [api/routes/chat.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/api/routes/chat.py)
- [bot/commands.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/bot/commands.py)
- [bot/events.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/bot/events.py)
- [services/state.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/state.py)
- [db/chat.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/db/chat.py)
- [services/review_flow.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/review_flow.py)
- [services/chat_session.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/chat_session.py)
- [services/chat_actions.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/chat_actions.py)
- [services/scheduler.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/scheduler.py)
- [services/tools_assess.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/tools_assess.py)
- [services/review_state.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/review_state.py)
- [services/pipeline.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/pipeline.py)
- [tests/test_state_lock.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_state_lock.py)
- [tests/test_user_context_entrypoints.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_user_context_entrypoints.py)
- [tests/test_pipeline_sessions.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_pipeline_sessions.py)
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
- [tests/test_suggest_topic_confirm.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_suggest_topic_confirm.py)
- [frontend/src/App.test.tsx](c:/Users/user/OneDrive/Documents/PA/learning_agent/frontend/src/App.test.tsx)

## Next Session Starting Point

Milestone 5 is complete. The next session should start from a new plan rather than reopening the reset.

### New Session Bootstrap

Start the next session from this exact posture:

1. Treat the explicit chat contract, typed-only reminder state, shared Discord proposal execution, slash maintenance/taxonomy cutover, and migration-init fix as done unless a focused regression falsifies them.
2. Do not reopen the local alias decision, turn-entry preamble, lightweight approval seam, or the decision to keep `/review` as a richer Discord transport flow.
3. Start any new work from user-visible product needs or concrete bugs, not from more architecture cleanup.
4. Keep `api/auth.py` as the fixed request-scope identity boundary, `services/chat_actions.py` as the lightweight approval executor, and `services/review_state.py` as the sole active-review state owner.
5. If a real-data issue appears, repair only that local slice instead of reopening the reset target.

### First Milestone 5 Question

Which adapter-owned workflow branches still exist and can be removed without changing domain behavior?

Use this falsifiable test:

- If a route, view, or callback still owns domain workflow that already exists in `services/chat_session.py`, `services/chat_actions.py`, `services/review_state.py`, or `services/review_flow.py`, move that branch inward.
- If the code only translates transport concerns, rendering, or user interaction primitives, keep it at the adapter edge.

Recommended next options, in order:

1. Harden the HTTP chat boundary so service contracts are explicit and adapters stop relying on ad hoc envelopes internally.
2. Reduce remaining Discord view/callback domain ownership where the shared helper path already exists.
3. Retire the reminder compatibility bridge only after the parity suite and migration rehearsal prove the typed reminder path is sufficient.

### Recommended First Milestone 5 Slice

- Start at the API chat adapter seam, not another service map.
- Use [api/routes/chat.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/api/routes/chat.py), [services/chat_session.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/chat_session.py), [api/auth.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/api/auth.py), and [services/chat_actions.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/chat_actions.py) as the first anchors.
- Keep request-scope identity in the auth dependency and domain workflow in the shared chat controller.
- Move only the remaining adapter-owned workflow branches that still duplicate shared behavior.
- Re-run [tests/test_api.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_api.py), [tests/test_user_context_entrypoints.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_user_context_entrypoints.py), and the relevant approval/review parity suites after the first slice.

### Explicit Non-Goals For The Next Session

- Do not introduce a new `ReviewService` class unless helper-level extraction clearly fails.
- Do not change browser identity, auth UX, or full multi-user activation.
- Do not replace the durable proposal store with a new proposal subsystem.
- Do not move generic prompt assembly or output validation out of `services/pipeline.py` unless a concrete business-policy leak still remains after adapter cleanup.

### Ready-To-Run Validation Set

Use this narrow command after the first Milestone 5 adapter slice:

- `python -m pytest c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_api.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_user_context_entrypoints.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_concept_confirm.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_suggest_topic_confirm.py -q -o "addopts="`

Use this broader checkpoint only after that narrow slice is green:

- `python -m pytest c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_user_context_entrypoints.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_pipeline_sessions.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_api.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_concept_confirm.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_suggest_topic_confirm.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_messages.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_quiz_views.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler_full.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_review_fallback.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_quiz_anchor.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_output_contract.py c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_proposals.py -q -o "addopts="`

## Commit-Prep Notes

- Canonical local identity now flows through `LEARN_LOCAL_USER_ID`, `services/state.py`, and `api/auth.py`; do not describe the runtime as default-user-only anymore.
- Interactive turn setup is centralized in `services/state.py`; adapters should not duplicate activity heartbeat or `quiz_answered` reset.
- API routes no longer own outer serialization; the shared chat controller now owns that boundary.
- Lightweight `add_concept` and `suggest_topic` approvals share one executor in `services/chat_actions.py` and one audit/history contract across Discord and browser/API.
- Scheduler reminder-policy decisions now live in `services/review_state.py`, and review payload construction is shared in `services/pipeline.py`.
- The current broader checkpoint is `192 passed` on the recorded command above; use that as the last known-good pre-commit validation baseline.

## Guardrails For The Next Session

- Do not reintroduce route-level or helper-level scoping or coordination rules if a boundary-level solution exists.
- Prefer one binding rule per boundary: adapter boundary, request boundary, scheduler job boundary, turn boundary.
- Preserve the local-first deployment assumption unless there is a deliberate product decision to widen scope.
- Keep validating in narrow slices before widening to larger suites.