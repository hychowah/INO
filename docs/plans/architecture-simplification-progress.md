# Architecture Simplification Progress Tracker

## Current Status

| Field | Value |
|---|---|
| Overall status | In progress |
| Active phase | Phase 5A review ownership, with canonical review payload/check helpers plus structured quiz generation and deterministic delivery formatting now owned by `services/review_flow.py` |
| Current objective | Continue shrinking `services/pipeline.py` by paying down remaining non-review orchestration and compatibility seams without regressing scheduler, chat, or Discord behavior |
| Next implementation target | Choose the next lowest-risk extraction from `services/pipeline.py`, most likely maintenance/taxonomy orchestration, now that prompt-building aliases and review-specific helpers are out |

## Baseline Metrics

### Runtime Areas

| Area | Files | LOC |
|---|---:|---:|
| `services/` | 25 | 7,109 |
| `bot/` | 7 | 796 |
| `api/` | 13 | 809 |
| `db/` | 15 | 4,019 |
| `frontend/src/` | 48 | 6,330 |
| **Runtime total** | **108** | **19,063** |

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
| Duplicate review orchestration paths | 0 | -2 | Review entry and generation now route through shared `services/chat_session.py` and `services/review_flow.py` surfaces rather than transport-owned orchestration |
| Confirmed review execution branches in `services/chat_session.py` | 0 | n/a | `maintenance_review` and `taxonomy_review` execution now delegate to `services.chat_admin.execute_confirmed_review()` |
| `bot/commands.py` LOC | 385 | -13 | Bot transport code is thinner for the targeted commands |
| `services/chat_admin.py` LOC | 428 | n/a | Shared proposal/admin owner now also handles confirmed maintenance and taxonomy execution |
| `services/chat_quiz.py` LOC | 123 | n/a | New shared owner for browser/API quiz follow-up button derivation |
| `services/pipeline.py` LOC | 481 | -632 | Conversation-session state, raw LLM/runtime helper logic, the fetch loop, review-specific helpers, and prompt-building alias surface now live behind shared owners; the file is concentrating further on remaining orchestration and direct prompt-context usage |
| `services/context.py` LOC | 922 | +106 | Prompt skill loading, prompt caching, and system-prompt composition now live with other prompt-building logic |
| `services/llm_runtime.py` LOC | 334 | n/a | Shared runtime owner now includes the fetch loop along with conversation sessions, output-contract retry/logging, and raw provider-call helpers |
| `services/chat_session.py` LOC | 337 | -87 | Shared chat controller now uses a local `call_with_fetch_loop` alias bound to `services.llm_runtime.call_with_fetch_loop`, preserving an API-facing patch seam without routing normal learn turns back through the pipeline facade |
| `services/review_flow.py` LOC | 274 | n/a | Review-flow ownership now includes canonical review payload/check helpers, structured quiz generation, deterministic delivery formatting, and runtime-backed quiz fallback generation |
| Runtime LOC total | 19,063 | +122 | Ownership is clearer across Phase 4A, Phase 4B, and Phase 5A review-generation moves; the remaining growth now mostly reflects deliberate shared review/admin seams and a smaller set of compatibility surfaces |

## Phase Tracker

