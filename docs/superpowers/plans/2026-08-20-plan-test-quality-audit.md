# Plan Test-Quality Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a project skill that audits the test code inside a drafted implementation plan against the superpowers test-quality rubric, plus the `CLAUDE.md` wiring that makes the pass mandatory.

**Architecture:** Detection, not prevention. A `reviewer-prompt.md` template carries the rubric and output contract; a `SKILL.md` controller decides when to run and dispatches a fresh subagent per task range; `CLAUDE.md` makes the pass a required step before a plan is finished. The reviewer reports findings only — the planner applies them, because only the planner holds the cross-task interface contracts.

**Tech Stack:** Markdown documents. No Python, no dependencies, no runtime.

**Spec:** `docs/superpowers/specs/2026-08-20-plan-test-quality-audit-design.md`

## Global Constraints

- Scope is this repository only. Changes are confined to `CLAUDE.md` and `.claude/skills/`.
- The upstream rubric is referenced by version-wildcarded glob: `~/.claude/plugins/cache/*/superpowers/*/skills/test-driven-development/writing-good-tests.md`. Never a version-pinned literal path — the installed path is `.../superpowers/6.2.0/...` and breaks on plugin update.
- Fallback when that glob does not resolve: invoke `Skill(superpowers:test-driven-development)` and follow the `writing-good-tests.md` link in its body.
- The reviewer returns findings only. It never edits the plan.
- Plans of 15 tasks or fewer get one reviewer. Larger plans are split into contiguous ranges of at most 15 tasks, one reviewer each, dispatched in parallel.
- The audit runs after `writing-plans` completes its self-review, before the execution handoff. It is skipped only when the plan contains no test code.
- **No pytest tests over document text.** Documents that instruct agents are tested by the consuming agent's behaviour (Task 3), never by asserting their contents. A test that greps `SKILL.md` for a phrase proves only that the source is the source.
- **Durable references only.** Neither deliverable cites an individual test, a line number, a test count, or a commit hash. Those rot silently — nothing checks them, so a drifted citation misleads the reviewer instead of failing loudly — and they tie the documents to this repository for no gain. Where a number carries weight, give the command that recomputes it. Stable paths (`tests/conftest.py`), architectural facts, and toolchain facts are durable and may be named. References to superpowers skills are fine: the shortfall in those skills is what drives this work.
- Definition of Done applies to every task: `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, `uv run pytest` must pass before a task is complete.

**Note on this plan:** it contains no `def test_` bodies, so by the skill's own rule the audit does not apply to it. That is the intended behaviour, not an oversight.

## File Structure

| File | Responsibility |
|------|----------------|
| `.claude/skills/reviewing-plan-tests/reviewer-prompt.md` | The subagent prompt: rubric pointers, project conventions, gate functions, output contract. Lifted verbatim at dispatch time. |
| `.claude/skills/reviewing-plan-tests/SKILL.md` | The controller: when the audit runs, how to size and dispatch reviewers, how to apply findings. |
| `CLAUDE.md` | Makes the pass mandatory and distinguishes it from the machine-checked Definition of Done. |

The split follows the superpowers convention (`subagent-driven-development/` keeps `implementer-prompt.md` beside `SKILL.md`): the controller stays short and readable, the prompt stays copy-pasteable.

---

### Task 1: Reviewer Prompt Template

**Files:**
- Create: `.claude/skills/reviewing-plan-tests/reviewer-prompt.md`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a prompt template with the placeholders `[MODEL]`, `[PLAN_FILE]`, `[A]`, `[B]`. Task 2's `SKILL.md` refers to this file by the relative name `reviewer-prompt.md` and requires every placeholder to be filled at dispatch.

- [ ] **Step 1: Verify the two durable references this document will make**

The prompt deliberately makes no reference to individual tests, line numbers, or counts — those rot silently as the suite changes, and nothing would catch a citation that has drifted onto the wrong line. It refers only to facts that outlive edits to any single test. Confirm both:

```bash
ls ~/.claude/plugins/cache/*/superpowers/*/skills/test-driven-development/writing-good-tests.md
grep -n "autouse\|delenv" tests/conftest.py
```

Expected: the glob resolves to exactly one path; `tests/conftest.py` contains an autouse fixture that deletes environment variables. If the conftest no longer strips the environment, the hermeticity convention in Step 2 is describing something that is no longer true — fix the convention, not the check.

- [ ] **Step 2: Write the prompt template**

**Superseded — do not transcribe this verbatim.** The template below is the
prompt as first drafted, kept as a record of what Task 3 measured against.
Task 3's validation replaced its rubric-loading section, its output contract
and its calibration paragraph, because the original degrades silently when
the rubric cannot be read and cannot express a finding whose remedy is
deletion. Re-executing this step from the text below would reconstruct those
defects. Take the shipped file as the source of truth.

Create `.claude/skills/reviewing-plan-tests/reviewer-prompt.md`:

````markdown
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
````

- [ ] **Step 3: Verify the document names no individual test, line number, or count**

The conventions must survive edits to any single test. A citation to a specific test is a silent staleness bug, and it also ties the prompt to this repository for no gain.

```bash
grep -nE "\.py:[0-9]|[0-9]+ test files|test_[a-z_]+\.py" .claude/skills/reviewing-plan-tests/reviewer-prompt.md
```

Expected: no matches. The prompt's two remaining repo references — `tests/conftest.py` and the `grep -rl "patch(" tests/` calibration command — are a stable path and a recomputation command, neither of which the pattern catches and neither of which goes stale. If the grep does return a hit, replace the citation with the durable rule it was illustrating.

Do not add a test that asserts the prompt file's contents. The prompt is tested by reviewer behaviour in Task 3.

- [ ] **Step 4: Run the Definition of Done**

```bash
uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Expected: all four pass. No Python changed, so a failure here means something unrelated broke — investigate before continuing.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/reviewing-plan-tests/reviewer-prompt.md
git commit -m "feat: add the plan test reviewer prompt template"
```

---

### Task 2: Skill Controller and CLAUDE.md Wiring

**Files:**
- Create: `.claude/skills/reviewing-plan-tests/SKILL.md`
- Modify: `CLAUDE.md` (insert a new section after `## Definition of Done`, before `## Toolchain`)

