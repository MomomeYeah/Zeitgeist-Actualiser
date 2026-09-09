import { Link } from "react-router-dom";

import type { RunSummary } from "@/api/types";
import { MemeTile } from "@/components/MemeTile";
import { StatusPill } from "@/components/StatusPill";
import { formatDuration, formatRelative, shortRunId } from "@/format";
import { resumeStageFor, survivedFor } from "@/features/runs/survived";

import styles from "./RunRow.module.css";

/** Three, then a dashed `+n` tile. Column four is 128px wide. */
const MAX_THUMBNAILS = 3;

export function RunRow({ summary }: { summary: RunSummary }) {
  const { run, topic_labels, render_ids } = summary;
  const failed = run.error !== null;
  const shown = render_ids.slice(0, MAX_THUMBNAILS);
  const overflow = render_ids.length - shown.length;
  const resumeStage = run.error ? resumeStageFor(run.error) : null;

  return (
    <Link
      to={`/runs/${encodeURIComponent(run.run_id)}`}
      className={`${styles.row} ${failed ? styles.failed : ""}`}
    >
      <span className={styles.identity}>
        <span className={styles.runId}>{shortRunId(run.run_id)}</span>
        <span className={styles.when}>
          {formatRelative(run.started_at)} · {formatDuration(run.started_at, run.finished_at)}
        </span>
      </span>

      {run.error ? (
        <span className={styles.error}>
          {run.error.kind} in {run.error.stage} — {run.error.message}
        </span>
      ) : (
        <span className={styles.labels}>{topic_labels.join(" · ")}</span>
      )}

      {run.error ? (
        <span className={styles.survived}>{survivedFor(run.error.stage)}</span>
      ) : (
        <span className={styles.counts}>
          <span>
            {run.trends_found ?? 0} trends → {run.topics_kept ?? 0} kept
          </span>
          <span className={styles.phrases}>{run.phrases_found ?? 0} phrases</span>
        </span>
      )}

      {run.error ? (
        <span className={styles.action}>
          {resumeStage === null ? "re-run ↗" : `resume from ${resumeStage} ↗`}
        </span>
      ) : (
        <span className={styles.thumbnails}>
          {shown.map((id) => (
            <MemeTile key={id} renderId={id} size={34} />
          ))}
          {overflow > 0 && <span className={styles.overflow}>+{overflow}</span>}
        </span>
      )}

      <span className={styles.status}>
        <StatusPill status={run.status} count={render_ids.length} />
      </span>
    </Link>
  );
}
