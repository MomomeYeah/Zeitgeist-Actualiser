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
 * resumable, so it destroys nothing. Abort does, and asks.
 *
 * Over: **Re-run config**, which is `NewRunButton` carrying this run's id
 * so the New run screen prefills from its frozen `RunConfig`; and
 * **Resume from &lt;stage&gt;**, whose stage name is computed by the server
 * and is therefore absent — not disabled — when there is nothing to resume
 * from. A disabled control still says the action exists.
 *
 * A refused action is reported where it happened. All three of these can
 * come back 409 (a double click, a second tab, a run that ended between
 * the render and the click) and the sentence the server sends is the only
 * thing that distinguishes them.
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
            disabled={stop.isPending}
            onClick={() => stop.mutate()}
          >
            Stop after this stage
          </button>
          <InlineConfirm
            label="Abort"
            question="Abort run?"
            onConfirm={() => abort.mutate()}
          />
        </>
      ) : (
        <>
          <NewRunButton from={runId} />
          {detail.resume_stage !== null && (
            <button
              type="button"
              className={styles.accent}
              disabled={resume.isPending}
              // An empty body: the stage is the server's own computation
              // (`resume_stage`), and echoing it back could send a stale
              // one if the run gained a checkpoint since this render.
              onClick={() => resume.mutate({})}
            >
              Resume from {detail.resume_stage}
            </button>
          )}
        </>
      )}
      {failure !== null && <p className={styles.failure}>{failure.detail}</p>}
    </div>
  );
}