**Interfaces:**
- Consumes: `reviewer-prompt.md` from Task 1, referenced by that relative name, with placeholders `[MODEL]`, `[PLAN_FILE]`, `[A]`, `[B]`.
- Produces: a skill invocable as `reviewing-plan-tests`. `CLAUDE.md` refers to it by exactly that name, which must match the `name:` field in the skill's frontmatter.

- [ ] **Step 1: Write the skill controller**

Create `.claude/skills/reviewing-plan-tests/SKILL.md`:

```markdown
---
name: reviewing-plan-tests
description: Use when an implementation plan containing test code has been drafted and before it is handed off for execution - audits every test in the plan for falsifiability and real-dependency discipline
---

# Reviewing Plan Tests

## Why This Exists

Implementation plans carry literal test code, and execution transcribes it
verbatim. A weak test in the plan becomes a weak test in the suite.

The rubric that catches weak tests, `writing-good-tests.md`, is reachable
from exactly one place in the superpowers plugin: the
`test-driven-development` skill, whose trigger is "before writing
implementation code". That fires a phase after plan tests are written, so
the rubric arrives too late to shape them. Every plan here that contained
test code has needed a post-hoc pass against it. This skill makes that pass
routine instead of remembered.

## When To Run

After `writing-plans` completes its self-review, before the execution
handoff. A plan containing test code is not finished until this pass has
run.

Skip only when the plan contains no test code:

```bash
grep -c "def test_" docs/superpowers/plans/<plan>.md
```

A count of zero means the plan produces documents or configuration rather
than tested code, and there is nothing to audit.

## How To Run

**Dispatch a subagent. Do not audit the tests yourself.** You wrote them,
and a reader who wrote the tests is biased toward them the same way a test
written after the code is biased by the code it describes. Fresh context is
the mechanism here, not a formality.

Count the plan's tasks. Plans of 15 tasks or fewer get one reviewer. Larger
plans are split into contiguous ranges of at most 15 tasks, one reviewer
each, dispatched in parallel — a several-thousand-line plan is more than one
reader can hold.

Use the prompt template in `reviewer-prompt.md`, filling every placeholder.

## Applying the Findings

The reviewer reports; you apply. For each finding, either apply the
replacement test or record why you are not — a finding you disagree with is
a decision worth writing down, not one to leave silent.

Then re-run the type-consistency check from `writing-plans`' self-review.
Rewriting a test can change a signature that a neighbouring task's
`Interfaces: Consumes` block depends on, and nothing downstream would catch
it. Check the names and types every amended test touches against the tasks
that consume them.

Commit the revisions separately from the plan itself, and list the findings
you applied in the commit message. That keeps the audit's effect legible in
history, and it leaves behind an answer key for anyone later measuring
whether this gate is working.
```

