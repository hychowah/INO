# Architecture Reset Target Architecture Sketch

## Purpose

This document describes the target architecture for the reset. It is a planning sketch, not a final package layout. The goal is to make module ownership explicit before implementation begins.

## Core Principle

One user-scoped backend owns the product. Adapters translate transport concerns. Application services own use cases. The LLM runtime owns prompt and action orchestration. Repositories and infrastructure own persistence and external integrations.

## Target Shape

```text
Discord Adapter ─┐
HTTP Adapter    ├──> Application Services ───> LLM Runtime
Scheduler Worker┘             │                     │
                              │                     │
                              └──────> Repositories / Infrastructure
```

## Layer 1: Adapters

Adapters are thin entry points. They do not own review logic, approval semantics, or direct workflow state transitions.

### Discord Adapter

Responsibilities:

- Translate Discord messages, slash commands, and button callbacks into service calls.
- Resolve Discord identity into user context.
- Render service responses into Discord messages and views.

Likely source files to shrink into this layer:

- [../../bot/commands.py](../../bot/commands.py)
- [../../bot/events.py](../../bot/events.py)
- [../../bot/handler.py](../../bot/handler.py)

### HTTP Adapter

Responsibilities:

- Translate HTTP and SSE requests into service calls.
- Resolve browser/API identity into user context.
- Return typed response models for chat, approvals, dashboard reads, and knowledge reads.

Likely source files to shrink into this layer:

- [../../api/routes/chat.py](../../api/routes/chat.py)
- [../../api/routes/topics.py](../../api/routes/topics.py)
- [../../api/routes/concepts.py](../../api/routes/concepts.py)
- [../../api/routes/reviews.py](../../api/routes/reviews.py)
- [../../api/routes/misc.py](../../api/routes/misc.py)

### Scheduler Worker Adapter

Responsibilities:

- Own durable scheduler leadership, job tick timing, and job dispatch.
- Call the same application services used by interactive paths.
- Send notifications through a transport abstraction rather than embedding Discord-specific workflow policy.

Likely source files to shrink into this layer:

- [../../services/scheduler.py](../../services/scheduler.py)

## Layer 2: Application Services

Application services own business use cases and shared state transitions.

### Conversation Service

Responsibilities:

- Cross-surface conversation/session state.
- Per-user turn ownership and serialization.
- Command dispatch into the correct use case.
- Chat history persistence policy.
- Confirmation marker lifecycle and user-visible conversation continuity.

Primary current inputs:

- [../../services/chat_session.py](../../services/chat_session.py)
- [../../bot/handler.py](../../bot/handler.py)
- [../../db/chat.py](../../db/chat.py)
- [../../services/state.py](../../services/state.py)

### Review Service

Responsibilities:

- Select due concepts.
- Generate quizzes.
- Bind quiz instance to concept and session state.
- Assess answers.
- Register, resend, and resolve reminders.
- Recover delayed answers safely.

Primary current inputs:

- [../../services/tools_assess.py](../../services/tools_assess.py)
- [../../services/review_state.py](../../services/review_state.py)
- [../../services/pipeline.py](../../services/pipeline.py)
- [../../db/review_reminders.py](../../db/review_reminders.py)

### Proposal Service

Responsibilities:

- Create approval records.
- Expire approvals.
- Approve or reject actions.
- Provide one canonical audit trail.
- Hand approved actions to execution services.

Primary current inputs:

- [../../db/proposals.py](../../db/proposals.py)
- [../../services/views.py](../../services/views.py)
- [../../services/chat_actions.py](../../services/chat_actions.py)
- [../../services/chat_session.py](../../services/chat_session.py)

### Maintenance Service

Responsibilities:

- Build maintenance context.
- Run maintenance action loop through the LLM runtime.
- Enforce safe versus approval-required actions.
- Emit durable results for scheduler, Discord, and browser.

Primary current inputs:

- [../../services/context.py](../../services/context.py)
- [../../services/pipeline.py](../../services/pipeline.py)
- [../../db/diagnostics.py](../../db/diagnostics.py)

### Taxonomy Service

Responsibilities:

- Build taxonomy context.
- Run taxonomy restructuring loops.
- Preserve rename suppression and structural safety.
- Integrate with preview/apply workflows.

Primary current inputs:

