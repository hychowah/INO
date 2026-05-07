# Post-Reset Delivery Progress Tracker

## Status Summary

| Item | Status |
|---|---|
| Overall plan | Completed |
| Active milestone | None |
| Completed milestones | M1. Reconcile docs; M2. Codify validation; M3. Retire residue; M4. Prepare merge |
| Highest current risk | No active blocker is documented for the post-reset scope; any remaining risk is from widening scope beyond the validated seams or reopening intentional carry-forward debt without a focused slice |

## Milestone Tracker

| Milestone | Status | Scope | Completion signal |
|---|---|---|---|
| M1. Reconcile docs | Completed | Bring docs into alignment with the completed simplification reset and register the active plan files | API, architecture, coding guide, changelog, and documentation index files now match the shipped ownership seams |
| M2. Codify validation | Completed | Capture the focused backend, frontend, and chat-flow checks as one repeatable post-reset matrix, with deterministic gates separated from advisory live smoke | The matrix is documented, deterministic slices rerun successfully, and the advisory harness path is explicitly classified |
| M3. Retire residue | Completed | Remove or classify the remaining obsolete compatibility paths and dead references | High-confidence residue is retired, and the remaining live compatibility seams are explicitly left as intentional carry-forward debt |
| M4. Prepare merge | Completed | Summarize blockers, final verification, and go/no-go criteria for integration | Merge readiness can be assessed from this tracker alone |

## Merge Readiness Summary

| Item | Status |
|---|---|
| Deterministic merge gates | Complete and passing |
| Advisory live smoke | Complete once; optional to rerun immediately before merge |
| High-confidence residue retirement | Complete |
| Intentional carry-forward debt classified | Complete |
| Active blockers | None documented |
| Current recommendation | Go for merge on the documented post-reset scope |

## M3 Residue Outcomes

| Area | Outcome |
|---|---|
| Discord follow-up sender seam | `_send_quiz_response()` no longer rebuilds quiz prompt formatting, skip-button attachment, or stale answered-state clearing itself. It now delegates prompt delivery to the shared sender helper in `bot/messages.py` and keeps only the interaction-specific compatibility duties: legacy anchor fallback and interactive review delivery registration. |
| Frontend route residue | Stale claims that legacy browser aliases were still supported were removed from shell and page copy. The remaining browser policy is now consistent across source, tests, and built assets: canonical routes are `/knowledge`, `/knowledge/concepts`, `/knowledge/graph`, `/progress`, and `/progress/forecast`; unsupported legacy aliases still fall through to the dashboard route. |
| Lower-confidence carry-forward seams | Parser string-envelope compatibility, live pipeline wrapper indirection, suggest-topic wrapper indirection, and the frozen `ease_factor` schema field remain intentional carry-forward debt. They still have live callers or schema coupling and were not reopened in this residue pass. |

## Known Inputs

| Input | Relevance |
|---|---|
| Completed simplify branch commits already landed the architectural reset | This tracker assumes the major refactor is done and focuses on stabilization |
| `docs/plans/` had no active files before this tracker | The plan pair created here is the new active coordination surface |
| `docs/DEVNOTES.md` still records intentional deferred debt such as the frozen `ease_factor` field | Residue retirement should distinguish dead code from conscious carry-forward debt |
| Frontend Playwright coverage runs against previewed built assets with mocked API contracts | The frontend slice is browser smoke for the delivery contract, not live backend integration |
| `docs/CHAT_FLOW_HARNESS.md` runs the real provider in sandbox mode by default | The harness adds high-signal operator confidence, but it remains advisory rather than a deterministic merge gate |

## M2 Decisions

| Decision | Outcome |
|---|---|
| Deterministic merge gates | Focused pytest, Vitest, and Playwright slices only |
| Chat-flow harness | Advisory operator smoke in sandbox mode, not a required merge gate |
| Frontend route-alias checks | Treated as residue verification during M3, not baseline delivery proof |

## Post-Reset Validation Matrix

### Deterministic backend gates

