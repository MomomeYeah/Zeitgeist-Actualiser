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

## Known Limitation: Change Detectors

Held-out replay against a plan whose defects were already known found this
gate to be a strong independent defect-finder and an unreliable detector of
one specific category: **change detectors** — tests only an intentional
decision could break. Across repeated cold runs it surfaced every other
category of known defect at least once and this one never.

So read the reviewer's report as incomplete on that axis. After applying the
findings, walk the plan's tests yourself asking the one question the gate
reliably skips: *if this test failed, would that mean a bug, or only that
someone changed their mind?* A test that asserts a formatting choice, a
joined string, a default the code is free to change, or a value the plan
itself decides, is a candidate. The remedy is usually deletion.

The blind spot is durable rather than incidental. It survived two measured
prompt fixes, each of which closed a separately verified defect. A third fix
targets it directly but has not been measured, so assume it is still there.

## Applying the Findings

The reviewer reports; you apply. Each finding carries a remedy in one of
three forms — rewrite a test, delete one, or add one that should exist. For
each, either apply the remedy or record why you are not: a finding you
disagree with is a decision worth writing down, not one to leave silent.

Then re-run the type-consistency check from `writing-plans`' self-review.
Rewriting a test can change a signature that a neighbouring task's
`Interfaces: Consumes` block depends on, and nothing downstream would catch
it. Check the names and types every amended test touches against the tasks
that consume them.

Commit the revisions separately from the plan itself, and list the findings
you applied in the commit message. That keeps the audit's effect legible in
history, and it leaves behind an answer key for anyone later measuring
whether this gate is working.
