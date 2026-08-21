# Plan Test-Quality Audit Design

## Problem

Tests authored during the implementation-plan stage are consistently weaker
than they should be. Re-reading them against `writing-good-tests.md` from
the superpowers TDD skill improves them substantially — which means the
rubric works, but is not being applied when the tests are written.

## Diagnosis

Test code is born in the plan, not during implementation. This repo's plans
carry 176 `def test_` bodies:

| Plan | Test bodies |
|------|-------------|
| `2026-08-16-zeitgeist-pipeline.md` | 138 |
| `2026-08-18-pluggable-sources.md` | 38 |
| `2026-08-20-type-checking-gate.md` | 0 |

Execution transcribes those bodies. A weak test in the plan becomes a weak
test in the suite.

The leak is systematic, not incidental. Both plans containing test code
needed a post-hoc pass against the rubric, each recorded as its own commit —
`c9fd700` for the pipeline plan, `0d4d4cd` for pluggable-sources. The third
plan contains no test code and needed no such pass.

`writing-good-tests.md` has exactly one inbound reference in the whole
superpowers plugin: `skills/test-driven-development/SKILL.md:206`. Nothing
else points at it. So the rubric is reachable only through the TDD skill,
whose trigger is "before writing implementation code" — one phase after the
tests are actually written.

Nothing in the surrounding pipeline compensates:

- **`writing-plans`** authors the test code and says "assume they don't know
  good test design very well" — guidance about the plan's *reader*, with no
  rubric handed to its *writer*. It never mentions `writing-good-tests.md`.
- **The implementer subagent** receives the tests pre-written. Its prompt
  says only "Write tests (following TDD if task says to)", naming no skill.
  Subagents are additionally told to ignore skill discovery
  (`<SUBAGENT-STOP>` in `using-superpowers`).
- **The task reviewer's** entire test rubric is one line: "Do the new and
  changed tests verify real behavior, not mocks?" That is Principle 2 alone
  — nothing on falsifiability, mirror assertions, change detectors, or the
  mutation check.

## Decision

Add a detection gate rather than a prevention nudge.

The evidence is that a re-check *fixes* the tests. That is a detection
result. Prevention would ask the planner to hold a 198-line rubric in mind
while composing several thousand lines of plan; detection gives a fresh
reader one job. A second instruction to "keep the rubric in mind" would
duplicate `SKILL.md:206`, which already says exactly that and is already
being skipped.

Scope is this repository only. The fix lives in `CLAUDE.md` and
`.claude/skills/`, both tracked in git (`.gitignore` excludes only
`.claude/worktrees/`).

## Design

Two files: a new project skill, and a short section in `CLAUDE.md` that
makes running it mandatory.

### Component 1: `.claude/skills/reviewing-plan-tests/SKILL.md`

**Frontmatter**

```yaml
---
name: reviewing-plan-tests
description: Use when an implementation plan containing test code has been
  drafted and before it is handed off for execution - audits every test in
  the plan for falsifiability and real-dependency discipline
---
```

**When it runs.** After `writing-plans` completes its own self-review,
before the execution handoff. Skipped only when the plan contains no test
code.

**How it runs.** The skill dispatches a subagent; the planner does not audit
its own tests. A reader who wrote the tests is biased toward them the same
way a test written after the code is biased by the code. Fresh context
reproduces the condition that makes the manual re-check effective.

Plans of 15 tasks or fewer get one reviewer. Larger plans are split into
contiguous ranges of at most 15 tasks, one reviewer each, dispatched in
parallel — a 4,796-line plan is too much for one reader to hold.

**Rubric, layer 1 — upstream.** The reviewer reads
`~/.claude/plugins/cache/*/superpowers/*/skills/test-driven-development/writing-good-tests.md`.
The wildcards matter: the installed path is version-pinned
(`.../superpowers/6.2.0/...`), so a literal path breaks on the next plugin
update. If the glob does not resolve, the reviewer invokes
`Skill(superpowers:test-driven-development)` and follows the link in its
body.

**Rubric, layer 2 — project conventions.** Derived from what the existing
suite demonstrates, so the skill carries knowledge upstream cannot, but
stated as durable rules rather than as citations to particular tests:

- *Hermetic by construction.* `tests/conftest.py` strips the environment
  variables the settings object reads, via an autouse fixture, so a result
  never depends on who runs the suite. A test whose outcome depends on the
  ambient environment, the wall clock, or test ordering is a defect, not a
  flake. Fixtures carrying timestamps use fixed dates.
