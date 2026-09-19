# Run deletion

There is no way to remove a run. Failed runs, tuning passes and runs that
were only ever a smoke test accumulate in the Runs list and the topics
index, and the only remedy today is deleting `data/zeitgeist.db` — every
run at once. This design adds deletion of one run, from its detail screen:
the row, everything that hangs off it, and its output directory.

## Scope

In:

- `DELETE /api/runs/{run_id}`, removing the run's database rows and its
  `output/<run_id>/` directory.
- Refusing that deletion while anything is still writing to the run.
- A **Delete** action in the run detail header, confirming in place with
  the number of memes that go with it.
- `render_count` on `RunDetail`, which that confirm needs.

Out:

- Deletion from the Runs list. Every row there is a single `<Link>`
  (`RunRow`); a button inside it would be interactive content nested in an
  anchor, which is invalid and breaks keyboard and screen-reader use. The
  detail screen is also where the user can see what they are about to
  delete, which matters for something that costs minutes and real model
  calls to reproduce.
- Bulk deletion ("clear all failed runs"). Nothing asks for it yet.
- Undo, soft deletion, or a trash. The project's stance on data is that it
  is disposable (see the web UI spec's "Migrations"); one confirm is the
  guard, as it is for renders.
- Deleting a live or queued run in one step. Abort it first; the button is
  not offered until it is over.

## What a run is made of

Every table except `settings` references `run_records (run_id)` with
`ON DELETE CASCADE`, and `Store.__init__` turns foreign-key enforcement on.
Deleting the one `run_records` row therefore removes the run's checkpoints,
stage rows, ranked topics, renders, log lines and per-platform scores in
the same statement. Nothing needs a hand-written cascade.

The per-platform scores are `topic_scores`, which `Store.previous_sub_scores`
reads to score the next run's momentum. Deleting the most recent run
therefore changes what the next run scores against, not just what this run's
own history shows.

On disk a run is `output/<run_id>/`, which holds only `renders/` — each
render's full PNG and thumbnail, laid out by
`zeitgeist.renders.render_paths`. Removing the whole directory rather than
iterating renders also reclaims the orphaned PNGs that `delete_render` and
`_draw` knowingly leave behind.

Hand-written renders get no special treatment. They are the one part of a
run a re-run cannot reproduce, which is why `clear_auto_renders` spares
them, but deleting a run is a deliberate act on the whole run. The confirm
states how many memes go with it instead.

## Backend

### `Store.delete_run(run_id) -> bool`

`DELETE FROM run_records WHERE run_id = ?`, committed. Returns whether a row
was removed. It knows rows and nothing about the filesystem, like
`Store.delete_render`.

### `delete_run_files(output_dir, run_id)`

In `zeitgeist/renders.py` beside `delete_render`, since that module already
owns the output layout and knows nothing about HTTP. Removes
`output_dir / run_id` recursively.

- **Containment.** The run id arrives in a URL. Before removing anything,
  the resolved target must be a direct child of the resolved `output_dir`;
  otherwise it raises `ValueError` and removes nothing. The endpoint only
  reaches this after finding a `run_records` row for the id, so an escaping
  id should never get here — this is the check that makes that a guarantee
  rather than an inference.
- **A missing directory is not an error.** A run that died in ingest never
  created one.
- **A failure to remove is logged, not raised.** Order is row first, files
  second, for the reason `delete_render` gives: a crash between the two
  leaves an unreferenced directory, which is invisible, whereas the other
  order leaves a run whose screens draw broken tiles. The database is
  authoritative for whether a run exists, so once the row is gone the
  request has succeeded; a locked file on Windows is a warning in the log,
  not a 500 for a deletion that already happened.

### `DELETE /api/runs/{run_id}`

In `zeitgeist/api/runs.py`. Answers:

| Status | When |
|---|---|
| 204 | Deleted. No body. |
| 404 | No such run. |
| 409 | The run is live or queued, or an on-demand generation job for it is in flight. `detail` is a sentence saying which. |

The handler composes the two guards below, then removes files outside both
locks:

```python
with generator.excluding(run_id):          # 409 if jobs in flight
    runner.delete(run_id)                  # 404 / 409; deletes the row
delete_run_files(settings.output_dir, run_id)
```

### Guard 1: the run worker

`RunService.delete(run_id)`, under `RunService._lock`:

1. If `_is_live(run_id)`, raise `RunAlreadyActive` → 409.
2. `store.delete_run(run_id)`; if it removed nothing, raise a new
   `UnknownRun` (`LookupError`) → 404.

Holding `_lock` is what makes this safe against a resume from a second tab:
`enqueue` opens or re-opens a run's row under the same lock, so the check
and the delete cannot interleave with it. Only the row delete happens under
the lock — one indexed `DELETE` — so `active()`, `stop()` and `abort()` wait
no longer than they already do for `enqueue`'s write. The directory removal
happens after the lock is released.

**Resume must re-check the row under the lock.** `resume_run` checks the
run exists before calling `enqueue`, and `Store.start_run` is an upsert. A
delete landing between the two would let `enqueue` insert a fresh
`run_records` row with no checkpoints behind it — a deleted run coming back
as an empty shell that then fails. So `enqueue` takes a keyword-only
`resuming: bool = False`, which `resume_run` passes as `True`; when it is
set, `enqueue` confirms `store.get_run(run_id)` is not `None` inside the
lock, and raises `UnknownRun` if it is; `resume_run` maps that to 404. A
flag rather than inferring a resume from `request.run_id` being set,
because tests (and nothing else) enqueue brand-new runs under a chosen id.

### Guard 2: on-demand generation

A finished run can still be written to by `GenerationService`: a job in
flight fills in its `generating` rows and writes PNGs under
`output/<run_id>/renders/`. Deleting the run under it would leave
`update_render` harmlessly updating nothing, but `_draw` would recreate the
run directory after `delete_run_files` removed it, and nothing would ever
reclaim it.

The stored `generating` status cannot answer "is a job running": nothing
reconciles those rows after a restart, so a run whose server died mid-job
would hold `generating` rows forever and could never be deleted. The
service's own in-memory state is the truth, so it tracks it:

- `_in_flight: dict[str, int]` — jobs per run, and `_deleting: set[str]`,
  both guarded by the existing `_lock`.
- `submit` increments `_in_flight[run_id]` after `_ensure_pool` and before
  anything else, refusing with `UnknownRun` (→ 404) if `run_id` is in
  `_deleting`. Having claimed the run, it confirms `store.get_run(run_id)`
  is not `None`, raising `UnknownRun` if it is. Every path out of `submit`
  that does not hand the job to the pool decrements it again.
- `_run` decrements in its `finally`, removing the key at zero.
- `excluding(run_id)` is a context manager: under `_lock`, raise
  `RunBusy` (→ 409) if `_in_flight.get(run_id)` is non-zero, otherwise add
  `run_id` to `_deleting`; on exit, discard it.

Claim first, then check, is what makes this airtight. Either `submit`'s
claim lands first, and `excluding` refuses the delete; or `excluding` lands
first, and the claim is refused; or the whole delete finishes first, and
the existence check refuses. Without it, a `submit` that passed the
endpoint's `_run_or_404` just before a delete would reach `_seed` after
the row was gone and hit the foreign key as an `IntegrityError` 500 — or,
earlier, `read_checkpoint` would answer `MissingCheckpoint`, a 409 claiming
the run never analysed.

### `RunDetail.render_count`

`render_count: int` on `RunDetail`, the sum of `Store.render_counts(run_id)`
— ready renders only, for the reason that method's docstring gives: a
`generating` or `failed` row is not a meme anyone can see, and the confirm
is telling the user what they will lose. A count at read time, per the
schema's standing rule against denormalised counts.

`web/openapi.json` and `web/src/api/schema.ts` are regenerated; the gate
fails if either is stale.

## Frontend

### `useDeleteRun(runId)`

In `web/src/api/queries.ts`, beside `useDeleteRender` and shaped like it:

- `apiDelete` on `/api/runs/{runId}`. A 404 resolves as success: the run
  is already gone, which is the outcome asked for.
- On success, marks every cached query under `queryKeys.run(runId)`'s
  prefix — detail, ranking, log, each topic detail — stale *without*
  refetching (`refetchType: "none"`), the way `useDeleteRender` treats the
  render it removed. Then invalidates everything else under `["runs"]`
  (the list, `active`) with a predicate excluding this run's keys, the
  topics index, and marks render records stale without a refetch.
- **The detail page must not flash "No such run." between success and
  navigation.** Its own run query is still mounted when the mutation
  succeeds; refetching it would 404 and render the missing state for a
  frame. Excluding the run's own keys from the refetch is what prevents
  it. Marking them stale doesn't stop Back from drawing the deleted run
  from cache — it still does, for one round trip — but it is what makes
  the page ask the server again on that round trip, which answers 404 and
  replaces the cached run with "No such run."

### The Delete action

In `RunActions`, the "over" branch gains a third control after *Re-run
config* and *Resume from &lt;stage&gt;*:

- An `InlineConfirm`, `label="Delete"`, default `tone="contrast"` — Abort's
  resting look, the design's destructive pill.
- `question`, from `detail.render_count`:
  - 0 → `Delete run?`
  - 1 → `Delete run and its 1 meme?`
  - n → `Delete run and its n memes?`
- `disabled` while the mutation is pending or has succeeded, the guard
  Resume carries, so a second confirm cannot draw a 404 or 409 in the
  moment before navigation.
- On success, navigate to `/runs`.
- A refusal (409) appears in the existing failure line: `failure` becomes
  `stop.error ?? abort.error ?? resume.error ?? remove.error ?? null`. The
  "one error at a time" argument in `RunActions`'s doc comment still holds,
  because Delete lives only in the "over" mount, beside Resume.

Absent, not disabled, while the run is live — the same rule as Resume. A
live run's header is Stop and Abort; after Abort the page remounts
`RunActions` into its "over" branch and Delete appears.

`RunActions`'s doc comment gains a paragraph on Delete: why it confirms,
why its question carries the count, and that it navigates away rather than
handing focus to the header, since the header is going too.

## Error handling summary

| Situation | Result |
|---|---|
| Run is live or queued | 409, "Run … is queued or executing; abort it before deleting it."; button not offered in the UI |
| Generation job in flight for the run | 409, sentence says memes are still generating; shown under the buttons |
| Deleted from another tab first | 404 → treated as success, navigate to `/runs` |
| Resume from another tab after delete | 404 from the resume, run not recreated |
| Generate from another tab during delete | 404 (`UnknownRun`), no `IntegrityError` |
| Output directory missing | 204; nothing to remove |
| Output directory cannot be removed | 204; warning logged, directory orphaned |
| Run id resolves outside `output_dir` | Unreachable via the endpoint (404 first); `delete_run_files` raises and removes nothing |

## Testing

Backend (pytest, each on its own `tmp_path` `Store`):

- `Store.delete_run` removes the run's row and its rows in every child
  table — checkpoints, stages, topics, renders, log lines, scores — leaves
  another run's rows untouched, and returns `False` for an unknown id.
- `delete_run_files` removes the run's directory and leaves a sibling run's
  directory intact; succeeds when the directory is absent; raises and
  removes nothing for an id that resolves outside `output_dir` (`..`, an
  absolute path).
- Endpoint: 204, then `GET /api/runs/{id}` is 404 and the directory is
  gone; 404 for an unknown id; 409 for a queued run (the stub executor
  holds the worker); 409 while a generation job is in flight, using
  `GenerationService(generate=...)` with a job that blocks on a
  `threading.Event`, and 204 once it is released.
- A resume issued after a delete is 404 and no `run_records` row exists
  afterwards.
- `excluding` refuses `submit` for that run while held and allows it for
  other runs.
- `GET /api/runs/{id}` carries `render_count` equal to the ready renders,
  not counting `generating` or `failed` ones.
- The OpenAPI snapshot test, which already exists, fails until
  `web/openapi.json` is regenerated.

Frontend (vitest with the MSW server):

- No Delete control while the run is live.
- The question reads correctly for 0, 1 and several memes.
- Confirming sends `DELETE /api/runs/{id}` and lands on `/runs` without
  rendering "No such run." on the way.
- A 409 shows the server's `detail` under the buttons and leaves the page
  in place.
- A 404 is treated as success and navigates.