- [../../services/context.py](../../services/context.py)
- [../../services/pipeline.py](../../services/pipeline.py)
- [../../scripts/taxonomy_shadow_rebuild.py](../../scripts/taxonomy_shadow_rebuild.py)
- [../../db/action_log.py](../../db/action_log.py)

### Preferences Service

Responsibilities:

- Persona selection.
- Preference reads and edits.
- Preference-edit approval or confirmation policy if needed.

Primary current inputs:

- [../../db/preferences.py](../../db/preferences.py)
- [../../services/pipeline.py](../../services/pipeline.py)

## Layer 3: LLM Runtime

The LLM runtime is a boundary, not the owner of business use cases.

Responsibilities:

- Load skill packs and personas.
- Build prompt envelopes from structured context input.
- Manage provider sessions and request execution.
- Run fetch loops.
- Validate and repair output.
- Invoke allowed actions or return structured action suggestions.

Primary current inputs:

- [../../services/pipeline.py](../../services/pipeline.py)
- [../../services/context.py](../../services/context.py)
- [../../services/llm.py](../../services/llm.py)
- [../../services/parser.py](../../services/parser.py)
- [../../services/tools.py](../../services/tools.py)

Constraints:

- It must stay fail-closed.
- It must not become the permanent owner of review, maintenance, taxonomy, or scheduler policy.

## Layer 4: Repositories And Infrastructure

Responsibilities:

- Persist user-scoped knowledge, reviews, reminders, approvals, and scheduler state.
- Provide narrow repository boundaries to services.
- Own external integrations such as vector search, backup, and notification transport.

Primary current inputs:

- [../../db/core.py](../../db/core.py)
- [../../db/concepts.py](../../db/concepts.py)
- [../../db/topics.py](../../db/topics.py)
- [../../db/reviews.py](../../db/reviews.py)
- [../../db/chat.py](../../db/chat.py)
- [../../db/review_reminders.py](../../db/review_reminders.py)
- [../../db/proposals.py](../../db/proposals.py)
- [../../db/action_log.py](../../db/action_log.py)
- [../../db/relations.py](../../db/relations.py)
- [../../services/backup.py](../../services/backup.py)
- [../../db/vectors.py](../../db/vectors.py)

## Canonical State Ownership

The target architecture needs one canonical owner for each hard state machine.

- Conversation/session state: owned by the Conversation service.
- Review/reminder state: owned by the Review service.
- Proposal/approval state: owned by the Proposal service.
- Scheduler timing and shared ownership: owned by the Scheduler worker plus scheduler-state repositories.

Compatibility bridges may exist temporarily, but canonical write ownership must be singular.

## Cross-Cutting Policies

### User Context

- Every adapter sets explicit user context.
- Services never guess user identity.
- No new workflow depends on implicit default-user fallback.

### Concurrency

- One active learning turn per user.
- Shared background jobs remain single-owner across processes.
- Cross-user concurrency is allowed once state is isolated.

### Safety

- Raw provider output never bypasses runtime validation.
- Destructive actions always go through durable approval policy.
- Maintenance and taxonomy never silently modify learning scores.

## Current-To-Target Mapping

### Modules Expected To Shrink

- [../../services/pipeline.py](../../services/pipeline.py)
- [../../services/chat_session.py](../../services/chat_session.py)
- [../../services/scheduler.py](../../services/scheduler.py)
- [../../bot/commands.py](../../bot/commands.py)
- [../../api/routes/chat.py](../../api/routes/chat.py)

### Modules Likely To Become Transitional Or Disappear

- [../../services/review_state.py](../../services/review_state.py) once reminder state is canonicalized.
- Transport-specific confirmation glue currently spread across browser and Discord code.

### Modules That Likely Remain But Under Narrower Contracts

- [../../services/llm.py](../../services/llm.py)
- [../../services/parser.py](../../services/parser.py)
- [../../services/tools.py](../../services/tools.py)
- The `db/` package, but behind narrower repository boundaries.

## What This Sketch Rejects

- Microservice decomposition as a first move.
- Framework replacement as a proxy for fixing ownership boundaries.
- Transport-specific business logic as a permanent design choice.
- Default-user fallback as an acceptable multi-user runtime model.

## Immediate Design Follow-Ups

1. Draw the current-state workflow map against this target.
2. Define the canonical state models in more detail.
3. Identify the smallest implementation slice that creates the first real shared service boundary.
4. Define the migration and rollback story for each compatibility bridge.