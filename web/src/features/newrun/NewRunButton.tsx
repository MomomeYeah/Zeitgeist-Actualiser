import { Link } from "react-router-dom";

import styles from "./NewRunButton.module.css";

/**
 * The accent pill on the Topics and Runs headers.
 *
 * `from` carries a run id into the New run screen, which is how "Re-run
 * config" reaches it: the screen reads that run's frozen `RunConfig` and
 * prefills every card from it, rather than a second screen existing to do
 * the same job with different defaults.
 */
export function NewRunButton({ from }: { from?: string } = {}) {
  const to = from === undefined ? "/runs/new" : `/runs/new?from=${encodeURIComponent(from)}`;
  return (
    <Link to={to} className={styles.button}>
      New run
    </Link>
  );
}
