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
Mitigated by the `Skill(superpowers:test-driven-development)` fallback, and
by the project layer being independently useful if the upstream file cannot
be found at all.

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
is validated behaviourally — and git history supplies a ready-made answer key.

The manual re-check that motivated this work is isolated in a single commit,
`0d4d4cd docs: revise plan tests against writing-good-tests`, whose message
itemises its six findings on the pluggable-sources plan:

1. A fixture dated the same day as the run, making the
   `fetched_at > created_at` assertion time-dependent
2. An incomplete Lemmy payload fixture that did not mirror the real API
3. A runaway-paging hang, converted into a named failure
4. Assertions on private attributes rather than on request URLs
5. and 6. Two change detectors

The validation is therefore a held-out replay:

1. Extract the plan as originally authored, before the manual pass:
   `git show 5ed6747:docs/superpowers/plans/2026-08-18-pluggable-sources.md`
2. Run the audit over that version, cold.
3. Score the findings against the six above.

**The plan at `HEAD` must not be used.** Those fixes are already applied
there, so an audit would correctly find little and the result would say
nothing about whether the gate works.

**Item 1 is retired; the live key is five items.** The defect it records was
that the Lemmy fixture was stamped `2026-08-18` in a plan authored on
`2026-08-18` — same-day, so `fetched_at > created_at` compared a fixture
timestamp against a wall clock only hours ahead of it. By `2026-08-21` that
date sits safely in the past and the assertion simply holds. A reviewer
inspecting the artifact today sees no defect, and is right not to. The item
cannot be scored because the thing being scored has expired.

The irony is worth recording rather than tidying away: this key item
documents the time-dependence rule, and the benchmark for it decayed by
time-dependence. An answer key assembled from defects that depend on the
clock has a shelf life, and nothing announces when it runs out — the item
simply stops being findable while still looking like a legitimate miss. Any
future key built from this repository's history should exclude
clock-sensitive items, or pin the evaluation to the authoring date rather
than the run date.

**Scoring.** Recall against the five live findings is the measure. Findings
beyond them are not failures — they are the expected upside of a fresh reader
with the rubric in hand — but they cannot be scored, because `0d4d4cd` is one
approved pass, not exhaustive truth.

**The bar.** Item 2 must be surfaced, plus at least two of items 3, 4, 5 and
6. Item 2 is the case the prompt's own project conventions name explicitly: a
reviewer that misses what its prompt spells out is not working.

**What the key is and is not.** `0d4d4cd` was itself produced by an agent
performing the re-check on request. Matching it shows the gate reproduces a
pass that today happens only when asked for by hand, which is precisely the
goal. It does not show the gate finds every real defect.

**Second corpus, if the first is inconclusive.** `c9fd700 Rework plan tests
for value` is the equivalent pass over the 138-test pipeline plan, replayable
from `c999046`. Richer sample, noisier key: it bundles changes that are not
test-quality fixes — models forbidding undeclared fields, placeholder
template images — so those need separating out before scoring.