| Slice | Command | What it proves |
|---|---|---|
| Shared chat controller and DTO routing | `python -m pytest tests/test_api.py::TestChat tests/test_learn_turn.py tests/test_user_context_entrypoints.py` | Shared `/api/chat` and `/api/chat/stream` behavior, confirm or decline or action envelopes, DTO-owned turn routing, and local-user or request-scope boundaries remain intact |
| Shared approval and confirm actions | `python -m pytest tests/test_proposals.py tests/test_concept_confirm.py tests/test_suggest_topic_confirm.py` | Proposal confirmation, add-concept confirmation, and suggest-topic confirmation still reuse the shared approval surfaces instead of adapter-local forks |
| Discord sender, quiz views, and scheduler delivery | `python -m pytest tests/test_messages.py tests/test_quiz_views.py tests/test_scheduler.py tests/test_review_fallback.py tests/test_scheduler_runtime.py` | Shared Discord send helpers, metadata-first quiz follow-up delivery, scheduler send registration, reminder fallback, and runtime scheduler binding still match the reset seams |
| Harness plumbing and page routes | `python -m pytest tests/test_chat_flow_script.py tests/test_api_pages.py` | The chat-flow harness entrypoint still works and the page routing surface still serves the current browser shell correctly |

### Deterministic frontend gates

| Slice | Command | What it proves |
|---|---|---|
| Browser chat contract and canonical routes | `cd frontend && npm run test -- src/App.test.tsx src/routes.test.tsx` | The browser chat surface still handles pending confirmations, streaming replies, inline actions, and the canonical route policy expected after the reset |
| Built browser chat smoke | `cd frontend && npm run build && npx playwright test e2e/chat.spec.ts` | The built SPA still honors the mocked `/api` chat contract, including stream completion, pending confirm rendering, and confirm completion flows |
| Route-alias residue verification | `cd frontend && npm run build && npx playwright test e2e/navigation.spec.ts e2e/knowledge-surfaces.spec.ts` | The browser route assertions stay aligned with the chosen canonical-route policy once M3 retires or normalizes the alias residue |

### Advisory operator smoke

| Slice | Command | How to use it |
|---|---|---|
| Real pipeline transcript in sandbox mode | `python scripts/test_chat_flow.py --scenario review --answer "when asking about sector, use global search with community summaries" --answer "for Company X inside that sector, use local search on the relevant nodes" --show-history` | Use this when you want one live conversational confidence check through the real provider without mutating the live DB. Record the transcript path or notable behavior, but do not treat the run as a deterministic merge gate. |

## Validation Execution Notes

| Slice | Result |
|---|---|
| Shared chat controller and DTO routing | Passed on 2026-05-07 via `python -m pytest tests/test_api.py::TestChat tests/test_learn_turn.py tests/test_user_context_entrypoints.py` (`33 passed`) |
| Shared approval and confirm actions | Passed on 2026-05-07 via `python -m pytest tests/test_proposals.py tests/test_concept_confirm.py tests/test_suggest_topic_confirm.py` (`37 passed`) |
| Discord sender, quiz views, and scheduler delivery | Passed on 2026-05-07 via `python -m pytest tests/test_messages.py tests/test_quiz_views.py tests/test_scheduler.py tests/test_review_fallback.py tests/test_scheduler_runtime.py` (`35 passed`) |
| Harness plumbing and page routes | Passed on 2026-05-07 via `python -m pytest tests/test_chat_flow_script.py tests/test_api_pages.py` (`26 passed`) |
| Browser chat contract and canonical routes | Passed on 2026-05-07 via `cd frontend && npm run test -- src/App.test.tsx src/routes.test.tsx` (`12 passed`) |
| Built browser chat smoke | Passed on 2026-05-07 via `cd frontend && npm run build && npx playwright test e2e/chat.spec.ts` (`3 passed`) |
| Discord sender residue cleanup | Passed on 2026-05-07 via `python -m pytest tests/test_quiz_views.py tests/test_messages.py` (`17 passed`) |
| Frontend route residue cleanup | Passed on 2026-05-07 via `cd frontend && npm run test -- src/routes.test.tsx src/pages/KnowledgePage.test.tsx src/pages/ProgressPage.test.tsx` (`6 passed`) |
| Built route residue verification | Passed on 2026-05-07 via `cd frontend && npm run build && npx playwright test e2e/navigation.spec.ts e2e/knowledge-surfaces.spec.ts` (`4 passed`) |
| Advisory operator smoke | Completed on 2026-05-07 via the sandbox harness command above. Transcript written to `scripts/prompt_logs/chat_flow_20260507_221629.json`. The run confirmed that unrelated follow-up replies stayed in casual-chat handling while the active review question remained pending, which matches the reply-mode intent rules for active quizzes. |

