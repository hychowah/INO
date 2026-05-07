# Post-Reset Delivery Master Plan

## Objective

Turn the completed architecture simplification reset into a stable, documented, and merge-ready baseline without reopening broad framework churn.

## Current Condition

| Area | Current state | Implication |
|---|---|---|
| Architecture reset | Completed on the active simplify branch, including shared chat payload ownership, shared admin orchestration, DTO-owned adapter projections, and shared Discord send paths | The repo is in a better structural position, but the next work should harden and document the new seams rather than re-refactor them immediately |
| Validation | The reset was protected by focused pytest slices and targeted frontend checks | The repo still needs one explicit post-reset validation matrix that is easy to rerun before merge or release |
| Documentation | `docs/plans/` was empty and the docs indexes still said there were no active plans | This file and its tracker now become the active coordination surface |
| Deferred debt | Some intentional follow-up remains, including residue audits and older compatibility/debt items such as the frozen `ease_factor` field noted in `docs/DEVNOTES.md` | Cleanup needs to stay scoped and evidence-driven so it does not turn into another open-ended rewrite |

## Success Criteria

| ID | Outcome |
|---|---|
| S1 | The post-reset ownership seams are fully reflected in the docs that own those facts |
| S2 | One repeatable post-reset validation matrix exists for backend, frontend, and shared chat flows, with deterministic gates separated from advisory live smoke |
| S3 | Remaining dead residue and compatibility bridges are either removed or explicitly documented as intentional |
| S4 | The simplify branch has a merge-ready checklist with no ambiguity about what still blocks integration |

## Guardrails

| Rule | Why it matters |
|---|---|
| Prefer residue removal and validation hardening over new product features | The reset only pays off if the new seams stay stable long enough to validate |
| Fix root ownership mismatches, not adapter-local symptoms | The reset already established shared seams; follow-up work should reinforce them |
| Keep cleanup evidence-based | Remove only residue that can be tied to an obsolete owner, compatibility path, or duplicated contract |
| Preserve local-first user identity and typed reminder state boundaries | Those were explicit architectural decisions during the reset and should not be casually reopened |

## Workstreams

| Stream | Scope | Deliverables | Exit signal |
|---|---|---|---|
| W1. Documentation Reconciliation | Align docs with the shipped post-reset ownership seams | Updates to `docs/API.md`, `docs/ARCHITECTURE.md`, `docs/index.md`, `docs/DOC_INDEX.md`, `CODING.md`, and `CHANGELOG.md` only where the reset changed ownership or operator behavior | No stale docs still describe pre-reset owners, aliases, or duplicate adapter logic |
| W2. Validation Matrix | Turn the reset's focused regressions into a repeatable post-reset check suite | A documented narrow command matrix for backend and frontend deterministic gates, plus advisory harness guidance for real chat-flow smoke | A contributor can run the matrix without reconstructing the reset history or confusing advisory smoke with merge gates |
| W3. Residue Retirement | Remove or formally classify remaining dead paths and compatibility bridges | Targeted cleanup of obsolete code or docs, including the contradictory frontend route-alias residue, plus DEVNOTES entries for intentional carry-forward debt | No high-confidence dead residue remains in the shared chat, review, scheduler, approval, or post-reset browser route surfaces |
| W4. Merge Readiness | Close the loop from refactor branch to safe integration | A blocker list, explicit merge criteria, and final verification notes | The branch can be evaluated for merge on current evidence rather than on tribal knowledge |

## Milestone Order

| Milestone | Streams | Intent |
|---|---|---|
| M1. Reconcile docs | W1 | Make the new ownership model legible before more cleanup lands |
| M2. Codify validation | W2 | Freeze a repeatable proof that the post-reset system still works across surfaces |
| M3. Retire residue | W3 | Remove what the reset made obviously obsolete, without broadening scope |
| M4. Prepare merge | W4 | Leave the branch with a clear go/no-go checklist |

## Out Of Scope

| Not in this plan | Reason |
|---|---|
| Major new product surfaces | They would hide whether the reset itself is stable |
| Another framework migration | The current repo state needs consolidation, not another platform pivot |
| Broad schema redesign | Only targeted debt cleanup should happen unless a blocker proves otherwise |

## Exit Condition

This plan is complete when the documentation reflects the post-reset architecture, the validation matrix is written and executed, the remaining residue list is either closed or intentionally documented, and the simplify branch can be judged for merge without reconstructing prior session context.
