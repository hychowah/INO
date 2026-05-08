# Architecture Simplification Progress Tracker

## Current Status

| Field | Value |
|---|---|
| Overall status | In progress |
| Active phase | Phase 4 pipeline split, with earlier Phase 3 and Phase 5 slices complete |
| Current objective | Move prompt-loading and prompt-cache responsibilities out of `services/pipeline.py` while preserving the existing public pipeline surface |
| Next implementation target | Choose the next coherent `services/pipeline.py` responsibility slice after prompt ownership, likely LLM-call helpers or preference-edit flow |

## Baseline Metrics

### Runtime Areas

| Area | Files | LOC |
|---|---:|---:|
| `services/` | 23 | 6,987 |
| `bot/` | 7 | 796 |
| `api/` | 13 | 809 |
| `db/` | 15 | 4,019 |
| `frontend/src/` | 48 | 6,330 |
| **Runtime total** | **106** | **18,941** |

### Secondary Areas

| Area | Files | LOC |
|---|---:|---:|
| `tests/` | 56 | 9,345 |
| `scripts/` | 10 | 2,573 |
| `docs/` | 9 | 2,064 |

### Production Class Count

| Metric | Count |
|---|---:|
| Total production classes | 42 |
| `services/` classes | 29 |
| `api/` classes | 13 |
| `bot/` classes | 0 |
| `db/` classes | 0 |
| `frontend/src/` classes | 0 |

## Hotspot File Baseline

| Path | LOC | Tracker note |
|---|---:|---|
| `services/pipeline.py` | 1,113 | Primary backend hotspot |
| `services/context.py` | 816 | Keep necessary prompt-context logic, reduce only when ownership is clearer |
| `frontend/src/pages/ChatPage.tsx` | 698 | Primary frontend hotspot |
| `db/concepts.py` | 664 | Large DB surface, monitor for future split only if still growing |
| `services/views.py` | 620 | Discord UI boilerplate hotspot |
| `services/scheduler.py` | 587 | Broad runtime responsibility surface |
| `services/tools.py` | 584 | Core action executor, protect behavior while simplifying |
| `services/tools_assess.py` | 466 | Review and quiz logic hotspot |
| `services/chat_session.py` | 424 | Shared chat controller and current transport-logic hotspot |
| `bot/commands.py` | 398 | Transport duplication target |
| `api/routes/chat.py` | 124 | Keep thin |

## Confirmed Duplication Baseline

| Metric | Count | Evidence |
|---|---:|---|
| Synthetic slash-to-chat routes | 2 | `/maintain` and `/reorganize` in `bot/commands.py` |
| Duplicate review entry flows | 2 | One flow in `services/chat_session.py`, one in `bot/commands.py` |

## Current Metrics After Latest Slice

| Metric | Current | Delta vs baseline | Notes |
|---|---:|---:|---|
| Synthetic slash-to-chat routes in `bot/commands.py` | 0 | -2 | Removed by direct shared maintenance and taxonomy request entrypoints |
| Duplicate review orchestration paths | 0 | -2 | `handle_review_check()` is now centralized in `services/chat_session.py`; the bot uses `handle_review_request()` |
| Confirmed review execution branches in `services/chat_session.py` | 0 | n/a | `maintenance_review` and `taxonomy_review` execution now delegate to `services.chat_admin.execute_confirmed_review()` |
| `services/chat_session.py` LOC | 323 | -101 | Chat-only quiz button derivation moved into `services/chat_quiz.py`, shrinking the controller back below baseline |
| `bot/commands.py` LOC | 385 | -13 | Bot transport code is thinner for the targeted commands |
| `services/chat_admin.py` LOC | 428 | n/a | Shared proposal/admin owner now also handles confirmed maintenance and taxonomy execution |
| `services/chat_quiz.py` LOC | 123 | n/a | New shared owner for browser/API quiz follow-up button derivation |
| `services/pipeline.py` LOC | 1,007 | -106 | Prompt-loading and prompt-cache implementation moved out of the orchestrator |
| `services/context.py` LOC | 922 | +106 | Prompt skill loading, prompt caching, and system-prompt composition now live with other prompt-building logic |
| Runtime LOC total | 18,969 | +28 | New seam improved ownership but increased runtime LOC; this increase must be repaid in a later consolidation slice |

## Phase Tracker

