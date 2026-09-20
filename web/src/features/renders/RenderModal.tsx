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
 * button, which `Modal` leaves to its caller, and the decision about what
 * a finished delete means.
 *
 * The address bar does not change while this is open. The permanent route
 * is still there and `Copy link` hands it out, but browsing a grid of
 * memes should not write a history entry per glance.
 */
export function RenderModal({
  record,
  onClose,
  onDeleted,
}: {
  record: RenderRecord;
  /** Escape, the backdrop, or the close button. */
  onClose: () => void;
  /**
   * The row has been deleted. Separate from `onClose` because the caller
   * has more to do — the tile this modal was opened from has gone with the
   * row, so focus needs somewhere to land.
   */
  onDeleted: () => void;
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
      <RenderDetail record={record} onDeleted={onDeleted} />
    </Modal>
  );
}
