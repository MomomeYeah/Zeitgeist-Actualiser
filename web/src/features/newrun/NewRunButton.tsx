import { Link } from "react-router-dom";

import styles from "./NewRunButton.module.css";

/**
 * The accent pill on the Topics and Runs headers, and — given `from` — the
 * ghost **Re-run config** pill on a finished run's header.
 *
 * `from` carries a run id into the New run screen, which reads that run's
 * frozen `RunConfig` and prefills every card from it, rather than a second
 * screen existing to do the same job with different defaults. The label and
 * the weight change with it, per the handoff: on a run's header this sits
 * beside the accent **Resume**, and two accent pills both reading as "start
 * something" left no way to tell a fresh run from this run's config again.
 */
export function NewRunButton({ from }: { from?: string } = {}) {
  if (from === undefined) {
    return (
      <Link to="/runs/new" className={styles.button}>
        New run
      </Link>
    );
  }
  return (
    <Link to={`/runs/new?from=${encodeURIComponent(from)}`} className={styles.ghost}>
      Re-run config
    </Link>
  );
}