- [ ] **Step 2: Verify the skill is discoverable and its references resolve**

```bash
head -5 .claude/skills/reviewing-plan-tests/SKILL.md
ls .claude/skills/reviewing-plan-tests/reviewer-prompt.md
grep -nE "\.py:[0-9]|[0-9]+ \`def test_\`|\b[0-9a-f]{7}\b" .claude/skills/reviewing-plan-tests/SKILL.md
```

Expected: frontmatter opens with `---`, carries `name: reviewing-plan-tests` and a `description:`; the sibling prompt file exists; the third command returns no matches, confirming the controller cites no line numbers, test counts, or commit hashes that would go stale.

- [ ] **Step 3: Wire it into CLAUDE.md**

Insert this section immediately after the `## Definition of Done` section and before `## Toolchain`:

```markdown
## Test quality

Test code written into an implementation plan is real test code. Execution
transcribes it verbatim, so a weak test in the plan becomes a weak test in
the suite.

A plan containing test code is not finished until those tests have been
audited: use the `reviewing-plan-tests` skill, which dispatches a fresh
reviewer over every test in the plan and reports findings for the planner
to apply. This gate is separate from the Definition of Done above — that
one is machine-checked, this one is not.
```

- [ ] **Step 4: Verify the skill name in CLAUDE.md matches the skill**

A name mismatch makes the instruction unfollowable, and nothing else would
catch it.

```bash
grep -n "reviewing-plan-tests" CLAUDE.md .claude/skills/reviewing-plan-tests/SKILL.md
```

Expected: the name in the `CLAUDE.md` prose is byte-identical to the `name:`
value in the skill frontmatter.

- [ ] **Step 5: Run the Definition of Done**

```bash
uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Expected: all four pass.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/reviewing-plan-tests/SKILL.md CLAUDE.md
git commit -m "feat: gate plans on a test-quality audit"
```

---

### Task 3: Behavioural Validation Against the Answer Key

**Files:**
- Create: `.superpowers/validation/pluggable-sources-pre-pass.md` (scratch; `.superpowers/` is gitignored)
- Modify: `.claude/skills/reviewing-plan-tests/reviewer-prompt.md` (only if the audit misses the bar)

**Interfaces:**
- Consumes: the skill and prompt from Tasks 1 and 2.
- Produces: a pass/fail verdict on whether the gate works, and any prompt revisions that verdict forces.

This task is the plan's only real test. Tasks 1 and 2 produce documents that
instruct agents, and such documents are tested by the consuming agent's
behaviour rather than by assertions on their text.

- [ ] **Step 1: Extract the plan as originally authored**

`0d4d4cd` applied the manual re-check to the pluggable-sources plan. Its
parent, `5ed6747`, is the plan before that pass — the uncontaminated input.

```bash
mkdir -p .superpowers/validation
git show 5ed6747:docs/superpowers/plans/2026-08-18-pluggable-sources.md > .superpowers/validation/pluggable-sources-pre-pass.md
grep -c "def test_" .superpowers/validation/pluggable-sources-pre-pass.md
```

Expected: the file is written and contains test bodies. **Do not use the
plan at `HEAD`** — the fixes are already applied there, so an audit would
correctly find little and the result would say nothing about the gate.

- [ ] **Step 2: Record the answer key before running the audit**

Read the six findings the manual pass made, so scoring is against a written
key rather than a memory formed after seeing the results:

```bash
git show --format=%B --no-patch 0d4d4cd
```

The six findings are:

1. A fixture dated the same day as the run, making the `fetched_at > created_at` assertion time-dependent — **retired, not scorable**
2. An incomplete Lemmy payload fixture that did not mirror the real API
3. A runaway-paging hang, converted into a named failure
4. Assertions on private attributes rather than on request URLs
5. A change detector
6. A second change detector

Item 1 is retired and the live key is five items. The defect was that the
fixture's date matched the day the plan was authored; enough time has since
passed that the date sits in the past and the assertion holds on its own. A
reviewer that reports no defect there today is correct. The design spec
records the dates and the lesson about keys built from clock-sensitive
defects.

