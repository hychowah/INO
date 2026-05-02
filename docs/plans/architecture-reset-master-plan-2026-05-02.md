## Plan: Simpler Architecture Reset

Refocus the system on a strong single-user modular monolith that preserves the LLM-first product model, keeps Discord + browser + scheduler + maintenance/taxonomy, and removes accidental complexity where it is actually concentrated: duplicated review flows, duplicated interactive turn orchestration, scheduler-owned workflow branches, provider-session locality, and approval behavior that is inconsistent across surfaces. The recommended path is not a microservice split and not a broad service lattice. It is a data-preserving architecture reset that introduces only the boundaries that remove real duplication.

## Companion Docs

- [Progress tracker](architecture-reset-progress-tracker-2026-05-02.md)
- [Architecture invariants](architecture-reset-invariants-2026-05-02.md)
- [Milestone roadmap](architecture-reset-roadmap-2026-05-02.md)
- [Debt register](architecture-reset-debt-register-2026-05-02.md)
- [Target architecture sketch](architecture-reset-target-architecture-2026-05-02.md)
- [Canonical conversation state model](architecture-reset-conversation-state-model-2026-05-02.md)
- [Canonical review state model](architecture-reset-review-state-model-2026-05-02.md)
- [Canonical proposal state model](architecture-reset-proposal-state-model-2026-05-02.md)
- [Current workflow map](architecture-reset-current-workflow-map-2026-05-02.md)
- [Multi-user gap inventory](architecture-reset-multi-user-gap-inventory-2026-05-02.md) — secondary reference only; not a reset driver for the current scope

**Primary technical debt findings**
- One logical review lifecycle is implemented three times across Discord, browser/API, and scheduler delivery.
- Reminder state is mirrored across typed rows and legacy session blobs, creating a fragile compatibility bridge.
- Cross-surface conversation continuity is a real product requirement. Durable turn exclusivity now exists via the lease-backed gateway in `services/state.py` and `db/chat.py`, but provider-session locality and duplicated adapter orchestration still create fragility.
- Confirmation behavior is split across durable proposals and lightweight same-turn confirms, but the split is inconsistent and some browser/API flows still drift from Discord.
- Scheduler code still owns too much review and proposal workflow behavior instead of acting as a runner.
- Core orchestration responsibilities are spread across transport adapters, scheduler code, and one oversized pipeline module.
- Multi-user groundwork exists in storage and some boundaries, but full activation is not part of this reset and should not drive the architecture sequence.

**Steps**
1. Phase 0: Re-baseline the reset documents and invariants. Freeze the non-negotiable rules before further refactor work: one shared conversation across Discord and browser, one active learning turn for the single-user product, durable approvals only for destructive or long-running actions, raw LLM output never crossing the contract boundary, assessment always bound to the intended quiz/concept, and data-preserving migration only. This blocks all later work.
2. Phase 0: Replace the target architecture framing with fewer seams. Keep adapters, a small turn-coordination boundary, a shared Review service, the fail-closed LLM runtime, and the existing db package as the repository layer. Defer separate Conversation, Proposal, Preferences, Maintenance, and Taxonomy services unless a later slice proves they remove real duplication. This depends on step 1.
3. Phase 1: Treat the durable single-user turn gateway as complete and preserve it as the outer coordination boundary. Reuse the existing lease-backed gateway instead of designing a new coordination subsystem, and focus the next slices on provider-session locality and duplicated adapter orchestration. This depends on step 2.
4. Phase 2: Extract one canonical Review service. Move manual review start, scheduled review send, quiz setup, assess, skip, reminder registration, reminder resend, reminder resolution, and late-answer recovery behind one shared boundary used by Discord, browser/API, and scheduler. This is the highest-value simplification and depends on step 3.
5. Phase 2: Keep approvals intentionally split into two tiers. Reuse the existing durable proposal store only for destructive or long-running flows such as dedup, maintenance, and taxonomy. Keep add-concept, suggest-topic, and preference confirms lightweight and same-turn, but route them through shared helpers so Discord and browser logic stop drifting. This depends on step 2 and should align with step 4.
6. Phase 3: Shrink the scheduler into a runner, not a workflow owner. Keep durable owner-election and due-time tracking, but move review state transitions and durable proposal creation behind the shared Review service and approval policy. This depends on steps 4-5.
7. Phase 3: Collapse maintenance and taxonomy only where they truly share policy. Prefer one automation-runner pattern with different prompt/policy inputs over two heavyweight service abstractions. Preserve the current destructive-action safety model and taxonomy shadow rebuild preview/replay guarantees. This depends on step 5 and can proceed in parallel with step 6.
8. Phase 4: Shrink the oversized pipeline into a cleaner LLM runtime boundary only after review, approvals, and scheduler ownership are clarified. Retain the fetch loop, skill loading, prompt assembly, output validation, repair/retry, and tool execution boundary, but move only business-specific orchestration out. This depends on steps 4-7.
9. Phase 5: Replace compatibility bridges deliberately. Once the new boundaries are live, remove the reminder dual-write bridge, transport-specific workflow branches, and stale planning assumptions. Only remove a bridge after the matching regression suite and migration rehearsal pass.