## Go Or No-Go Criteria

| Criterion | Current state |
|---|---|
| Local-first runtime identity still resolves through `services.state.get_local_user_id()` across Discord, API, browser, views, and scheduler surfaces | Satisfied by the reset architecture and covered by the focused API or user-context validation slices |
| API request scoping remains bounded at `api/auth.py` through `X-Learning-User`, without reintroducing adapter-local user identity drift | Satisfied by the reset architecture and the shared chat-controller or user-context validation slices |
| Shared interactive turn setup and serialization remain centralized in `services.state.begin_interactive_turn()` and `services.state.pipeline_serialized()` | Satisfied by the reset architecture and the chat-controller, scheduler-runtime, and user-context validation slices |
| Shared browser or API chat ownership remains in `services.chat_session.py` rather than route-local wrappers | Satisfied by the reset architecture and the shared chat-controller validation slice |
| Lightweight approvals remain shared in `services.chat_actions.py` across browser, API, Discord views, and reply-based Discord confirms | Satisfied by the shared approval and confirm validation slice |
| Scheduler reminder ownership remains in `services.review_state.py` and canonical review payload construction remains shared in `services.pipeline.build_review_payload()` | Satisfied by the scheduler or sender validation slices and the advisory harness smoke |
| Discord quiz follow-up delivery no longer keeps a second prompt-rendering seam in `services.views.py` | Satisfied by the M3 residue cleanup and the focused `tests/test_quiz_views.py tests/test_messages.py` rerun |
| Browser route support is internally consistent: canonical consolidated routes only, with unsupported legacy aliases falling through to `/` | Satisfied by the M3 residue cleanup plus the focused Vitest and Playwright route reruns |
| Lower-confidence live compatibility seams are classified as intentional debt instead of being half-removed during stabilization | Satisfied; parser string-envelope compatibility, pipeline wrapper indirection, suggest-topic wrapper indirection, and frozen `ease_factor` remain documented carry-forward debt |

## Final Verification Policy

| Check type | Policy |
|---|---|
| Required before merge | The documented deterministic backend and frontend gates in this tracker |
| Optional before merge | One sandbox chat-flow harness rerun when an operator wants fresh live-provider confidence immediately before merge |
| Not required for this plan | A broad full-suite rerun, unless a separate branch policy or unrelated code changes require it |

## Merge Decision

| Decision | Rationale |
|---|---|
| Go | The documented deterministic gates all passed on 2026-05-07, the advisory live smoke completed without contradicting the reply-mode contract, high-confidence residue was retired in M3, and the remaining debt items are explicitly classified rather than left ambiguous. |
| No-go triggers | Reopen the decision only if a required deterministic gate regresses, a new ownership seam is modified without focused validation, or an intended carry-forward debt item becomes a concrete blocker for the merge target. |

## Validation Log

| Check | Result |
|---|---|
| Plan files created and documentation indexes updated | Complete |
| Owning docs reconciled with post-reset payload, admin, and Discord delivery seams | Complete |
| Edited M1 documentation files validate cleanly in the workspace | Complete |
| Post-reset validation matrix documented with deterministic and advisory split | Complete |
| Post-reset validation matrix rerun | Complete |
| Residue audit rerun after cleanup | Complete |
| Merge-readiness review | Complete |

## Blockers

| Blocker | Status |
|---|---|
| No blocker identified on the documented post-reset scope | Closed |
