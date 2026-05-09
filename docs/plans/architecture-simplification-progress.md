# Architecture Simplification Progress Tracker

## Current Status

| Field | Value |
|---|---|
| Overall status | In progress |
| Active phase | Phase 7 UI cleanup is still open, but the active slices now move between UI and backend hotspots based on where duplicated workflow still remains meaningful |
| Current objective | Continue simplification on the plan’s real goal: remove duplicated workflow and clarify ownership where it still matters, using hotspot LOC only as a guardrail rather than the main objective |
| Next implementation target | Revisit the next real hotspot by evidence: `services.context.py` for prompt/cache bookkeeping or another backend owner with duplicated orchestration; return to UI only if a meaningful duplicated browser/Discord workflow remains |

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
| Workflow-specific seams in `services/pipeline.py` | 8 | `handle_maintenance`, `call_maintenance_loop`, `call_taxonomy_loop`, `handle_taxonomy`, the preference-edit trio, and approved-action replay were still colocated with the durable parse/execute core |

## Current Metrics After Latest Slice

| Metric | Current | Delta vs baseline | Notes |
|---|---:|---:|---|
| Synthetic slash-to-chat routes in `bot/commands.py` | 0 | -2 | Removed by direct shared maintenance and taxonomy request entrypoints |
| Duplicate review orchestration paths | 0 | -2 | Review entry and generation now route through shared `services/chat_session.py` and `services/review_flow.py` surfaces rather than transport-owned orchestration |
| Confirmed review execution branches in `services/chat_session.py` | 0 | n/a | `maintenance_review` and `taxonomy_review` execution now delegate to `services.chat_admin.execute_confirmed_review()` |
| `services/chat_admin.py` LOC | 448 | +20 | Shared proposal/admin owner now also handles confirmed maintenance and taxonomy execution plus approved-action replay |
| `services/chat_quiz.py` LOC | 123 | n/a | New shared owner for browser/API quiz follow-up button derivation |
| `services/context.py` LOC | 922 | +106 | Prompt skill loading, prompt caching, and system-prompt composition now live with other prompt-building logic |
| `services/llm_runtime.py` LOC | 334 | n/a | Shared runtime owner now includes the fetch loop along with conversation sessions, output-contract retry/logging, and raw provider-call helpers |
| `services/chat_session.py` LOC | 338 | -86 | Shared chat controller now calls `services.llm_runtime.call_with_fetch_loop` directly when routing interactive learn turns |
| `services/preferences_flow.py` LOC | 35 | n/a | Shared owner for the isolated preference-edit skill path and approved preference writes |
| `services/review_flow.py` LOC | 273 | n/a | Review-flow ownership now includes canonical review payload/check helpers, structured quiz generation, deterministic delivery formatting, and runtime-backed quiz fallback generation |
| `bot/commands.py` LOC | 386 | -12 | Bot transport code is thinner for the targeted commands and Phase 3 closeout remains intact |
| `services/pipeline.py` LOC | 414 | -699 | The durable parse/execute core remains, the DB bootstrap shim is gone, and only the intentional maintenance/taxonomy operator wrappers remain |
| Runtime LOC total | 19,120 | +57 | The runtime is slightly above the original baseline because later shared-owner additions and unrelated frontend growth offset backend reductions, but duplicated paths are down and the main backend hotspot shrank materially |

## Current Hotspot Snapshot

| Path | Current LOC | Delta vs baseline | Current note |
|---|---:|---:|---|
| `services/context.py` | 922 | +106 | Largest backend hotspot after prompt ownership consolidation |
| `frontend/src/pages/ChatPage.tsx` | 832 | +134 | Phase 7 started with a local controller seam plus extracted leaf UI inside the same file; ownership is clearer, but hotspot LOC is higher until those seams move into separate files |
| `db/concepts.py` | 664 | 0 | Large DB surface remains stable but broad |
| `services/views.py` | 635 | +15 | Discord UI boilerplate is now a clearer Phase 7 hotspot than `services/pipeline.py` |
| `services/scheduler.py` | 587 | 0 | Still broad, but Phase 6 intentionally kept its due-only review selector local |
| `services/tools.py` | 584 | 0 | Durable action executor remains large but central |
| `services/tools_assess.py` | 466 | 0 | Review and quiz logic hotspot remains |
| `services/chat_admin.py` | 448 | n/a | Emerged as a shared proposal/admin hotspot as workflow ownership moved out of transports |
| `services/pipeline.py` | 414 | -699 | No longer the primary backend hotspot; now mostly durable parse/execute orchestration plus intentional operator wrappers |
| `bot/commands.py` | 386 | -12 | Adapter-only target is thinner after transport flattening |
| `services/chat_session.py` | 338 | -86 | Shared chat controller shed quiz, review, and preference-specific ownership |

