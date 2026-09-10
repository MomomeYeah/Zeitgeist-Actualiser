import type { ReactNode } from "react";

import styles from "./Chip.module.css";

/**
 * The four chip treatments the handoff uses.
 *
 * `inverted` is the hero card's: on an accent fill the palette inverts, so a
 * chip there is a dark fill with accent text rather than the other way
 * round.
 */
export type ChipTone = "accent" | "muted" | "contrast" | "inverted";

export function Chip({
  tone = "muted",
  children,
}: {
  tone?: ChipTone;
  children: ReactNode;
}) {
  return <span className={`${styles.chip} ${styles[tone]}`}>{children}</span>;
}