- *Fixtures mirror the real payload completely.* A fixture standing in for an
  external API response reproduces the real structure in full, including
  fields the code under test ignores today. Trimming it lets a later change
  reference a field that was never in the test data — the test passes while
  the real payload breaks.
- *Mocks are rare and must justify themselves.* The suite tests against real
  objects and hand-built fakes almost everywhere; the few patches that exist
  inject faults that cannot be produced any other way. A new mock must name
  the real behaviour it replaces and why the real thing will not do. The
  current baseline is measured, not quoted: `grep -rl "patch(" tests/`.
- *Table-driven with literal expectations.* `@pytest.mark.parametrize` with
  hand-derived `want` values. An expectation computed by the code under test
  passes no matter what that code does.
- *Tests are type-checked.* The type checker covers `tests/` as part of the
  Definition of Done, so test code in a plan must satisfy it — PEP 695
  generics, not `typing.TypeVar`.

**Durable references only.** Neither `SKILL.md` nor `reviewer-prompt.md`
cites an individual test, a line number, a test count, or a commit hash.
Such references rot silently — nothing checks them, so a citation that has
drifted onto the wrong line misleads the reviewer rather than failing
loudly — and they tie the documents to this repository for no gain. Where a
number would carry real weight, the documents give the command that
recomputes it instead: a count goes stale, the command that produces it does
not. Stable paths (`tests/conftest.py`), architectural facts, and toolchain
facts are durable and may be named.

This dated spec is the exception, and deliberately so: it is a historical
record of the evidence at design time, not a living instruction. Specific
counts and commit hashes belong here and nowhere else.

**Output contract.** Findings only. The reviewer does not edit the plan. For
each finding: plan location (task, step, line), the test's name, the rubric
rule violated, why it fails that rule, and complete replacement test code.
The reviewer reports the number of tests audited alongside the number of
findings, and reporting zero findings is a valid result.

The reviewer applies both gate functions from the upstream rubric to every
test — name the production change that would make it fail; confirm the
expected value is derived without the code under test — and runs the closing
mutation check per task.

**Applying findings.** The planner applies them, then re-runs the
type-consistency check from `writing-plans`' self-review. Rewriting a test
can change a signature that a neighbouring task's `Interfaces: Consumes`
block depends on.

**Why findings rather than direct edits.** The planner is the single writer
of the plan and the only party holding cross-task interface context. A
reviewer rewriting tests across dozens of tasks can silently break the
`Consumes`/`Produces` contracts that `writing-plans` relies on, and no
subsequent step would catch it.

### Component 2: `CLAUDE.md`

A new `## Test quality` section immediately after `## Definition of Done`,
positioned as its sibling:

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

The wording states why the gate exists, names its trigger, names the skill,
and distinguishes it from the machine-checked gate so neither is mistaken
for the other.

## Out of Scope

- **No execution-time gate.** Tests are born in the plan; fixing them there
  makes the transcription correct. The task reviewer's one-line test rubric
  is a real weakness, but a separate one. Address it only if execution-stage
  drift proves to be its own leak.
- **No hook.** The `Definition of Done` Stop hook works because `ruff`, `ty`,
  and `pytest` actually decide. Test quality is not machine-checkable, so a
  hook could only nag — and it would fire on every plan edit.
- **No copy of the upstream rubric into the repo.** A pointer plus the
  project layer avoids maintaining a fork of someone else's document.

## Risks

**The skill does not fire.** It is instructional, so it can be rationalized
past at the end of a long planning session. Mitigated by the `CLAUDE.md`
line, which is always in context and formally outranks skills. Not
eliminated — accepted, because the only stronger mechanism cannot verify
what it demands.

**The upstream rubric is renamed or moved.** It has been renamed once
already: `testing-anti-patterns.md` became `writing-good-tests.md`.
Mitigated by the `Skill(superpowers:test-driven-development)` fallback.

Validation showed this risk was originally mitigated the wrong way. The
assumption was that an unreachable rubric would degrade gracefully, with the
project layer carrying the audit alone. What actually happened is that the
rubric was unreachable from the first run — the prompt gave a glob no tool can
read — and the reviewer reported success at a path that does not exist rather
than reporting the failure the prompt asked for. Graceful degradation was the
defect: it produced an invalid audit wearing the appearance of a complete one.
The prompt now requires a proof-of-read that can be checked from outside, and
hard-stops with `RUBRIC_UNAVAILABLE` instead of falling back to the project
layer. A missing rubric is now loud and fatal, which is the correct behaviour
for a gate.

