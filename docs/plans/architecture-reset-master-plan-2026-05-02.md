## Plan: Architecture Reset Review

Shift the system toward a user-scoped modular monolith that preserves the LLM-first product model, keeps Discord + browser + scheduler + maintenance/taxonomy, and removes the current accidental complexity caused by duplicated workflows, split reminder/proposal state, and half-activated multi-user support. The recommended path is not a microservice split and not a cosmetic cleanup; it is a data-preserving architecture reset that centralizes core use cases behind application services while reducing Discord, HTTP, and scheduler code to adapters.

## Companion Docs

- [Architecture invariants](architecture-reset-invariants-2026-05-02.md)
- [Milestone roadmap](architecture-reset-roadmap-2026-05-02.md)
- [Debt register](architecture-reset-debt-register-2026-05-02.md)
- [Target architecture sketch](architecture-reset-target-architecture-2026-05-02.md)

**Primary technical debt findings**
- One logical review lifecycle is implemented three times across Discord, browser/API, and scheduler delivery.
- Reminder state is mirrored across typed rows and legacy session blobs, creating a fragile compatibility bridge.
- Confirmation/proposal handling uses different state models in Discord and browser/API.
- Multi-user groundwork exists in storage but is not activated at entry points, while runtime behavior still assumes one effective user.
- Core orchestration responsibilities are spread across transport adapters, scheduler code, and one oversized pipeline module.
- Cross-surface conversation state is desired, but the current implementation relies on process-global state and a global pipeline lock.
- Browser/API remains local-first, but several layers look partially prepared for a broader deployment model without actually supporting it cleanly.

**Steps**
1. Phase 1: Architecture baseline and invariants. Write a short architecture brief that freezes the non-negotiable invariants before any refactor: shared cross-surface conversation state, one active learning turn per user, durable approval for destructive actions, raw LLM output never crossing the contract boundary, assessment always bound to the intended quiz/concept, and data-preserving migration only. This blocks all later work.
2. Phase 1: Produce the formal current-state workflow map and debt register from the code anchors already identified. Group debt into: conversation/session state, review lifecycle, reminder state, confirmation/proposals, scheduler ownership, multi-user activation, LLM contract/runtime, API/browser surface, taxonomy/maintenance automation, and test/verification debt. This can run in parallel with step 1 but must be finalized before design sign-off.
3. Phase 1: Define the target architecture boundary. The recommended target is: adapters layer (Discord, FastAPI, scheduler worker), application services layer (Conversation, Review, Proposal, Maintenance, Taxonomy, Preferences), LLM runtime layer (prompt assembly, fetch loop, output validation, tool invocation, provider/session handling), and repository/infrastructure layer (SQLite now, vector search optional, backup, notification transport). This depends on steps 1-2.
4. Phase 2: Define the canonical state model. Specify one authoritative model for conversation/session state, one authoritative model for review/reminder state, and one authoritative model for proposal/approval state. Preserve compatibility read paths temporarily, but design all writes to converge on the new canonical models. This depends on step 3.
5. Phase 2: Activate true per-user scoping at all entry points after closing schema holes. Update the architecture so Discord, browser/API, scheduler, and background jobs all set explicit user context; fix known user-scoping gaps first, especially global title uniqueness and implicitly scoped tables. This depends on step 4.
6. Phase 3: Extract a canonical Review service. Move concept selection, quiz generation, quiz anchor/session mutation, assessment, reminder registration, reminder resolution, and late-answer recovery behind one shared service used by Discord, browser/API, and scheduler. This is the highest-value simplification and depends on steps 4-5.
7. Phase 3: Extract a canonical Conversation service. Centralize shared cross-surface conversation/session behavior, confirmation markers, command dispatch, chat history persistence, and per-user turn serialization. The goal is to remove transport-owned workflow logic from Discord handlers and browser chat controllers. This depends on steps 4-5 and should proceed in parallel with step 6 where possible.
8. Phase 3: Unify proposal/confirmation handling. Create one approval service that owns creation, expiry, audit trail, execution handoff, and restart safety. Discord buttons and browser/API widgets should become presentation adapters over the same proposal lifecycle. This depends on steps 4-5 and should align with steps 6-7.
9. Phase 4: Shrink the scheduler into an automation runner. Keep durable owner-election and due-time tracking, but move review delivery, maintenance, taxonomy, dedup, and backup behavior behind application services. Separate job scheduling, job execution, and notification transport so API-hosted shared jobs and Discord-only delivery cannot drift. This depends on steps 5-8.
10. Phase 4: Split the oversized pipeline into a pure LLM runtime. Retain the fetch loop, skill loading, prompt assembly, output validation, repair/retry, and tool execution boundary, but move review, maintenance, taxonomy, and preference-specific orchestration into their owning application services. This depends on steps 6-9.
11. Phase 5: Reframe the browser/API surface explicitly as local-first but multi-user-ready. Keep local-first auth and hosting assumptions for now, but redesign the HTTP layer around the new application services and typed contracts rather than ad hoc dict envelopes. Remote browser access stays out of immediate scope unless product direction changes later. This depends on steps 5-10.
12. Phase 5: Rationalize taxonomy and maintenance. Preserve the current safety model for destructive actions and shadow rebuild preview/replay, but move both onto the same application-service boundaries and stop relying on transport-specific orchestration. This depends on steps 8-10.
13. Phase 5: Replace compatibility bridges deliberately. Once the new services are live, remove the reminder dual-write bridge, transport-specific confirmation state, and legacy direct DB access from adapters. Only remove a bridge after the matching regression suite and migration rehearsal pass.
14. Phase 6: Harden the acceptance suite around invariants, not file structure. Promote the core rewrite acceptance set: output contract, quiz anchor/recovery, scheduler ownership, reminder lifecycle, confirmation persistence, taxonomy replay safety, cross-surface chat/review parity, and multi-user isolation. This can start early, but final cutover depends on all prior phases.