| Phase | Status | Completion signal | Notes |
|---|---|---|---|
| 0. Planning artifacts | Completed | Both `docs/plans` files exist and doc indexes point to them | Completed |
| 1. Core boundary | Not started | Shared-core boundary accepted and referenced by active work | |
| 2. Baseline metrics | Completed | Tracker contains area LOC, hotspot LOC, duplication counts, and validation targets | Completed with filtered source-only baseline |
| 3. Transport flattening | In progress | Confirmed synthetic routes reduced and shared services own command logic | `/maintain`, `/reorganize`, and review request orchestration now use shared direct request entrypoints |
| 4. Pipeline split | In progress | `services/pipeline.py` responsibilities reduced without behavior drift | Prompt-loading and prompt-cache ownership moved into `services/context.py` |
| 5. Review and proposal ownership | In progress | Fewer modules participate in the same review and proposal-confirm flows | Confirmed maintenance and taxonomy review execution moved into `services/chat_admin.py` |
| 6. Optional subsystem boundaries | Not started | Operator-only and optional concerns are more explicit | |
| 7. UI hotspot cleanup | Not started | Discord and frontend hotspot files shrink with stable behavior | |
| 8. Framework fit review | Not started | Keep-both-equal decision revisited using post-refactor metrics | |

## Implementation Log

| Slice | Outcome |
|---|---|
| Planning bootstrap | Created master plan and tracker documents, recorded the first filtered line-count baseline, and confirmed the first duplication targets |
| Direct maintenance and taxonomy entrypoints | Removed the synthetic Discord `/maintain` and `/reorganize` chat-message routing by adding shared direct request entrypoints in `services/chat_session.py` and rewiring `bot/commands.py` |
| Shared review request orchestration | Centralized manual review selection and quiz generation in `services/chat_session.py` so `bot/commands.py` now projects a shared review request result instead of owning the orchestration itself |
| Shared proposal-confirm execution | Moved confirmed `maintenance_review` and `taxonomy_review` execution out of `services/chat_session.py` and into `services/chat_admin.py`, with new API regression coverage for both confirm flows |
| Shared chat quiz-action seam | Extracted browser/API quiz follow-up button derivation from `services/chat_session.py` into `services/chat_quiz.py`, reducing the chat controller hotspot while preserving behavior |
| Prompt ownership move | Moved skill loading, prompt caching, and system-prompt composition out of `services/pipeline.py` and into `services/context.py`, while preserving the pipeline public surface through compatibility aliases |

## Validation Log

| Slice | Validation |
|---|---|
| Planning bootstrap | Source metrics collected from filtered PowerShell file walk; no runtime code changed |
| Direct maintenance and taxonomy entrypoints | `python -m pytest tests/test_proposals.py -k "maintain_command_uses_shared_maintenance_request_for_proposals or reorganize_command_uses_shared_reorganize_request_for_proposals" -q` passed: 2 passed |
| Shared review request orchestration | `python -m pytest tests/test_review_fallback.py -k "chat_review_registers_typed_review_reminder or test_generate_review_quiz_from_payload_tolerates_none_choices or test_bot_review_fallback_uses_review_check_mode or test_bot_review_does_not_persist_pending_when_send_fails" -q` passed: 4 passed |
| Shared proposal-confirm execution | `python -m pytest tests/test_api.py -k "confirm_maintenance_review_uses_shared_admin_executor or confirm_taxonomy_review_uses_shared_admin_executor or chat_action_taxonomy_uses_taxonomy_source" -q` passed: 3 passed |
| Shared chat quiz-action seam | `python -m pytest tests/test_user_context_entrypoints.py -k "chat_action_skip_uses_current_scoped_user" -q` passed: 1 passed; `python -m pytest tests/test_review_fallback.py -k "chat_review_registers_typed_review_reminder" -q` passed: 1 passed |
| Prompt ownership move | `python -m pytest tests/test_skill_loading.py tests/test_pipeline_sessions.py tests/test_persona.py -q` passed: 33 passed |

## Next Actions

1. Choose the next `services/pipeline.py` responsibility slice, likely LLM-call helpers or preference-edit flow, using the same narrow extraction approach.
2. Repay the current +28 runtime LOC increase by consolidating nearby seams instead of only extracting more files.
3. Reassess whether `services/chat_quiz.py` should remain a stable owner or be merged later once the browser/API chat seams settle.