| Phase | Status | Completion signal | Notes |
|---|---|---|---|
| 0. Planning artifacts | Completed | Both `docs/plans` files exist and doc indexes point to them | Completed |
| 1. Core boundary | Not started | Shared-core boundary accepted and referenced by active work | |
| 2. Baseline metrics | Completed | Tracker contains area LOC, hotspot LOC, duplication counts, and validation targets | Completed with filtered source-only baseline |
| 3. Transport flattening | In progress | Confirmed synthetic routes reduced and shared services own command logic | `/maintain`, `/reorganize`, and review request orchestration now use shared direct request entrypoints |
| 4. Pipeline split | In progress | `services/pipeline.py` responsibilities reduced without behavior drift | Prompt-loading and prompt-cache ownership moved into `services/context.py`; Phase 4A extracted conversation-session, raw LLM runtime helpers, and the fetch loop into `services/llm_runtime.py`, and Phase 4B moved `review_flow`, `chat_session`, and `bot.handler` off the pipeline fetch-loop facade before deleting the public fetch-loop wrapper |
| 5. Review and proposal ownership | In progress | Fewer modules participate in the same review and proposal-confirm flows | Confirmed maintenance and taxonomy review execution moved into `services/chat_admin.py`; Discord lightweight confirms, preference approval, and quiz follow-up dispatch now delegate through shared confirm/chat-action surfaces; Phase 5A has now moved both canonical review payload/check ownership and structured quiz-generation ownership into `services/review_flow.py` |
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
| Shared LLM runtime helper seam | Moved conversation-session state, output-contract retry/logging, and raw provider-call helpers out of `services/pipeline.py` and into `services/llm_runtime.py`, while deliberately keeping `call_with_fetch_loop()` in `services/pipeline.py` so existing fetch-loop tests and patch seams stayed stable during the first extraction step |
| Shared LLM fetch-loop seam | Moved the fetch-loop implementation into `services/llm_runtime.py` and reduced `services/pipeline.py` to a wrapper that injects the existing `_call_llm` and `_call_llm_followup` aliases so current monkeypatch-heavy tests keep working |
| Review-flow runtime migration | Moved `services/review_flow.py` off `services.pipeline.call_with_fetch_loop()` and onto a local alias of the shared runtime seam, so review-quiz fallback no longer depends on the pipeline facade for fetch-loop ownership |
| Chat-session runtime migration | Moved `services/chat_session.py` off `services.pipeline.call_with_fetch_loop()` and onto a local alias of the shared runtime seam, so normal API/browser learn turns no longer depend on the pipeline facade for fetch-loop ownership |
| Bot-handler runtime migration and alias paydown | Moved `bot/handler.py` off `services.pipeline.call_with_fetch_loop()` and onto a local alias of the shared runtime seam, then retargeted output-contract helper consumers to `services.llm_runtime.py` so redundant runtime-format aliases could be deleted from `services/pipeline.py` |
| Session-helper alias paydown | Retargeted session-lifecycle tests to `services.llm_runtime.py` and removed the redundant `_conv_sessions`, `_get_conv_session()`, and `_make_isolated_session_name()` aliases from `services/pipeline.py` |
| Fetch-loop wrapper removal | Retargeted the remaining direct test and smoke-script consumers to `services.llm_runtime.call_with_fetch_loop()`, then deleted the public `services.pipeline.call_with_fetch_loop()` wrapper and moved the internal action loops onto a local runtime alias |
| Review payload/check ownership move | Moved `build_review_payload()` and `handle_review_check()` into `services/review_flow.py`, rewired `services/chat_session.py` and `services/scheduler.py` onto local aliases of the new owner, and removed the old helper definitions from `services/pipeline.py` |
| Review quiz-generation ownership move | Moved `_quiz_generator_system_prompt()`, structured Prompt 1 validation, `generate_quiz_question()`, and `format_quiz_action()` into `services/review_flow.py`, rewired the review flow to call local helpers, and reduced `services/pipeline.py` to compatibility wrappers for the old import surface |
| Persona-path compatibility retirement | Moved persona-switch session reset calls directly to `services.llm_runtime.reset_conversation_session()`, moved prompt-cache invalidation calls directly to `services.context.invalidate_prompt_cache()`, deleted `pipeline.reset_conversation_session()`, removed the dead quiz-generation compatibility wrappers, and retargeted the remaining test-only cache invalidation import to `services.context` |
| Prompt-building alias retirement | Moved prompt-building imports in tests and scripts directly to `services.context.py`, removed `SKILLS_DIR`, `PREFERENCES_MD_PATH`, `SKILL_SETS`, `_mode_to_skill_set`, `_get_base_prompt`, and `build_system_prompt` aliases from `services/pipeline.py`, and kept only direct internal `context` calls for preference-edit prompt assembly and file writes |
| Shared Discord confirm delegation | Moved Discord button-confirm and reply-confirm execution onto one shared lightweight confirm resolver, and rewired Discord `/preference` approval to use the same pending-confirm contract as chat/API |
| Shared Discord quiz helper ownership | Moved quiz follow-up prompt construction and skip execution into `services/chat_quiz.py`, with `services/views.py` and `services/chat_session.py` consuming the shared helpers instead of synthesizing prompts or calling `skip_quiz()` directly |
| Typed quiz follow-up actions | Replaced quiz follow-up pseudo-message dispatch with explicit `quiz_followup` actions, routed Discord quiz buttons through `handle_chat_action()`, and taught `bot/messages.py` to reconstruct Discord quiz views from shared `payload.actions` |

## Validation Log

