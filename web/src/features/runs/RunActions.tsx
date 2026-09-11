import type { RunDetail } from "@/api/types";
import { useAbortRun, useResumeRun, useStopRun } from "@/api/queries";
import { InlineConfirm } from "@/components/InlineConfirm";
import { NewRunButton } from "@/features/newrun/NewRunButton";

import styles from "./RunActions.module.css";

/**
 * The header's button pair, in both of the run's lives.
 *
 * Live: **Stop after this stage** and **Abort**. Stop carries no confirm —
 * it lets the current stage write its checkpoint and leaves the run
 * resumable, so it destroys nothing. Abort does, and asks. Once either
 * succeeds (a 202 — accepted, not finished: the current stage can still
 * take minutes), the buttons acknowledge it rather than sitting there
 * unchanged: Stop disables and reads "Stopping…", Abort's confirm is
 * replaced by a disabled "Aborting…", and Abort succeeding disables Stop
 * too. Stop succeeding leaves Abort available, because a user who asked
 * for a clean stop can still escalate.
 *
 * Over: **Re-run config**, which is `NewRunButton` carrying this run's id
 * so the New run screen prefills from its frozen `RunConfig`; and
 * **Resume from &lt;stage&gt;**, whose stage name is computed by the server
 * and is therefore absent — not disabled — when there is nothing to resume
 * from. A disabled control still says the action exists. Resume carries the
 * same swap-in-place confirm as Abort (`tone="accent"` keeps its resting
 * look the design's accent pill rather than Abort's contrast one): the
 * header's buttons swap in place the instant a run ends, and a click aimed
 * at Abort as that happens can land on Resume instead. Re-run config stays
 * a plain link with no confirm — it opens a form and acts on nothing.
 *
 * `RunDetailPage` keys this component on `live`, remounting it on every
 * live↔over transition. That is what makes the pending-state guards above
 * safe: a resumed run goes live again on the *same* page, and without the
 * remount a stale `stop.isSuccess` from the previous life would still read
 * "Stopping…" under buttons that now belong to a run going a second time.
 *
 * A refused action is reported where it happened. All three mutations can
 * come back 409 (a double click, a second tab, a run that ended between the
 * render and the click), and the sentence the server sends is the only
 * thing that distinguishes them. The remount above is also why the three
 * errors can be merged into one line rather than picked apart by `live`:
 * within a single mount, only the branch matching that mount's own `live`
 * ever has a button to click, so at most one of `stop`, `abort` and
 * `resume` can ever hold an error at a time. The mount boundary already
 * scopes it; a second check here would be redundant.
 */
export function RunActions({ detail, live }: { detail: RunDetail; live: boolean }) {
  const runId = detail.run.run_id;
  const stop = useStopRun(runId);
  const abort = useAbortRun(runId);
  const resume = useResumeRun(runId);

  const failure = stop.error ?? abort.error ?? resume.error ?? null;

  return (
    <div className={styles.actions}>
      {live ? (
        <>
          <button
            type="button"
            className={styles.ghost}
            disabled={stop.isPending || stop.isSuccess || abort.isSuccess}
            onClick={() => stop.mutate()}
          >
            {stop.isSuccess ? "Stopping…" : "Stop after this stage"}
          </button>
          {abort.isSuccess ? (
            <button type="button" className={styles.ghost} disabled>
              Aborting…
            </button>
          ) : (
            <InlineConfirm
              label="Abort"
              question="Abort run?"
              onConfirm={() => abort.mutate()}
            />
          )}
        </>
      ) : (
        <>
          <NewRunButton from={runId} />
          {detail.resume_stage !== null && (
            <InlineConfirm
              label={`Resume from ${detail.resume_stage}`}
              question={`Resume from ${detail.resume_stage}?`}
              tone="accent"
              // An empty body: the stage is the server's own computation
              // (`resume_stage`), and echoing it back could send a stale
              // one if the run gained a checkpoint since this render.
              onConfirm={() => resume.mutate({})}
            />
          )}
        </>
      )}
      {failure !== null && <p className={styles.failure}>{failure.detail}</p>}
    </div>
  );
}
