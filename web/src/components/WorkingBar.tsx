import styles from "./WorkingBar.module.css";

/**
 * A render still being made: a sweeping bar and what is being done.
 *
 * The bar sweeps rather than filling to a fraction, because nothing reports
 * how far along a brief is and a percentage would be a number invented for
 * the screen.
 *
 * Shared by the topic grid's tile and the render modal's frame, which want
 * it at very different sizes, so both looks live here. The alternative —
 * the modal's stylesheet reaching in to resize the track and the sentence —
 * would put this component's internals in another module's rules, with the
 * cascade order between the two decided by import order. See the `composes`
 * comment in `InlineConfirm.module.css`.
 */
export function WorkingBar({
  doing,
  size = "tile",
}: {
  doing: string;
  /**
   * How much room it is drawn in. `"tile"` is the grid's 112px preview box.
   * `"panel"` is the render modal's frame, where the bar has the height of
   * the failed render's panel to fill — the same height, so paging between a
   * generating render and a failed one does not resize the frame, which is
   * the reflow the grid's outline-over-border choice was protecting against
   * in the small.
   */
  size?: "tile" | "panel";
}) {
  const panel = size === "panel";
  // Both classes, the variant second: same stylesheet, so source order
  // decides and the modifier wins. That is the whole reason it is here
  // rather than in the caller's module.
  const at = (base: string, variant: string) => (panel ? `${base} ${variant}` : base);

  return (
    <span className={at(styles.bar, styles.panelBar)}>
      <span className={at(styles.track, styles.panelTrack)} aria-hidden="true">
        <span className={styles.sweep} />
      </span>
      <span className={at(styles.doing, styles.panelDoing)}>{doing}</span>
    </span>
  );
}
