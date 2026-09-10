import styles from "./StageBar.module.css";

/**
 * The 3-4px bar across a stage card and the four-segment run progress bar.
 *
 * A partial fill is a hard-edged gradient rather than a nested element,
 * because that is what the handoff specifies:
 * `linear-gradient(90deg, accent 68%, rgba(255,255,255,.12) 68%)`.
 *
 * `fill` is 0-1 and is clamped. Phase 6 drives it from stage-relative
 * counters (`17 / 25`), and a stage that overshoots its own estimate must
 * not paint outside the card.
 */
export function StageBar({
  fill,
  tone = "accent",
}: {
  fill: number;
  tone?: "accent" | "muted";
}) {
  const percent = Math.round(Math.min(1, Math.max(0, fill)) * 100);
  return (
    <div
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      className={`${styles.bar} ${tone === "muted" ? styles.muted : styles.accent}`}
      style={{ "--fill": `${percent}%` }}
    />
  );
}
