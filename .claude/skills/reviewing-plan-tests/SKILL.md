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
