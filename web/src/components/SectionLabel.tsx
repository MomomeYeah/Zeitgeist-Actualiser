import type { ReactNode } from "react";

import styles from "./SectionLabel.module.css";

/**
 * The mono 700/9.5/.12em uppercase label above every block, with the
 * right-aligned hint several of them carry ("optional", "exactly one",
 * "2 rendered · 3 to go").
 */
export function SectionLabel({
  children,
  hint,
}: {
  children: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className={styles.row}>
      <span className={styles.label}>{children}</span>
      {hint !== undefined && <span className={styles.hint}>{hint}</span>}
    </div>
  );
}