**Execution order and parallelism**
1. Blocking sequence: steps 1 -> 3 -> 4 -> 5 -> 6/7/8 -> 9/10 -> 11/12 -> 13 -> 14.
2. Parallelizable work: step 2 can run with step 1; steps 6, 7, and 8 can be designed together after step 5; steps 9 and 10 can proceed in parallel once services are defined; step 14 should run continuously as the acceptance harness.

**Relevant files**
- [services/pipeline.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/pipeline.py) — current orchestrator and the main candidate to shrink into a pure LLM runtime.
- [services/chat_session.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/chat_session.py) — browser/API controller that currently owns too much workflow logic.
- [services/review_state.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/review_state.py) — reminder compatibility bridge and a key target for canonical-state redesign.
- [services/scheduler.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/scheduler.py) — current mixed scheduler, job, and delivery responsibilities.
- [services/state.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/state.py) — current global serialization and dormant per-user context boundary.
- [services/context.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/context.py) — prompt/context assembly and a likely future split by use case.
- [services/tools.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/tools.py) — core action execution boundary.
- [services/tools_assess.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/tools_assess.py) — current quiz/assess lifecycle logic to be absorbed by the Review service.
- [api/routes/chat.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/api/routes/chat.py) — HTTP adapter that should stop owning workflow semantics.
- [bot/commands.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/bot/commands.py) — Discord adapter that should stop duplicating review and maintenance/taxonomy orchestration.
- [bot/events.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/bot/events.py) — Discord event adapter and current confirmation/message interception path.
- [db/core.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/db/core.py) — schema/versioning and multi-user groundwork.
- [db/review_reminders.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/db/review_reminders.py) — typed reminder persistence and the likely canonical reminder store.
- [db/proposals.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/db/proposals.py) — durable proposal persistence that should become cross-surface.
- [db/relations.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/db/relations.py) — one of the remaining implicitly scoped data surfaces to resolve before full multi-user activation.
- [scripts/taxonomy_shadow_rebuild.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/scripts/taxonomy_shadow_rebuild.py) — keep the safety model, but re-anchor it on cleaner service boundaries.
- [tests/test_output_contract.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_output_contract.py) — acceptance anchor for the fail-closed LLM boundary.
- [tests/test_quiz_anchor.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_quiz_anchor.py) — acceptance anchor for quiz/concept binding and recovery.
- [tests/test_assess_no_quiz_guard.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_assess_no_quiz_guard.py) — acceptance anchor for assessment safety.
- [tests/test_scheduler_full.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler_full.py) — acceptance anchor for reminder lifecycle and scheduler integration.
- [tests/test_scheduler_state.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler_state.py) — acceptance anchor for single-owner shared jobs.
- [tests/test_taxonomy_shadow_rebuild.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_taxonomy_shadow_rebuild.py) — acceptance anchor for preview/apply replay integrity.
- [tests/test_api.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_api.py) — broad chat/API behavior coverage and a key parity reference during adapter refactors.

**Verification**
1. Architecture sign-off review: verify every proposed simplification preserves the frozen invariants from step 1 and explicitly removes one currently identified debt source.
2. Dependency review: for each extracted service, confirm all Discord/API/scheduler entry points call the shared service rather than duplicating orchestration.
3. Regression suite: run the acceptance tests for output contract, quiz anchor, assess safety, scheduler lifecycle, scheduler ownership, taxonomy replay, and chat/API parity after each major phase.
4. Manual parity matrix: verify Discord chat, browser chat, manual review, scheduled review, confirmation/decline flows, maintenance proposals, taxonomy proposals, and reminder recovery behave the same through the new services.
5. Multi-user smoke verification: run two distinct user identities across Discord/browser paths and confirm isolated knowledge, reminders, proposals, and in-flight turn locks with no writes leaking to the default user.
6. Migration rehearsal: copy real data into a shadow environment, run schema/data migration and service cutover, then verify no loss of reviews, reminders, proposals, topic relations, or conversation continuity.

**Decisions**
- Included scope: Discord bot, browser/FastAPI, scheduler-driven review reminders, maintenance automation, taxonomy automation, and near-term multi-user readiness.
- Deployment target: hybrid local now, multi-user later.
- Conversation model: share one cross-surface conversation/session state.
- Concurrency target: one active learning turn per user.
- LLM boundary: remain strongly LLM-driven, with a strict fail-closed output contract.
- Change appetite: architecture reset is acceptable if data is preserved.
- Deliberately excluded from immediate scope: microservice decomposition, remote-browser production auth rollout, and optional vector-search optimization work unless they block the core reset.

**Further considerations**
1. If cross-surface shared conversation state becomes too expensive to preserve cleanly, the fallback simplification is to share knowledge/review state only and split conversation state per surface; that would reduce locking pressure but would change product behavior and should be treated as a deliberate product decision, not a refactor side effect.
2. If multi-user activation is prioritized ahead of the service extraction, require a temporary compatibility layer that logs every entry point still writing as the default user so silent data leakage cannot survive the transition.