## Phase Tracker

| Phase | Status | Completion signal | Notes |
|---|---|---|---|
| 0. Planning artifacts | Completed | Both `docs/plans` files exist and doc indexes point to them | Completed |
| 1. Core boundary | Completed | Shared-core boundary accepted and referenced by active work | The canonical core path is now documented in the master plan and aligned with the current runtime split between `services/context.py`, `services/llm_runtime.py`, `services/review_flow.py`, and the remaining durable pipeline core |
| 2. Baseline metrics | Completed | Tracker contains area LOC, hotspot LOC, duplication counts, and validation targets | Completed with filtered source-only baseline |
| 3. Transport flattening | Completed | No transport-owned workflow orchestration remains for the targeted maintain, reorganize, review, confirm, preference, and quiz follow-up flows | `/maintain`, `/reorganize`, review request orchestration, `/preference`, confirm flows, and quiz follow-up behavior now route through shared chat-session, chat-admin, chat-action, and review-flow owners; Discord is now a thin transport adapter with local delivery and view lifecycle responsibilities |
| 4. Pipeline split | Completed | `services/pipeline.py` responsibilities reduced without behavior drift and its durable core is explicit | Prompt loading and prompt-cache ownership moved into `services/context.py`; runtime fetch-loop and session ownership moved into `services/llm_runtime.py`; `services/pipeline.py` now holds the durable parse/execute core plus the intentionally retained maintenance/taxonomy wrappers |
| 5. Review and proposal ownership | Completed | Shared services own the behavior; transports only render it | `services/review_flow.py` owns canonical review payload/check and quiz-generation helpers, `services/chat_admin.py` owns confirmed review and proposal-action execution, and Discord/browser flows now consume shared confirm and chat-action payloads instead of transport-owned orchestration |
| 6. Optional subsystem boundaries | In progress | Remaining optional and operator concerns are either justified by distinct behavior or clearly called non-goals | Scheduler keeps its local due-only review selector as an intentional behavior fork from manual review, canonical DB bootstrap now lives directly in `db.init_databases()`, transport-local lazy DB guards remain lightweight shims rather than a new shared helper, and maintenance/taxonomy wrappers remain intentionally retained because scheduler, chat-admin, and script callers still share one real operator call graph |
| 7. UI hotspot cleanup | In progress | Discord and frontend hotspot files either shrink or gain a durable split with focused regression coverage | Early ChatPage cleanup clarified local ownership without shrinking the file; Phase 7 now continues by removing duplicated UI interaction flow, using file splits only where they create a durable boundary |
| 8. Transport and framework fit review | Not started | Browser-primary versus keep-both investment revisited only if product usage or duplicated transport logic justifies it | |

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
| Preference-edit seam extraction | Moved the isolated preference-edit skill path and approved preference writes out of `services/pipeline.py` and into a dedicated shared owner in `services/preferences_flow.py`, with `services/chat_session.py` now depending on the new owner directly |
| Approved-action replay extraction | Moved approved proposal replay out of `services/pipeline.py` and into `services/chat_admin.py`, preserving `pipeline.execute_action()` as the shared execution policy layer while retargeting confirm/proposal callers to the new owner |
| Maintenance wrapper coverage and boundary decision | Added direct coverage for the maintenance wrapper contract, scheduler forwarding, and shared maintenance command proposal persistence, then kept the maintenance/taxonomy wrappers in `services/pipeline.py` because they still share one real operator call graph through scheduler, chat admin, and scripts |
| Low-risk alias retirement | Removed the pure pass-through `chat_session.handle_review_check` and `scheduler.build_review_payload` aliases so callers and tests now target `services.review_flow.py` directly, while leaving the fetch-loop aliases in place as the remaining caller-specific patch seams |
| Fetch-loop alias retirement | Removed the remaining caller-local `call_with_fetch_loop` aliases from `services/chat_session.py`, `services/review_flow.py`, `services/pipeline.py`, and `bot/handler.py`, then retargeted the focused tests to patch `services.llm_runtime.call_with_fetch_loop` directly through each importing module |
| Final transport flattening paydown | Routed Discord no-argument `/preference` display through `services.chat_session.handle_chat_message()` and moved the Discord quiz skip button onto the shared `handle_chat_action()` plus shared Discord result rendering path |
| Handler bootstrap owner cleanup | Retargeted `bot.handler._ensure_db()` to call `db.init_databases()` directly, aligning it with the canonical bootstrap owner and avoiding an extra hop through the `services.pipeline` compatibility shim |
| Pipeline bootstrap shim retirement | Retargeted API startup, bot startup, and maintenance smoke bootstrap to `db.init_databases()`, updated the bot startup regression seam, and deleted the dead `services.pipeline.init_databases()` compatibility wrapper |
| Boundary blessing checkpoint | Blessed scheduler’s due-only review selector as a durable behavior fork from manual review, and explicitly rejected introducing a shared DB-init helper because the remaining duplication is only transport-local lazy gating rather than divergent bootstrap policy |
| Phase 6 closeout rebaseline | Reframed the simplification strategy around product-serving duplication removal, aligned the baseline summary with the tracker, and corrected stale ownership notes before opening Phase 7 |
| Phase 7 ChatPage ownership cleanup | Extracted local action-button, pending-confirmation, command-palette, thread, and composer UI components plus a `useChatPageController()` seam in `frontend/src/pages/ChatPage.tsx`; ownership is clearer, but the hotspot LOC increased because the new seams remain in the same file |
| Phase 7 Discord quiz-view callback consolidation | Moved repeated quiz navigation button callback flow into `QuizNavigationView._run_followup_action()` so the Discord adapter no longer repeats the same follow-up dispatch, shared action call, and result-rendering sequence in three separate buttons |
| Phase 7 Discord proposal-view decision consolidation | Replaced separate per-item and bulk approve/reject proposal button classes with shared decision-button helpers plus view-local handlers, so `services/views.py` keeps the decision/update lifecycle in one place for dedup and maintenance proposal reviews |
| Phase 7 Discord confirm-view button consolidation | Replaced decorator-only add-concept, suggest-topic, and preference-update button callbacks with shared runtime button helpers plus one parameterized preference resolver, leaving the transport layer to own labels and the genuinely distinct confirm behavior only |
| Phase 7 Discord proposal finalize consolidation | Moved dedup and maintenance proposal action execution plus result rendering into `_ProposalDecisionView`, leaving each proposal view to own only its decision state and action-payload construction |
| Phase 7 ChatPage request-lifecycle consolidation | Moved repeated busy/status/focus/error lifecycle handling for send, action, and pending-confirm flows into one `runRequest()` helper in `useChatPageController()`, while keeping the distinct streaming, action, and confirm response handling local |
| Phase 7 ChatPage response-render consolidation | Moved repeated assistant reply rendering in action responses and pending-confirm follow-ups into shared `responseVariant()` and `appendAssistantResponse()` helpers, leaving the streaming path and pending-confirm message shaping as the remaining distinct browser behavior |
| Prompt-cache bookkeeping consolidation | Moved shared skill-path and mtime resolution into helper functions in `services/context.py` and slimmed the system-prompt cache to the fields it actually uses, so prompt ownership no longer repeats the same skill-file bookkeeping across base and system prompt builders |
| Lightweight-context due-section consolidation | Moved repeated due-concept line rendering in `build_lightweight_context()` into shared `_format_due_concept_line()` and `_append_due_concepts_section()` helpers, while keeping relation snippets disabled in `REVIEW-CHECK` mode |
| Concept-overview formatting consolidation | Moved repeated concept description/score/interval/reviews/topics rendering into `_append_concept_overview()` and reused it across active concept detail, preloaded concept detail, quiz-generator context, fetched concept detail, and concept-cluster rendering |
| Scheduler mode-check consolidation | Moved the duplicated serialized maintenance/taxonomy scheduler check flow into shared `_run_mode_check()` and added `_send_taxonomy_report()` so each scheduled operator job now owns only its context builder, messages, and report sender |

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
| Preference-edit seam extraction | `python -m pytest tests/test_preferences_flow.py tests/test_user_context_entrypoints.py -k "preference" -q` passed: 8 passed |
| Approved-action replay extraction | `python -m pytest tests/test_api.py tests/test_proposals.py -k "confirm_maintenance_review_uses_shared_admin_executor or confirm_taxonomy_review_uses_shared_admin_executor or chat_action_taxonomy_uses_taxonomy_source or execute_approved_actions_preserves_source_and_formats_results" -q` passed: 4 passed |
| Maintenance wrapper coverage and boundary decision | `python -m pytest tests/test_pipeline_operator_loops.py tests/test_scheduler_full.py tests/test_proposals.py -k "call_maintenance_loop_forwards_contract or send_maintenance_report_forwards_loop_output_to_mode_report or handle_maintenance_command_strips_reply_prefix_and_persists_proposals" -q` passed: 3 passed |
| Low-risk alias retirement | `python -m pytest tests/test_review_fallback.py tests/test_scheduler.py tests/test_scheduler_full.py -k "review or scheduled_review_payload or check_maintenance or check_taxonomy" -q` passed: 19 passed |
| Fetch-loop alias retirement | `python -m pytest tests/test_api.py tests/test_user_context_entrypoints.py tests/test_review_fallback.py tests/test_taxonomy_shadow_rebuild.py -k "test_chat_normal_reply or test_chat_stream_returns_status_and_done_events or test_chat_add_concept_returns_pending_confirm or test_chat_suggest_topic_returns_pending_confirm or test_handle_user_message_sets_context_from_explicit_user_id or test_scheduler_fallback_uses_review_check_mode or test_chat_review_fallback_uses_review_check_mode or test_bot_review_fallback_uses_review_check_mode or test_taxonomy_loop_reuses_session_and_records_created_topic" -q` passed: 9 passed |
| Final transport flattening paydown | `python -m pytest tests/test_user_context_entrypoints.py tests/test_quiz_views.py -k "preference_command or skip_button or chat_action_skip_uses_current_scoped_user" -q` passed: 8 passed |
| Handler bootstrap owner cleanup | `python -m pytest tests/test_user_context_entrypoints.py -k "handler_ensure_db_uses_db_owner_once or handle_user_message_sets_context_from_explicit_user_id" -q` passed: 2 passed |
| Pipeline bootstrap shim retirement | `python -m pytest tests/test_bot_events.py tests/test_user_context_entrypoints.py tests/test_api.py -k "on_ready_initializes_databases_before_scheduler_start or handler_ensure_db_uses_db_owner_once or chat_empty_message_400" -q` passed: 3 passed |
| Phase 6 closeout rebaseline | Docs revalidated against current shared-owner modules and a 2026-05-09 PowerShell line-count snapshot; no runtime code changed |
| Phase 7 ChatPage ownership cleanup | `Push-Location frontend; npm test -- --run src/App.test.tsx; Pop-Location` passed after each ChatPage slice; focused browser validation remains green while the page ownership improved |
| Phase 7 Discord quiz-view callback consolidation | `python -m pytest tests/test_quiz_views.py -q` passed: 13 passed |
| Phase 7 Discord proposal-view decision consolidation | `python -m pytest tests/test_proposals.py -q` passed after the per-item and bulk decision-button refactors: 11 passed |
| Phase 7 Discord confirm-view button consolidation | `python -m pytest tests/test_concept_confirm.py tests/test_suggest_topic_confirm.py -q` passed: 28 passed; `python -m pytest tests/test_user_context_entrypoints.py -k "discord_reply_confirm_delegates_to_shared_resolver or discord_reply_decline_delegates_to_shared_resolver or preference_view_apply_and_reject_delegate_to_shared_chat_confirm" -q` passed: 3 passed |
| Phase 7 Discord proposal finalize consolidation | `python -m pytest tests/test_proposals.py -q` passed after moving proposal action execution and result rendering into the shared proposal base: 11 passed |
| Phase 7 ChatPage request-lifecycle consolidation | `Push-Location frontend; npm test -- --run src/App.test.tsx; Pop-Location` passed: 10 passed |
| Phase 7 ChatPage response-render consolidation | `Push-Location frontend; npm test -- --run src/App.test.tsx; Pop-Location` passed after extracting shared assistant response rendering: 10 passed |
| Prompt-cache bookkeeping consolidation | `python -m pytest tests/test_skill_loading.py -q` passed after simplifying duplicated skill-path bookkeeping in `services/context.py`: 23 passed |
| Lightweight-context due-section consolidation | `python -m pytest tests/test_context_enrichment.py tests/test_concept_confirm.py -k "DueConceptRelations or review_check_mode_uses_concept_prefix or concept_prefix_in_due_list" -q` passed: 4 passed |
| Concept-overview formatting consolidation | `python -m pytest tests/test_context_enrichment.py -k "ActiveConceptDetail or PreloadMentionedConcept or QuizGeneratorEnrichment" -q` passed: 17 passed; `python -m pytest tests/test_context_builders.py -q` passed: 3 passed |
| Scheduler mode-check consolidation | `python -m pytest tests/test_scheduler_full.py -k "maintenance or taxonomy" -q` passed after extracting the shared scheduler helper and adding direct taxonomy sender coverage: 4 passed |

## Next Actions

1. Continue only where the next slice removes real duplicated workflow or clarifies ownership; `services/views.py` and `frontend/src/pages/ChatPage.tsx` now have less obvious transport/browser duplication than before.
2. Revisit `services/context.py` or another backend hotspot only if prompt/context or operator bookkeeping still repeats enough logic to justify another shared owner helper; avoid bookkeeping-only splits.
3. Revisit maintenance/taxonomy wrapper extraction only if the scheduler, chat-admin, and script call graph narrows enough to justify a real owner boundary instead of a packaging move.
4. Revisit transport strategy only if product usage or duplicated transport logic shows that equal investment across browser and Discord is no longer justified.