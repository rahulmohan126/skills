# Subagent briefs (complex plans)

Use these as the prompts when you spawn the test-writer and implementer subagents. Fill in the angle-bracket parts. Keep each brief to what's written here. In particular, don't pass your own implementation ideas to the test writer. Keeping them out is the whole reason it's a separate agent.

## Test-writer brief

```
You are writing the tests for a feature before any implementation exists.

Plan: <absolute path to plan file>
Repo: <repo root>
Test conventions: <framework(s), test directory layout, naming, how to run, existing fixtures/helpers worth reusing>

Your job:
1. Read the plan. The success criteria (SC-n) and the public contract are your spec. Read existing code only to learn conventions and the interfaces the feature plugs into. Do not design the implementation.
2. Write tests that verify every success criterion at the level the plan assigns (unit / integration / e2e). Name or tag each test with its SC id.
3. Assert only on observable behavior through the public contract. Don't depend on internals the plan leaves open, since a correct alternative implementation must also pass.
4. Use deterministic synthetic fixtures. Mock only true external boundaries (third-party services, clock, randomness).
5. Run the tests. Confirm each fails because the feature is missing (import error, missing route, assertion mismatch), not because of a broken test or harness. Fix any test that fails for the wrong reason.
6. Do not write or stub any production code. The one exception: if the test runner literally cannot load without some file existing, create the most minimal empty placeholder and say so.

Report back with:
- the test files you created, and each test → SC mapping
- the command to run them, and the failing output summary
- any criterion you couldn't test, and why
- anything in the plan that was ambiguous enough to force a guess
```

## Implementer brief

```
You are implementing a feature to satisfy a plan and a set of frozen tests.

Plan: <absolute path to plan file>
Frozen tests: <file list>
Run with: <command(s)>
Repo: <repo root>

Rules:
- Implement what the plan describes. Don't write code that recognizes the tests: no hardcoded expected values, no test-mode detection, no special-casing fixtures.
- The tests are frozen. Change one only if you can quote plan text it contradicts. Log every change in the plan's "Test changes" section (test, contradicted text, change, reason). Never weaken an assertion just to get past a failure, and never skip or xfail a test to get to green.
- If the plan itself seems wrong, stop and report it. Don't resolve requirement questions yourself.
- Build in dependency order (types/schemas → persistence/adapters → services → routes/commands → UI).

Loop: run tests → triage each failure (implementation bug / environment / test contradicts plan) → fix → re-run. Add one line per iteration to the plan's progress log. When the plan's tests pass, run the full suite plus the project's lint/typecheck/build gates. If a failure survives ~3 genuinely different fix attempts, stop and report.

Report back with:
- the files changed
- the final test results (plan tests and full suite) and gate results
- any test changes, with the reasons
- deviations from the plan, and open risks
```

## Orchestrator review between phases

After the test writer reports, check before freezing:
- Every SC has at least one test, at the level the plan assigned.
- No test asserts on an internal detail the plan left open.
- The failures are the right kind (feature missing, not a broken harness).

After the implementer reports, don't take its word for it. Re-run the tests and gates yourself, read the diff of any test files since the freeze point, and only then hand off.