| Slice | Validation |
|---|---|
| Planning bootstrap | Source metrics collected from filtered PowerShell file walk; no runtime code changed |
| Direct maintenance and taxonomy entrypoints | `python -m pytest tests/test_proposals.py -k "maintain_command_uses_shared_maintenance_request_for_proposals or reorganize_command_uses_shared_reorganize_request_for_proposals" -q` passed: 2 passed |
| Shared review request orchestration | `python -m pytest tests/test_review_fallback.py -k "chat_review_registers_typed_review_reminder or test_generate_review_quiz_from_payload_tolerates_none_choices or test_bot_review_fallback_uses_review_check_mode or test_bot_review_does_not_persist_pending_when_send_fails" -q` passed: 4 passed |
| Shared proposal-confirm execution | `python -m pytest tests/test_api.py -k "confirm_maintenance_review_uses_shared_admin_executor or confirm_taxonomy_review_uses_shared_admin_executor or chat_action_taxonomy_uses_taxonomy_source" -q` passed: 3 passed |
| Shared chat quiz-action seam | `python -m pytest tests/test_user_context_entrypoints.py -k "chat_action_skip_uses_current_scoped_user" -q` passed: 1 passed; `python -m pytest tests/test_review_fallback.py -k "chat_review_registers_typed_review_reminder" -q` passed: 1 passed |
| Prompt ownership move | `python -m pytest tests/test_skill_loading.py tests/test_pipeline_sessions.py tests/test_persona.py -q` passed: 33 passed |
| Shared LLM runtime helper seam | `python -m pytest tests/test_output_contract.py tests/test_pipeline_sessions.py tests/test_quiz_anchor.py -q` passed: 29 passed |
| Shared LLM fetch-loop seam | `python -m pytest tests/test_output_contract.py tests/test_pipeline_sessions.py tests/test_quiz_anchor.py tests/test_learn_turn.py -q` passed: 31 passed |
| Review-flow runtime migration | `python -m pytest tests/test_review_fallback.py -q` passed: 6 passed |
| Chat-session runtime migration | `python -m pytest tests/test_api.py -k "test_chat_normal_reply or test_chat_stream_returns_status_and_done_events or test_chat_add_concept_returns_pending_confirm or test_chat_suggest_topic_returns_pending_confirm" -q` passed: 4 passed |
| Bot-handler runtime migration and alias paydown | `python -m pytest tests/test_user_context_entrypoints.py -k "test_handle_user_message_sets_context_from_explicit_user_id" -q` passed: 1 passed; `python -m pytest tests/test_output_contract.py -q` passed: 9 passed |
| Session-helper alias paydown | `python -m pytest tests/test_pipeline_sessions.py -q` passed: 2 passed |
| Fetch-loop wrapper removal | `python -m pytest tests/test_quiz_anchor.py tests/test_taxonomy_shadow_rebuild.py -k "test_fetch_during_quiz_preserves_anchor or test_fetch_without_quiz_sets_active or test_call_taxonomy_loop_forwards_overrides or test_taxonomy_loop_reuses_session_and_records_created_topic" -q` passed: 4 passed |
| Review payload/check ownership move | `python -m pytest tests/test_review_fallback.py tests/test_scheduler.py tests/test_scheduler_full.py -q` passed: 21 passed |
| Review quiz-generation ownership move | `python -m pytest tests/test_quiz_pipeline.py tests/test_review_fallback.py tests/test_scheduler.py tests/test_quiz_generator_script.py -q` passed: 23 passed |
| Persona-path compatibility retirement | `python -m pytest tests/test_pipeline_sessions.py tests/test_api.py tests/test_persona.py tests/test_skill_loading.py -q` passed: 124 passed; `python -m pytest tests/test_quiz_pipeline.py tests/test_review_fallback.py tests/test_scheduler.py tests/test_quiz_generator_script.py tests/test_pipeline_sessions.py -q` passed: 25 passed |
| Prompt-building alias retirement | `python -m pytest tests/test_skill_loading.py tests/test_persona.py -q` passed: 31 passed |
| Shared Discord confirm delegation | `python -m pytest tests/test_user_context_entrypoints.py tests/test_concept_confirm.py tests/test_suggest_topic_confirm.py -q` passed: 40 passed; `python -m pytest tests/test_user_context_entrypoints.py -q` passed: 14 passed |
| Shared Discord quiz helper ownership | `python -m pytest tests/test_quiz_views.py tests/test_user_context_entrypoints.py -q` passed: 26 passed; `python -m pytest tests/test_messages.py tests/test_review_fallback.py -q` passed: 13 passed |
| Typed quiz follow-up actions | `python -m pytest tests/test_quiz_views.py tests/test_messages.py tests/test_user_context_entrypoints.py -q` passed: 35 passed; `python -m pytest tests/test_api.py tests/test_review_fallback.py tests/test_proposals.py -q` passed: 106 passed |

## Next Actions

1. Evaluate whether the next lowest-risk extraction is maintenance/taxonomy orchestration from `services/pipeline.py`, or whether `execute_llm_response()` and related parsing/execution seams should remain there as the durable core.
2. Decide whether remaining direct prompt-context usage in `services/pipeline.py` belongs there, or whether the preference-edit flow should move closer to `services.context.py` or another dedicated owner.
3. Repay the current +122 runtime LOC increase by consolidating the remaining review/admin seams and any last compatibility surfaces before closing Phase 4 and Phase 5 slices.