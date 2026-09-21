import styles from "./WorkingBar.module.css";

/**
 * A render still being made: a sweeping bar and what is being done.
 *
 * The bar sweeps rather than filling to a fraction, because nothing reports
 * how far along a brief is and a percentage would be a number invented for
 * the screen.
 *
 * Shared by the topic grid's tile and the render modal's frame, which draw
 * it at very different sizes. The caller's box decides how much room it
 * gets; this decides what it looks like, so the keyframes exist once.
 */
export function WorkingBar({ doing }: { doing: string }) {
  return (
    <span className={styles.bar}>
      <span className={styles.track} aria-hidden="true">
        <span className={styles.sweep} />
      </span>
      <span className={styles.doing}>{doing}</span>
    </span>
  );
}
