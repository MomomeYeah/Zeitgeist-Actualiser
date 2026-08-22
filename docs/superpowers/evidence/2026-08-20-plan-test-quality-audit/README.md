# Plan Test-Quality Audit — Validation Evidence

Raw reviewer output from the held-out replays that validated the
`reviewing-plan-tests` skill. The results are summarised in
`docs/superpowers/specs/2026-08-20-plan-test-quality-audit-design.md`; these
files are the evidence behind that summary.

They are kept because the summary makes claims — hit rates per key item,
out-of-key yield, zero false positives — that are otherwise unverifiable
assertions. Discarding the transcripts was itself flagged as a defect during
the validation: a result nobody can re-examine is a result nobody can
falsify. The spec's dispatch procedure now requires preserving this output,
and these files are that requirement being met.

## The experiment

Each run dispatched a fresh reviewer over the pluggable-sources plan as it
stood at `5ed6747`, before the manual test-quality pass. The answer key is
the commit message of `0d4d4cd`, that pass, which itemises what it fixed.
The reviewer was never told the key, the commit, or anything about expected
findings.

## The runs

| File | Run | Prompt version | Cold? | Score |
|------|-----|----------------|-------|-------|
| `runs-1-and-2-verbatim.md` | 1 | as first shipped | **No — void** | 5 of 6, discarded |
| `runs-1-and-2-verbatim.md` | 2 | as first shipped | Yes | 3 of 6 |
| `run-4-verbatim.md` | 4 | + proof-of-read | Yes | 3 of 6 |
| `run-5-verbatim.md` | 5 | + three-form remedy | Yes | 2 of 5 |

Run 1 is retained deliberately, not as a result but as the record of a
failure mode worth recognising again: it ran inside a checkout holding the
finished post-fix test suite, so it could retrieve answers rather than derive
them. It was caught by noticing its replacement code was *too* good — it
reproduced a magic constant and an exact error string from the shipped suite,
and cited a test introduced by a commit later than the answer key.

Run 3 is absent because it was abandoned mid-flight. It had been tuned
against the known key, which invalidates it as a measurement.

Runs 4 and 5 open with a proof-of-read block — the absolute path of the
rubric the reviewer read and a verbatim quote from it — added after Run 2
revealed the reviewer could confabulate having read a rubric it never opened.

Key item 1 was retired between Run 4 and Run 5: it described a fixture dated
the same day as the plan, and enough time has passed that the date now sits
safely in the past, so the defect is no longer detectable from the artifact.
Run 5 is therefore scored out of five.

## Reading these

Scores against the key are the weaker half of the picture. The stronger half
is the out-of-key column: 10, 8 and 7 genuine findings across the three cold
runs, with no false positives in any of them. Several are more consequential
than anything in the key — a test that cannot pass against the plan's own
implementation, and a task whose exception handler contradicts the plan's
stated global constraints.
