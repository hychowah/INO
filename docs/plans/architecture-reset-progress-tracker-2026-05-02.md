## Architecture Reset Progress Tracker

Use this document as the session handoff ledger for the architecture reset work. It records what is already done, what is validated, what was simplified on purpose, and what the next session should pick up without having to reconstruct the whole branch history.

## Current Status

- Branch: `refactor/architecture-reset`
- Strategy: user-scoped modular monolith, not a microservice split
- Refactor style: small validated slices, checkpoint frequently, do not widen scope before a focused check passes
- Latest completed direction: activate real per-user boundaries before extracting larger services

## Completed Planning Baseline

- Master plan written and frozen in [architecture-reset-master-plan-2026-05-02.md](c:/Users/user/OneDrive/Documents/PA/learning_agent/docs/plans/architecture-reset-master-plan-2026-05-02.md)
- Companion docs written for invariants, roadmap, debt register, target architecture, workflow map, and canonical state models
- The program-level decision is already made: keep the LLM-first workflow, preserve data, and refactor toward shared application services behind thin adapters

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

### Slice 4: API Identity Boundary Simplification

- Moved API user scoping into the auth dependency so one request-level rule covers the full route surface
- Removed chat-only duplicate user scoping from the API adapter
- Added lightweight explicit API identity support through `X-Learning-User`
- Added browser client support for that header in the shared frontend API client
- Result: API identity is now a centralized boundary, not a route-by-route convention

## Verified State

The following checks passed for the current branch state before this tracker was written:

- `python -m pytest tests/test_scheduler_runtime.py tests/test_scheduler.py tests/test_scheduler_full.py tests/test_review_fallback.py -q -o "addopts="`
- Result: `25 passed`

- `python -m pytest tests/test_user_context_entrypoints.py tests/test_api.py -q -o "addopts="`
- Result: `91 passed`

- `npm test -- --run src/api.test.ts` from [frontend](c:/Users/user/OneDrive/Documents/PA/learning_agent/frontend)
- Result: `2 passed`

## Intentional Simplifications

- Scheduler user binding is handled once in [services/scheduler.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/scheduler.py), not spread across each job helper
- API request user binding is handled once in [api/auth.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/api/auth.py), not repeated in each route
- Browser/API identity is still local-first. The new header path is a lightweight bridge, not a full auth system

## Current Code Areas Touched In The Latest Validated Slice

- [services/scheduler.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/scheduler.py)
- [api/auth.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/api/auth.py)
- [api/routes/chat.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/api/routes/chat.py)
- [frontend/src/api.ts](c:/Users/user/OneDrive/Documents/PA/learning_agent/frontend/src/api.ts)
- [frontend/src/api.test.ts](c:/Users/user/OneDrive/Documents/PA/learning_agent/frontend/src/api.test.ts)
- [tests/test_scheduler_runtime.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler_runtime.py)
- [tests/test_review_fallback.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_review_fallback.py)
- [tests/test_user_context_entrypoints.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_user_context_entrypoints.py)
- [tests/test_api.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_api.py)

## Next Session Starting Point

The next major blocker is no longer basic entry-point user activation. It is choosing how far to take browser identity UX versus continuing deeper service extraction.

Recommended next options, in order:

1. Build a minimal browser user switcher so `X-Learning-User` becomes usable without dev tools.
2. Move to scheduler and review delivery semantics for true multi-user behavior, especially reminder ownership and dispatch.
3. Start extracting the canonical Review service now that the user-boundary work is in place across Discord, API, and scheduler entry points.

## Guardrails For The Next Session

- Do not reintroduce route-level or helper-level user scoping if a boundary-level solution exists.
- Prefer one binding rule per boundary: adapter boundary, request boundary, scheduler job boundary, service boundary.
- Preserve the local-first deployment assumption unless there is a deliberate product decision to widen scope.
- Keep validating in narrow slices before widening to larger suites.