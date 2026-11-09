---
name: execution-protocol
description: A plan → tests → implement → verify loop for building features and fixing bugs. Write a behavior-level plan with testable success criteria and no code. Then write unit, integration and e2e tests from the plan before any implementation exists. Then implement until those tests pass, and run a test/fix/re-run loop until everything is green. Use this whenever the user asks to implement, build, add or ship a feature, execute or carry out a plan, work through a spec or ticket, do test-driven or test-first development, or make a non-trivial change to a codebase, even if they don't mention tests or plans. Also use it when the user hands over an existing plan document and says "go" or "execute this".
---

# Execution protocol

This is a protocol for turning a feature request or a plan into working, verified code. It has four phases, and their order is the point:

1. **Plan** what the feature must do and how success is judged. Describe behavior, not code.
2. **Write tests** from the plan, before any implementation exists.
3. **Implement** until the tests pass.
4. **Loop**: run the tests, fix, and re-run until green, then verify and hand off.

## Why this order matters

When one agent writes code and then writes tests, the tests end up describing the code it just wrote, including its bugs. They pass because they mirror the implementation, not because the feature is right. The same thing happens one step earlier: a plan full of code snippets locks in an implementation before anyone has thought hard about the behavior, and both the tests and the code then follow those snippets.

So each phase is kept "upstream" of the next:
- The plan describes **what** and **why**, and says nothing about **how**. Then the tests are derived from intended behavior.
- The tests are written **before** the implementation. Then they check the plan, not the code.
- The tests are **frozen** while implementing. Then the implementation has to meet the tests, and the tests can't be bent to fit the implementation.

Keep this reasoning in mind. When a situation isn't covered below, ask what keeps the tests an independent check on the code, and do that.

## Phase 0: Intake

Before planning, get oriented. Keep it short; you only need enough to plan well.

- Read the project's agent and contributor docs (`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, the README) and any spec or plan the user pointed to.
- Find the test setup: the frameworks in use, where tests live, how they're named, how they're run, and whether integration or e2e tooling exists (Playwright, Cypress, supertest, pytest fixtures, a test database). Note what's missing.
- Look at the existing code the feature touches, and the public interfaces it will need to plug into.
- Check the working tree (`git status`). Don't disturb unrelated changes.

If the user already gave you a plan, go to Phase 1 and **review** that plan against the template rather than writing a new one. Fill in any missing success criteria or test mapping. If the plan contains code snippets, treat them as suggestions, not requirements, unless the user says they're required. Point this out once, briefly.

## Phase 1: Plan

Write the plan to a Markdown file in the repo. Follow the project's convention if it has one; otherwise use `docs/plans/<feature-slug>.md`. A file survives context resets and handoffs, and it gives the user and any subagents a single source of truth. Use the structure in `references/plan-template.md`.

### Describe behavior, not implementation

Unless the user explicitly asks for implementation detail, the plan contains **no code snippets and no internal design**: no function bodies, algorithms, data structures, class hierarchies or library choices made "because that's how I'd write it".

It **does** contain the **public contract**, which is the surface the tests will exercise. Tests written before the code can't run without one. Examples:
- the name of a module, function, CLI command or HTTP endpoint that callers or tests use,
- its inputs, outputs, error cases and side effects, described in prose or a table,
- the user-visible flows and states (loading, empty, error, success),
- data that persists and what must hold true about it.

A quick test for whether a detail belongs: *would a reasonable alternative implementation need to change this to stay correct?* If yes, it's part of the contract and goes in. If no, it's an implementation choice and stays out. For example, "`parse_duration(text)` returns total seconds and raises `ValueError` on malformed input" is contract. "Use a regex with named groups" is implementation.

### Success criteria are the backbone

Number each success criterion (`SC-1`, `SC-2`, …). Each one must be observable and testable: someone could write a test for it without guessing. "Handles errors gracefully" is too vague. "Returns 400 with a field-level message when `email` is missing" is testable. Include boundary and failure cases, not just the happy path. Most bugs live in those cases.

