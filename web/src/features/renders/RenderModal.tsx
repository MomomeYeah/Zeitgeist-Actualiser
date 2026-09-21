import type { RenderRecord } from "@/api/types";
import { Modal } from "@/components/Modal";
import type { RenderNav } from "@/features/renders/RenderDetail";
import { RenderDetail } from "@/features/renders/RenderDetail";
import { templateLabel } from "@/features/renders/render";

import styles from "./RenderModal.module.css";

/**
 * A render, opened over the topic it came from, with the topic's other
 * renders a keystroke away.
 *
 * Everything about being a modal — Escape, the focus trap, focus restore,
 * the backdrop, and now the arrow keys — belongs to `Modal`. What is added
 * here is the close button, which `Modal` leaves to its caller, and the
 * wiring between `Modal`'s keystrokes and the frame's chevrons. This is the
 * only place those two halves meet.
 *
 * There is no `onDeleted` prop. `RenderGrid`'s cursor works out what to
 * show from its own `renders`: a delete advances this modal to the render
 * that took the deleted one's place, and empties it only when the last row
 * goes. Deriving that from the list rather than from a callback is what
 * makes a row leaving for some other reason — a tile's own ✕ behind the
 * scrim, another tab, a refetch — behave the same way. `RenderDetail` still
 * requires the prop, so a no-op is passed through; it is the standalone
 * page's own `onDeleted` that navigates.
 *
 * The address bar does not change while this is open, and paging does not
 * change it either. The permanent route is still there and `Copy link`
 * hands it out, but browsing a grid of memes should not write a history
 * entry per glance.
 */
export function RenderModal({
  record,
  onClose,
  nav,
}: {
  record: RenderRecord;
  /** Escape, the backdrop, or the close button. */
  onClose: () => void;
  /** Prev/next, when the topic has more than one render. */
  nav?: RenderNav;
}) {
  return (
    <Modal
      label={templateLabel(record)}
      onClose={onClose}
      onArrowKey={
        nav === undefined
          ? undefined
          : (step) => {
              // The ends are checked here as well as on the chevrons'
              // `disabled`: a keystroke that stepped where the button
              // refuses to would wrap the list by the back door.
              if (step === -1) {
                if (nav.hasPrev) nav.onPrev();
              } else if (nav.hasNext) {
                nav.onNext();
              }
            }
      }
    >
      <button
        type="button"
        className={styles.close}
        aria-label="Close"
        onClick={onClose}
      >
        ✕
      </button>
      {/* Keyed by the render, so paging resets everything the body holds
          about the one it was showing: a failed image, the delete mutation,
          its error line, and whether a delete is armed. An armed confirm
          carried onto the next render would point at something the user
          never chose. */}
      <RenderDetail
        key={record.id}
        record={record}
        nav={nav}
        onDeleted={() => undefined}
      />
    </Modal>
  );
}