**Execution order and parallelism**
1. Blocking sequence: steps 1 -> 2 -> 3 -> 4/5 -> 6/7 -> 8 -> 9.
2. Parallelizable work: review extraction and approval split can proceed together once the adapter orchestration seam is fixed; scheduler cleanup and automation-runner cleanup can proceed together once the Review boundary is stable; acceptance work should run continuously throughout the implementation.

**Relevant files**
- [services/state.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/state.py) — existing lease-backed turn gateway; preserve as the outer coordination boundary.
- [bot/handler.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/bot/handler.py) — Discord chat entry and shared conversation flow anchor.
- [api/routes/chat.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/api/routes/chat.py) — HTTP adapter that must share the same turn gateway.
- [services/chat_session.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/chat_session.py) — browser/API review and confirmation behavior that should shrink behind shared helpers.
- [services/review_state.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/review_state.py) — reminder compatibility bridge and the best transitional seam for canonical review ownership.
- [services/tools_assess.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/tools_assess.py) — current quiz, assess, skip, and anchor logic to preserve while extracting the Review service.
- [services/scheduler.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/scheduler.py) — keep timing and owner election, remove workflow ownership.
- [db/proposals.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/db/proposals.py) — keep as the durable approval store for destructive or long-running flows.
- [services/views.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/views.py) — existing split between durable and lightweight Discord confirmations.
- [services/chat_actions.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/chat_actions.py) — shared lightweight confirmation helpers.
- [services/pipeline.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/services/pipeline.py) — keep as the fail-closed LLM runtime boundary until later slices remove business-specific orchestration.
- [scripts/taxonomy_shadow_rebuild.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/scripts/taxonomy_shadow_rebuild.py) — preserve the shadow rebuild safety model while simplifying automation ownership.
- [tests/test_output_contract.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_output_contract.py) — acceptance anchor for the fail-closed LLM boundary.
- [tests/test_review_fallback.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_review_fallback.py) — acceptance anchor for review recovery behavior.
- [tests/test_quiz_anchor.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_quiz_anchor.py) — acceptance anchor for quiz/concept binding and recovery.
- [tests/test_assess_no_quiz_guard.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_assess_no_quiz_guard.py) — acceptance anchor for assessment safety.
- [tests/test_scheduler_full.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler_full.py) — acceptance anchor for reminder lifecycle and scheduler integration.
- [tests/test_scheduler_state.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_scheduler_state.py) — acceptance anchor for single-owner shared jobs.
- [tests/test_proposals.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_proposals.py) — acceptance anchor for durable proposal persistence.
- [tests/test_api.py](c:/Users/user/OneDrive/Documents/PA/learning_agent/tests/test_api.py) — chat/API confirmation and parity coverage during adapter refactors.

**Verification**
1. Architecture sign-off review: verify every proposed simplification preserves the frozen invariants from step 1 and removes one identified debt source.
2. Turn-gateway validation: keep the durable gateway green with narrow chat and entry-path tests while adapter orchestration is consolidated above it.
3. Review extraction validation: run the focused regression set for review fallback, quiz anchor, assess safety, reminder lifecycle, and scheduler ownership after each review-state change.
4. Approval split validation: keep lightweight confirmation behavior green in API/browser flows and durable proposal persistence green in scheduler/Discord flows.
5. Manual parity matrix: verify Discord chat, browser chat, manual review, scheduled review, confirmation/decline flows, maintenance proposals, taxonomy proposals, and reminder recovery behave the same through the new shared boundaries.
6. Migration rehearsal: copy real data into a shadow environment, run schema/data migration and service cutover, then verify no loss of reviews, reminders, proposals, topic relations, or conversation continuity.

**Decisions**
- Included scope: Discord bot, browser/FastAPI, scheduler-driven review reminders, maintenance automation, taxonomy automation, single-user turn coordination, and review/reminder unification.
- Deployment target: local-first single-user core.
- Conversation model: preserve one shared conversation across Discord and browser/API.
- Concurrency target: one active learning turn for the single-user product, enforced durably rather than process-locally.
- Approval model: durable proposals only for destructive or long-running flows; lightweight same-turn confirmations stay lightweight.
- LLM boundary: remain strongly LLM-driven, with a strict fail-closed output contract.
- Change appetite: architecture reset is acceptable if data is preserved.
- Deliberately excluded from immediate scope: microservice decomposition, full multi-user activation, remote-browser production auth rollout, and optional vector-search optimization work unless they block the core reset.

**Further considerations**
1. If provider-session continuity still matters after the shared entry orchestration is simplified, keep it as an optimization over durable chat history rather than treating provider session state as authoritative.
2. If review extraction exposes that maintenance and taxonomy share less code than expected, keep them as separate workflows over one automation-runner pattern rather than forcing a false unification.
3. Existing multi-user groundwork may remain in place if it is low-cost, but it is no longer a planning driver for the reset.