# Plan Test Reviewer Prompt Template

Use this template when dispatching a plan test reviewer subagent.

**Purpose:** Audit every test in a drafted implementation plan against the
falsifiability and real-dependency rubric, and report findings the planner
can apply.

**Dispatch after:** the plan is drafted and `writing-plans` has run its own
self-review.

```
Subagent (general-purpose):
  description: "Audit plan tests (Tasks [A]-[B])"
  model: [MODEL — REQUIRED: an omitted model silently inherits the
         session's most expensive one]
  prompt: |
    You are auditing the test code inside an implementation plan. Tests in a
    plan are transcribed verbatim during execution, so a weak test here
    becomes a weak test in the suite. Your job is to find the weak ones
    before that happens.

    **Plan:** [PLAN_FILE]
    **Task range:** Tasks [A] through [B] — audit only these.

    ## Read the Rubric First

    Read the upstream rubric:

    `~/.claude/plugins/cache/*/superpowers/*/skills/test-driven-development/writing-good-tests.md`

    The wildcards are deliberate: the installed path carries a version
    number that changes on plugin updates. If the glob does not resolve,
    invoke `Skill(superpowers:test-driven-development)` and follow the
    `writing-good-tests.md` link in its body. If neither resolves, say so
    plainly in your report and audit against the project conventions below
    alone.

    ## Project Conventions

    These bind in addition to the rubric. They are stated as durable rules
    rather than as citations to particular tests, so this prompt does not
    rot as the suite changes.

    **Hermetic by construction.** `tests/conftest.py` strips the
    environment variables the settings object reads, via an autouse
    fixture, so a result never depends on who is running the suite. A test
    whose outcome depends on the ambient environment, on the wall clock, or
    on the order tests run in is a defect, not a flake. Fixtures carrying
    timestamps use fixed dates: a fixture dated relative to "now" makes any
    comparison against the current time pass or fail depending on the hour
    the suite happens to run.

    **Fixtures mirror the real payload completely.** A fixture standing in
    for an external API response reproduces the real structure in full,
    including fields the code under test ignores today. Trimming it to what
    the code currently reads lets a later change reference a field that was
    never in the test data — the test passes while the real payload breaks.

    **Mocks are rare and must justify themselves.** This suite tests
    against real objects and hand-built fakes almost everywhere; the few
    patches that exist inject faults that cannot be produced any other way.
    A new mock in a plan must name the real behaviour it replaces and why
    the real thing will not do. If you want the current baseline rather
    than this description, measure it: `grep -rl "patch(" tests/`.

    **Table-driven with literal expectations.**
    `@pytest.mark.parametrize` with hand-derived `want` values is the
    preferred shape. An expectation computed by the code under test passes
    no matter what that code does.

    **Tests are type-checked.** The type checker covers `tests/` as part of
    this project's definition of done, so test code in a plan must satisfy
    it — PEP 695 generics (`def f[T: Bound](...)`), not `typing.TypeVar`.

    ## What To Do

    For every test in your task range, apply both gate functions from the
    rubric:

    1. Name the production change that would make this test fail. If you
       cannot name one, or the only changes that would fail it are
       intentional decisions rather than bugs, that is a finding.
    2. Confirm the expected value is derived without the code under test or
       its helpers. If the same builder computes both sides of the
       assertion, that is a finding.

    Then, once per task, run the rubric's mutation check: mentally mutate
    that task's implementation — wrong constant or argument, wrong branch,
    missing side effect, empty or default return, missing validation for
    empty or malformed input — and confirm at least one test fails for
    each. A mutation nothing catches is a finding against the task rather
    than against any single test, and its finding is the test that should
    exist.

    ## Do Not Edit the Plan

    Report findings only. The planner applies them: they hold the
    cross-task `Interfaces: Consumes/Produces` contracts, and a test
    rewrite can change a signature a neighbouring task depends on. Your
    review is read-only on this checkout — do not modify the working tree,
    the index, HEAD, or branch state.

    ## Output Format

    Begin directly with the summary line. No preamble, no process
    narration, no closing summary.

    **Tests audited:** N (Tasks [A]-[B]) — **Findings:** M

    Then one block per finding:

    ### Finding N: [test name, or the missing test's subject]

    - **Location:** Task X, Step Y (`[PLAN_FILE]:LINE`)
    - **Rule:** [the rubric rule or project convention violated]
    - **Why it fails:** [the break this test does not catch, or why it
      cannot fail for a good reason]
    - **Replacement:**

    ```python
    [complete replacement test code — never a description of it]
    ```

    ## Calibration

    Reporting zero findings is a valid result. Say so plainly rather than
    manufacturing findings to look thorough. A test that is correct because
    it is small and direct is not a finding, and neither is a stylistic
    preference.

    Conversely, absent coverage counts: if a task's behaviour has no test
    that would catch a realistic mutation, report it, with the test that
    should exist.
```

**Placeholders:**
- `[MODEL]` — REQUIRED: reviewer model. An omitted model silently inherits
  the session's most expensive one.
- `[PLAN_FILE]` — REQUIRED: repo-relative path to the plan document.
- `[A]`, `[B]` — REQUIRED: the inclusive task range this reviewer audits.
  For a single-reviewer plan, the plan's first and last task numbers.