Then map each criterion to the test level(s) that will verify it:

| Level | What it verifies | Typical shape |
|---|---|---|
| **Unit** | One function or module in isolation | Pure logic, validation, edge cases. Fast, no I/O. |
| **Integration** | That separate components or services interact correctly | Service ↔ database, route ↔ handler ↔ store, module ↔ external API behind a fake |
| **E2E** | One whole workflow path, end to end | User action through the UI or CLI down to persisted result. Can span frontend and backend. |

Not every feature needs all three levels. A pure utility may need only unit tests. Every criterion needs at least one test, though, and a feature that crosses component boundaries should have at least one integration test. A feature with a user-facing workflow should have at least one e2e test, if the project can run e2e tests. If it can't, say so in the plan and propose the closest substitute. Don't skip the level silently.

### Size the work

At the end of the plan, mark it **simple** or **complex**. This decides how Phases 2–4 are run (see "Single agent or subagents" below). Mark it complex if any of these apply:
- it touches more than one component or service (for example frontend and backend, or app and database),
- it needs integration or e2e tests,
- it has more than about 5 success criteria,
- the implementation path is not obvious.

Otherwise mark it simple.

### Checkpoint

Show the user the plan: a short summary plus the file path. If they've told you to proceed without check-ins, continue. Otherwise, wait for approval before writing tests. This is the cheapest point to catch a misunderstanding. Once tests exist, every change to the plan means changing them too.

## Phase 2: Write the tests

Write tests from the plan's success criteria. At this point the plan and the existing codebase are your only inputs; no implementation of the new behavior exists yet, and you shouldn't sketch one in your head and test against it. Write each test as if someone else will do the implementing.

- Follow the project's existing test conventions: framework, layout, naming, fixtures. Add new tooling only if the plan calls for a test level the project can't run yet, and keep it minimal.
- Name or tag each test with the criterion it verifies (for example `test_sc3_rejects_negative_quantity`, or a comment `# SC-3`). Then the plan, the tests and the final report can be cross-checked.
- Assert on observable behavior through the public contract: return values, HTTP responses, persisted rows, rendered UI, CLI output. Don't assert on internals the plan left open. A test that breaks when someone refactors correctly is testing the implementation, not the feature.
- Use deterministic, synthetic fixtures. Mock only true external boundaries (third-party APIs, the clock, randomness), never the behavior under test.
- Integration tests should use real collaborators where practical, for example a temporary or in-memory database rather than a mocked repository. Real collaborators are the whole point of that level.

**Confirm the tests fail for the right reason.** Run them. They should fail because the feature doesn't exist yet: an import error, a missing route, an assertion mismatch. They should not fail because of a syntax error, a broken fixture or a misconfigured runner. A test that can't fail for the right reason gives no signal. A test that already passes is either a regression guard for existing behavior (fine, note it) or isn't testing anything new (fix it).

**Freeze the tests.** Record exactly which test files belong to this plan in the plan's progress log. If you're in a git repo and committing is acceptable to the user, commit the tests as their own commit. Otherwise note the current HEAD and the file list, so you can later show any test change with `git diff`. Either way, the frozen tests become the contract for Phase 3.

## Phase 3: Implement

Now implement, working from both the plan and the tests.

- Build in dependency order: data types and schemas, then persistence and adapters, then services, then routes and commands, then UI. Then each layer's tests can turn green as you go.
- Write the code the plan describes, not code that recognizes the tests. Don't hardcode expected values, don't detect "test mode", and don't special-case fixture inputs. The tests are a sample of the behavior the plan requires; the implementation must meet the plan for all inputs.
- Stay inside the plan's scope. If you find the plan is wrong or incomplete, stop and say so. Update the plan, and if needed the tests, through the path described in Phase 4. Don't quietly build something different.

