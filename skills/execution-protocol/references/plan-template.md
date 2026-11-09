# Plan template

Copy this structure into `docs/plans/<feature-slug>.md` (or the project's plan location). Leave out any section that doesn't apply, but keep the order. Write in prose and tables, not code. The only code-like text should be the names in the public contract (module, function, command or endpoint names), since tests need them.

---

```markdown
# <Feature name>

**Status:** Planning | Tests written | Implementing | Verifying | Done | Blocked
**Size:** Simple | Complex (one line on why)

## Goal
One or two sentences: what changes for the user or the system, and why it matters.

## Scope
- In scope: …
- Non-goals: … (things someone might reasonably assume are included but aren't)

## Context
What already exists that this builds on: relevant modules, flows, constraints from the codebase or docs. Mention existing tests that cover nearby behavior.

## User flows / behavior
Step-by-step description of each flow, from the outside. Cover each state that applies: success, empty, loading, error, permission-denied, invalid input.

## Public contract
The surface tests will exercise. For each entry point:
- **Name** (function, CLI command, endpoint, component), and where it lives if that's fixed by convention
- **Inputs**: what's accepted, and what's rejected
- **Outputs and side effects**: return values, responses, persisted changes, emitted events
- **Errors**: each failure case and how it's surfaced

Don't include internal helpers, algorithms, data structures or library choices.

## Success criteria
| ID | Criterion (observable, testable) | Test level(s) |
|----|----------------------------------|---------------|
| SC-1 | … | Unit |
| SC-2 | … | Integration |
| SC-3 | … | E2E |

## Test strategy
- Unit: what's isolated and the key edge cases
- Integration: which components interact, and what's real versus faked
- E2E: which workflow path(s), and how they're driven (browser, CLI, HTTP client)
- Gaps: any level the project can't run yet, and the substitute

## Assumptions
Choices made without explicit confirmation, each of which could be revisited.

## Risks
What could go wrong, and how it would show up.

## Open decisions
Questions only the user can answer. For each, note what's blocked by it.

## Progress log
- <date> Plan written
- <date> Tests written and frozen: <file list>, <commit or HEAD ref>
- <date> Loop iteration 1: <what failed> → <cause> → <fix>
- …

## Test changes
Every modification to a frozen test: test name, the plan text it contradicted, the change, the reason. Write "None" if there were none.
```
