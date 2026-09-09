import type { ReactNode } from "react";

import styles from "./EmptyState.module.css";

/**
 * The centred block for an emptiness that is the app's condition rather than
 * the user's own doing. The lighter treatment — a filter that matched
 * nothing — is a single line, not a card, and belongs to the screen that
 * owns the filter.
 *
 * `action` is optional and no phase-5 caller passes it: the only sensible
 * next step is "New run", and there is no New run screen until phase 6.
 */
export function EmptyState({
  headline,
  body,
  action,
}: {
  headline: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className={styles.block}>
      <h2 className={styles.headline}>{headline}</h2>
      <p className={styles.body}>{body}</p>
      {action !== undefined && <div className={styles.action}>{action}</div>}
    </div>
  );
}