- [ ] **Step 3: Run the audit cold, in an isolated checkout**

"Cold" governs two things, and the first validation attempt was void because
it governed only one. What the reviewer is *told* must exclude the key; what
the reviewer can *read* must exclude the answer too. A reviewer dispatched
into the working tree can open the finished post-fix suite, the skill that is
under test, and the commit that holds the key — none of which a genuinely
cold reader would have. Isolate both.

**Isolate the checkout.** Create a detached `git worktree` at the pre-pass
commit and run the reviewer with that as its working directory. A detached
worktree at that commit is the proven approach: it reconstructs the tree as
it stood before the manual pass, so the post-pass suite, the skill under
test, and the key commit are all simply absent rather than merely
off-limits.

Before dispatching, verify the isolation rather than assuming it. Confirm in
that worktree that the post-pass test module does not exist, that the
hermeticity fixture is not yet in `tests/conftest.py`, that there is no
`.claude/` directory, and that the key commit is unreachable from the
checked-out revision. Record what those checks returned; unverified
isolation is the failure this step exists to prevent.

**Isolate what the reviewer is told.** Dispatch using `reviewer-prompt.md`
with every placeholder filled: `[PLAN_FILE]` set to the extracted pre-pass
plan and `[A]`/`[B]` set to that plan's first and last task numbers. The
reviewer must not be told what the answer key contains, which commits are
involved, how many findings to expect, or that a validation is under way. It
gets the pre-pass plan and the prompt, nothing else.

**Preserve the verbatim output.** Write the reviewer's output to a durable
artifact under this plan's `.superpowers/sdd/` directory, byte for byte as
returned, before scoring anything. A paraphrase cannot be re-scored, cannot
be checked for a category of finding that turns out to matter later, and
cannot settle a disagreement about what the reviewer actually said. Score
from the saved artifact, and do not delete it when the scratch plan file is
cleaned up.

Remove the temporary worktree with `git worktree remove` once the output is
saved.

- [ ] **Step 4: Score the findings against the key**

The gate ships if **both** conditions hold:

- Finding 2 is surfaced. It is the case the project conventions in
  `reviewer-prompt.md` name explicitly. If the reviewer misses the case its
  own prompt spells out, the prompt is not working.
- At least two of findings 3, 4, 5, 6 are surfaced.

Findings beyond the key are not failures and do not count toward the bar —
they are the expected upside of a fresh reader with the rubric in hand, but
`0d4d4cd` is one approved pass rather than exhaustive truth, so they cannot
be scored.

- [ ] **Step 5: If the bar is missed, revise and re-run**

Diagnose which rule failed to fire, strengthen that section of
`reviewer-prompt.md`, and repeat Steps 3 and 4 with a fresh reviewer.

Cap this at three attempts. If the bar is still missed on the third,
stop and report BLOCKED with the findings from each attempt — three failures
means the design is wrong, not the wording, and that is a decision for the
human partner rather than a fourth revision.

**If the result is inconclusive rather than failing** — the reviewer returns
substantial, plausible findings that neither clearly match nor clearly miss
the key, so the six-item key looks too small to judge by — replay against the
second corpus instead of revising the prompt. `c9fd700` is the equivalent
manual pass over the 138-test pipeline plan, replayable from its parent
`c999046`:

```bash
git show c999046:docs/superpowers/plans/2026-08-16-zeitgeist-pipeline.md > .superpowers/validation/pipeline-pre-pass.md
git show --format=%B --no-patch c9fd700
```

Richer sample, noisier key: `c9fd700` bundles changes that are not
test-quality fixes — models forbidding undeclared fields, placeholder
template images — so separate those out of the key before scoring. Score it
the same way: does the audit surface the test-quality items the commit
message names?

- [ ] **Step 6: Clean up the scratch file**

```bash
rm -rf .superpowers/validation
```

- [ ] **Step 7: Run the Definition of Done**

```bash
uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Expected: all four pass.

- [ ] **Step 8: Commit**

If Step 5 changed the prompt:

```bash
git add .claude/skills/reviewing-plan-tests/reviewer-prompt.md
git commit -m "fix: strengthen the reviewer prompt to hit the validation bar"
```

If nothing changed, there is nothing to commit — record the validation
result in the task report instead. A passing replay that required no edits
is the best outcome, not a missing deliverable.
