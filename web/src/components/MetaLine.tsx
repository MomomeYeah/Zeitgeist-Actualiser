import type { ReactNode } from "react";

import styles from "./MetaLine.module.css";

/** The mono 400/10.5 line under a page title, a run id, or a card header. */
export function MetaLine({ children }: { children: ReactNode }) {
  return <p className={styles.meta}>{children}</p>;
}
