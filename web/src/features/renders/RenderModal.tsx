import type { RenderRecord } from "@/api/types";
import { Modal } from "@/components/Modal";
import { RenderDetail } from "@/features/renders/RenderDetail";
import { templateLabel } from "@/features/renders/render";

import styles from "./RenderModal.module.css";

/**
 * A render, opened over the topic it came from.
 *
 * Everything about being a modal — Escape, the focus trap, focus restore,
 * the backdrop — belongs to `Modal`. What is added here is the close
 * button, which `Modal` leaves to its caller.
 *
 * There is no `onDeleted` prop. The grid that opens this modal derives
 * which render is open from its own `renders`, so a successful delete
 * drops the row and this modal unmounts on the very next render — before
 * react-query would run a `mutate()` callback on a component that has
 * already gone. `RenderGrid` watches the row leaving instead. `RenderDetail`
 * still requires the prop, so a no-op is passed through here; it is the
 * standalone page's own `onDeleted` — not forwarded from here — that
 * navigates, because that page is still mounted when its delete resolves.
 *
 * The address bar does not change while this is open. The permanent route
 * is still there and `Copy link` hands it out, but browsing a grid of
 * memes should not write a history entry per glance.
 */
export function RenderModal({
  record,
  onClose,
}: {
  record: RenderRecord;
  /** Escape, the backdrop, or the close button. */
  onClose: () => void;
}) {
  return (
    <Modal label={templateLabel(record)} onClose={onClose}>
      <button
        type="button"
        className={styles.close}
        aria-label="Close"
        onClick={onClose}
      >
        ✕
      </button>
      <RenderDetail record={record} onDeleted={() => undefined} />
    </Modal>
  );
}
