# Architecture Reset Target Architecture Sketch

## Purpose

This document describes the target architecture for the reset. It is a planning sketch, not a final package layout. The goal is to make module ownership explicit before implementation begins.

## Core Principle

One local-first single-user backend owns the product. Adapters translate transport concerns. Only the use-case boundaries that remove real duplication should be introduced. The LLM runtime owns prompt and action orchestration. The existing db package remains the repository layer unless a narrower repository boundary proves necessary.

## Target Shape

```text
Discord Adapter ─┐
HTTP Adapter    ├──> Shared Boundaries ───> LLM Runtime
Scheduler Worker┘           │                  │
                            │                  │
                            └──────> DB / Infrastructure
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

## Layer 2: Shared Boundaries

Only the boundaries that remove clear duplication should exist in the target shape.

### Turn Gateway

Responsibilities:

- Preserve one shared conversation across Discord and browser/API.
- Own durable single-user turn acquisition and release.
- Keep adapters from coordinating turns through process-local state.
- Append shared history and confirmation markers without becoming a large domain service.

Primary current inputs:

- [../../services/state.py](../../services/state.py)
- [../../bot/handler.py](../../bot/handler.py)
- [../../api/routes/chat.py](../../api/routes/chat.py)
- [../../db/chat.py](../../db/chat.py)

### Review Service

Responsibilities:

- Select due concepts.
- Generate quizzes.
- Bind quiz instance to reminder and session state.
- Assess answers.
- Register, resend, and resolve reminders.
- Recover delayed answers safely.

Primary current inputs:

- [../../services/tools_assess.py](../../services/tools_assess.py)
- [../../services/review_state.py](../../services/review_state.py)
- [../../services/chat_session.py](../../services/chat_session.py)
- [../../services/scheduler.py](../../services/scheduler.py)
- [../../db/review_reminders.py](../../db/review_reminders.py)

### Approval Policy Boundary

Responsibilities:

- Keep durable proposals only for destructive or long-running flows.
- Keep lightweight same-turn confirmations lightweight, but shared.
- Provide one place to decide which path a requested action belongs to.

Primary current inputs:

- [../../db/proposals.py](../../db/proposals.py)
- [../../services/views.py](../../services/views.py)
- [../../services/chat_actions.py](../../services/chat_actions.py)
- [../../services/chat_session.py](../../services/chat_session.py)

### Automation Runner Pattern

Responsibilities:

- Provide one reusable orchestration shape for maintenance and taxonomy.
- Reuse the same approval policy and runtime boundary.
- Preserve existing safety guardrails without inventing heavyweight peer services.

Primary current inputs:

- [../../services/pipeline.py](../../services/pipeline.py)
- [../../services/context.py](../../services/context.py)
- [../../services/scheduler.py](../../services/scheduler.py)
- [../../scripts/taxonomy_shadow_rebuild.py](../../scripts/taxonomy_shadow_rebuild.py)

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
- It must not remain the permanent owner of review lifecycle, approval policy, maintenance policy, taxonomy policy, or scheduler behavior.

## Layer 4: DB And Infrastructure

Responsibilities:

- Persist knowledge, reviews, reminders, approvals, and scheduler state.
- Keep the current db package as the default repository boundary unless a narrower split proves necessary.
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

The target architecture needs one canonical owner for each hard state machine, but not every concern needs a heavyweight service.

- Shared conversation continuity and turn ownership: owned by the Turn Gateway.
- Review/reminder lifecycle: owned by the Review service.
- Durable proposal state for destructive or long-running flows: owned by the existing proposal store plus approval policy boundary.
- Lightweight same-turn confirmations: remain lightweight and shared, but are not promoted into durable proposal state.
- Scheduler timing and shared ownership: owned by the Scheduler worker plus scheduler-state repositories.

Compatibility bridges may exist temporarily, but canonical write ownership must still be singular where real state machines exist.

## Cross-Cutting Policies

### User Context

- The current reset assumes a single-user product and keeps existing local-first identity rules.
- New workflow boundaries should not introduce fresh default-user assumptions even if dormant multi-user plumbing remains in code.

### Concurrency

- One active learning turn for the single-user product.
- Shared background jobs remain single-owner across processes.
- Cross-surface coordination must be durable rather than process-local.

### Safety

- Raw provider output never bypasses runtime validation.
- Destructive or long-running actions always go through durable approval policy.
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
- Process-local turn coordination in [../../services/state.py](../../services/state.py) once a durable turn gateway replaces it.
- Transport-specific confirmation glue currently spread across browser and Discord code where shared helpers can remove drift.

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