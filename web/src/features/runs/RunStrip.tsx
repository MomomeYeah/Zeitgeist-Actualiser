import { Link } from "react-router-dom";

import type { RunSummary } from "@/api/types";
import { formatRelative, shortRunId } from "@/format";

import styles from "./RunStrip.module.css";

/**
 * Three rows, per the handoff. The running one takes the accent border and
 * wash, which is the only difference between the rows.
 *
 * `state` is the run's own status rather than a rephrasing of it: `ok`,
 * `failed`, `aborted`, `interrupted`, `running` are the words the rest of
 * the app uses for these, and inventing friendlier ones here would mean two
 * vocabularies for one set of states.
 */
export function RunStrip({
  runs,
  activeRunId,
}: {
  runs: RunSummary[];
  activeRunId: string | null;
}) {
  return (
    <ul className={styles.strip} data-testid="run-strip">
      {runs.map((summary) => {
        const running = summary.run.run_id === activeRunId;
        return (
          <li key={summary.run.run_id}>
            <Link
              to={`/runs/${encodeURIComponent(summary.run.run_id)}`}
              className={[styles.row, running ? styles.running : ""]
                .filter(Boolean)
                .join(" ")}
            >
              <span
                className={[styles.dot, running ? styles.dotRunning : ""]
                  .filter(Boolean)
                  .join(" ")}
              />
              <span className={styles.runId}>{shortRunId(summary.run.run_id)}</span>
              <span className={styles.state}>
                {running ? "running" : summary.run.status}
              </span>
              <span className={styles.when}>
                {formatRelative(summary.run.finished_at ?? summary.run.started_at)}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