## Phase 4: Test/fix loop

Run the tests, fix, and run them again until they pass:

1. **Run** the plan's tests. Start with the narrowest relevant set for fast feedback.
2. **Triage** each failure into one of three kinds:
   - **Implementation bug**: the code doesn't do what the plan says. Fix the code. This is the usual case.
   - **Environment or harness problem**: a missing dependency, a port conflict, a bad fixture path. Fix the setup, not the assertions.
   - **The test contradicts the plan**: the test asserts something the plan doesn't require, or it asserts the opposite of what the plan says. See "Changing a frozen test" below.
3. **Fix** the cause and **re-run**. Each iteration, write one line in the plan's progress log: what failed, the cause, and what changed. This keeps the loop honest and shows the user what happened.
4. When the plan's tests pass, run the **whole** test suite to catch regressions. Then run the project's other gates (lint, typecheck, format, build), whichever exist.

**Changing a frozen test.** By default the tests don't change. "The test is inconvenient" and "my implementation does it differently" are not reasons to change one. Change a test only when you can point to the plan text it contradicts. When you do:
- log it in the plan under "Test changes": the test, the plan text it contradicted, what you changed, and why;
- keep the change as small as possible, and never weaken an assertion just to get past a failure;
- tell the user about it in the handoff.

If the test is right and the *plan* is wrong, because the requirement itself was mistaken, that's a product decision. Raise it with the user instead of resolving it on your own.

**Know when to stop.** If the same failure survives about three genuinely different fix attempts, or the loop stops making progress (the failing set isn't shrinking), stop. Report what you tried and what you suspect. Thrashing burns context and tends to produce code that's worse each round.

## Phase 5: Verify and hand off

Before reporting done, read your own diff once. Look for leftover debug code, scope creep, secrets, missing input validation at trust boundaries, and any test that was skipped or marked as an expected failure (`.skip`, `xfail`) to get to green. That last one counts as a test change and must be logged.

Then report to the user:
- **Result**: each success criterion, the test(s) that verify it, and whether they pass.
- **Commands run**, with their results (test suite, lint, typecheck, build).
- **Test changes**: every frozen test that was modified, with the reason, or "none".
- **Deviations from the plan**, and why.
- **Open risks and decisions** the user should know about.

Update the plan file's status to match. It's the durable record.

## Single agent or subagents

**Simple plans**: one agent runs every phase in order. The ordering and the frozen tests provide the separation.

**Complex plans**: use separate subagents, so the test author has never seen the implementation discussed. Their tests then really are derived from the plan alone. Subagents are only useful if each one gets exactly the context its role needs. `references/subagent-briefs.md` has the briefs.

1. **You (orchestrator)** do intake and the plan, and get the plan approved.
2. **Test-writer subagent**: gets the plan file path and the repo's test conventions, and nothing else. In particular, it gets none of your implementation ideas. It writes the tests, confirms they fail for the right reason, and reports back.
3. **You** review the tests against the plan: does every criterion have a test, and do the tests stick to the public contract? Then freeze them.
4. **Implementer subagent**: gets the plan path and the frozen test list. It implements and runs the test/fix loop under the same rules for changing tests, and reports back with its progress log.
5. **You** verify independently. Re-run the suite yourself rather than trusting the report, review any test changes, and hand off.

If subagents aren't available in your environment, run a complex plan as a single agent. Be extra strict about not reasoning about implementation while writing tests.

## When to ask the user

Proceed on your own for reversible engineering choices that the plan or the codebase conventions cover. Stop and ask when a decision would:
- change what the feature does for users (the plan's requirements, not its tests),
- affect permissions, security posture, data retention, or irreversible data migrations,
- add significant dependencies, paid services or infrastructure,
- require modifying code outside the plan's scope in a way that could break other things.

When you're blocked on one of these, record it in the plan's "Open decisions" section. If the decision only blocks part of the work, finish everything that doesn't depend on it.