**The gate under-detects change detectors.** Measured, not hypothetical: zero
hits across six opportunities in three cold runs, on three prompt versions.
Two candidate causes were fixed and made no difference; a third fix is applied
but untested. Mitigated only by disclosure — `SKILL.md` carries a
known-limitation note directing the caller to check that category by hand.
Accepted, because the gate's value does not rest on this category and the
alternative is not shipping a working defect-finder.

**The project layer drifts from the suite.** Mitigated by construction: the
conventions name no individual test, line number, or count, so ordinary edits
to the suite cannot invalidate them. What remains is a slower drift — a
convention could outlive the practice it describes, as the hermeticity rule
would if `conftest.py` stopped stripping the environment. That is why Task 1
verifies the conftest behaviour rather than the prose, and the residual risk
is accepted: a convention that has become merely aspirational still points in
the right direction, where a stale line number points at the wrong line.

## Validation

`writing-good-tests.md` holds that documents instructing agents are tested by
the consuming agent's behaviour, never by grepping their text. So this change
was validated behaviourally, as a held-out replay: git history supplies a
ready-made answer key, and the plan it was applied to can be recovered from
before the pass.

The manual re-check that motivated this work is isolated in a single commit,
`0d4d4cd docs: revise plan tests against writing-good-tests`, whose message
itemises six findings on the pluggable-sources plan. The plan as originally
authored is its parent, `5ed6747`. The plan at `HEAD` must not be used: those
fixes are already applied there, so an audit would correctly find little.

**This section records what the replay actually showed, including the ways it
went wrong.** The gate shipped; it did not pass the bar it was given.

### Results

Three valid cold runs, each a fresh reviewer over the same pre-pass plan, on
three successive versions of the prompt.

| Key item | Runs surfaced |
|---|---|
| 1. Fixture dated the same day as the run | *retired — see below* |
| 2. Incomplete Lemmy payload fixture | 2 of 3 |
| 3. Runaway-paging hang → named failure | 2 of 3 |
| 4. Private attributes vs. request URLs | 3 of 3 |
| 5. Change detector | **0 of 3** |
| 6. Second change detector | **0 of 3** |

Out-of-key genuine findings: 10, 8, 7. **Zero false positives in all three
runs.** Every run surfaced at least one defect materially worse than anything
in the key.

The bar — item 2, plus at least two of 3/4/5/6 — was met by one run of the
three. It is not met reliably, and the reasons matter more than the score.

### Four things the replay revealed

**The first attempt was void through contamination.** The reviewer was
dispatched into the working checkout, which held the finished post-fix suite,
the skill under test, and the answer-key commit. It reported 5 of 6. The
result was caught by checking whether the reviewer's replacement code was
*too* good: it reproduced a magic constant and an exact error string from the
shipped suite, and cited a test introduced by a commit later than the key.
That is retrieval, not review. The plan's dispatch step had constrained what
the reviewer was told and not the checkout it could read; it now requires a
detached worktree at the pre-pass commit, verified before dispatch, and
preservation of the reviewer's verbatim output as a durable artifact.

**The upstream rubric layer was silently not loading.** The prompt handed the
reviewer a glob with a leading `~`. Neither is a readable path, and the
prompt gave no procedure for expanding one. Rather than reporting the failure
the prompt explicitly asked for, the reviewer confabulated success at a
plausible-looking path that does not exist on this machine, and audited
against the project conventions alone while presenting a completed audit. The
failure was silent *and* self-concealing. It is now guarded two ways: a
mandatory proof-of-read — the reviewer must open its output with the absolute
path it read and a verbatim quote of the rubric's two core principles, both
checkable from outside — and a hard `RUBRIC_UNAVAILABLE` stop that forbids
degrading to a partial audit. Both have held across every subsequent run.

**Key item 1 expired mid-validation.** It records a Lemmy fixture stamped
`2026-08-18` in a plan authored `2026-08-18` — same-day, so a
`fetched_at > created_at` assertion compared a fixture timestamp against a
wall clock only hours ahead of it. By `2026-08-21` that date sits safely in
the past and the assertion holds on its own. A reviewer inspecting the
artifact today sees no defect and is right not to.

The irony is worth recording rather than tidying away: the key item
documenting the time-dependence rule decayed by time-dependence. An answer key
assembled from clock-sensitive defects has a shelf life that nothing
announces — the item stops being findable while continuing to look like a
legitimate miss. Any future key built from this history should exclude
clock-sensitive items, or pin evaluation to the authoring date rather than the
run date.

**Run-to-run variance is wide enough to flip the bar.** Items 2 and 3 each
flipped between runs whose prompts differed only in ways unrelated to them.
This invalidates single-run A/B comparison of prompt versions, and it
retroactively invalidates a conclusion drawn during this very validation: the
rubric-loading fix was credited with gaining item 3, on the strength of one
run before and one run after. That attribution does not survive the variance
finding. The loading fix is justified because the reviewer provably could not
read the rubric and now provably can — not because a score moved.

Items 5 and 6 are the exception that the variance finding makes legible. Zero
hits across six opportunities and three prompt versions is not noise. The
change-detector blind spot is systematic.

### The change-detector blind spot

Three hypotheses were formed and two were disproven by direct evidence:

1. *The rubric never loaded, so the category was never in scope.* Disproven:
   after the loading fix the reviewer provably read the file, and the category
   stayed empty.
2. *The output contract had nowhere to put the finding* — every finding
   required replacement test code, and a change detector's remedy is deletion.
   Disproven: an explicit `Delete` remedy form was added, defined, and
   pre-emptively defended against being read as a cop-out. It was used zero
   times out of nine findings in the following run.
3. *The Calibration paragraph licenses the skip.* It exempted "a test that is
   correct because it is small and direct" — which describes a change detector
   exactly. This one is **untested**. It was applied because the text is wrong
   on its face, not because a measurement moved, and it must not be described
   as validated.

The prompt's gate function does ask the change-detector question, and the
reviewer provably reads the rubric section naming the category. It is asked,
it has the rule, it has somewhere to put the answer, and it produces nothing.
`SKILL.md` therefore carries a known-limitation note telling the caller to
walk the plan's tests for this category by hand.

### Conclusion

**The gate does not reproduce the manual pass, and must not be described as
doing so.** The original framing of this section — that matching the key would
show the gate reproducing a pass which today happens only when asked for by
hand — was the goal, and it was not achieved.

What the gate demonstrably is: a reliable independent defect-finder with a
reproducible blind spot. Seven to ten genuine findings per run, zero false
positives across three runs, and it repeatedly caught things the human pass
never itemised — a plan test that could not pass against the plan's own
implementation, and a contradiction between one task's error handling and the
plan's own Global Constraints. Neither is in the key. Both would have cost an
executor real time.

It earns its place on those grounds rather than on recall against the key. The
Definition of Done's machine checks cannot find either of those defects,
because the code does not exist yet when the plan is written.

### Methodology defects, recorded so the next validation does not repeat them

**The revision loop was invalid.** The plan prescribed diagnose → revise →
re-run, capped at three attempts, over a single cold run per attempt. That
loop attributes score movement to the revision. With run-to-run variance wide
enough to flip the pass criterion, an n=1 measurement cannot support the
attribution, and two rounds of it produced a conclusion that had to be
withdrawn. **A future validation of this kind must measure variance first** —
repeat one configuration several times over the same input — and only then
attribute any change to a fix. Cheaper than a speculative revision, and it is
the difference between a result and a coin flip.

**The key is weaker than it looks.** It is one prior agent's pass, not
exhaustive truth, and three specific weaknesses showed up in use. It
undercounts: the same commit silently fixed a defect it never itemised, so a
reviewer finding that defect scores no credit for it. It expires: one of six
items decayed out of existence during the validation itself. And it is small
— five live items against runs producing seven to ten genuine findings, so
most of what the gate does is unscoreable by construction.

**Second corpus, unused.** `c9fd700 Rework plan tests for value` is the
equivalent pass over the 138-test pipeline plan, replayable from `c999046`.
Richer sample, noisier key: it bundles changes that are not test-quality fixes
— models forbidding undeclared fields, placeholder template images — so those
need separating out before scoring. It remains the better corpus for anyone
measuring this gate again, and it should be paired with repeated runs rather
than a single pass.
