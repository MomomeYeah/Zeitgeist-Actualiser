import { useEffect, useState } from "react";

import type { RenderRecord } from "@/api/types";

/** Where the modal is: which render, and where that render sat. */
interface Position {
  id: string;
  index: number;
}

export interface RenderCursor {
  /** The render to show, or null when the modal is closed. */
  record: RenderRecord | null;
  /** Its 0-based place in the list, or -1 when closed. */
  index: number;
  /** How many renders there are to page through. */
  count: number;
  hasPrev: boolean;
  hasNext: boolean;
  /** Show this render. A id that is not in the list is ignored. */
  open: (id: string) => void;
  close: () => void;
  prev: () => void;
  next: () => void;
}

/**
 * Which render the modal is showing, and what happens to it when the list
 * moves underneath.
 *
 * The state is an id *and* a position, because the id alone cannot survive
 * its own row being deleted — and a delete from inside the modal should
 * carry on to the next render rather than shutting the modal. Resolution
 * each pass:
 *
 * 1. The id is still in the list → show that row, and remember where it
 *    now is.
 * 2. The id has gone → show whatever is at the same index, clamped to the
 *    end of the list.
 * 3. The clamp produced nothing → closed.
 *
 * Rule 2 is both behaviours the screen needs, from one line. Deleting row
 * *i* slides row *i+1* down into index *i*, so "the same index" is "the
 * next one"; deleting the last row leaves the index past the end, so the
 * clamp lands on the new last row, which is the one before it. An emptied
 * list clamps to -1, which is rule 3.
 *
 * The record is worked out during the render pass rather than assigned in
 * an effect. An effect would leave one pass with no record and therefore no
 * modal, and an unmounted modal hands focus back to the grid and re-traps
 * it on the way in — a visible flinch in the middle of the interaction this
 * exists to smooth. The effect below only writes the resolved position
 * back, so the next deletion resolves from where the row actually is.
 */
export function useRenderCursor(renders: RenderRecord[]): RenderCursor {
  const [position, setPosition] = useState<Position | null>(null);

  const held =
    position === null ? -1 : renders.findIndex((render) => render.id === position.id);
  const at =
    position === null
      ? -1
      : held === -1
        ? Math.min(position.index, renders.length - 1)
        : held;
  // Indexing is the bounds check: `noUncheckedIndexedAccess` makes this
  // `RenderRecord | undefined`, so a clamp that produced -1 — or any index
  // the list does not reach — arrives here as `undefined` and closes.
  const shown = at === -1 ? undefined : renders[at];
  const index = shown === undefined ? -1 : at;
  const shownId = shown?.id ?? null;

  useEffect(() => {
    if (position === null) return;
    if (shownId === null) {
      setPosition(null);
      return;
    }
    if (shownId !== position.id || index !== position.index) {
      setPosition({ id: shownId, index });
    }
  }, [position, shownId, index]);

  function step(delta: -1 | 1) {
    if (index === -1) return;
    const target = renders[index + delta];
    // Again the undefined branch is the bounds check — there is no wrapping,
    // so a step off either end does nothing.
    if (target === undefined) return;
    setPosition({ id: target.id, index: index + delta });
  }

  return {
    record: shown ?? null,
    index,
    count: renders.length,
    hasPrev: index > 0,
    hasNext: index !== -1 && index < renders.length - 1,
    open: (id: string) => {
      const found = renders.findIndex((render) => render.id === id);
      if (found !== -1) setPosition({ id, index: found });
    },
    close: () => setPosition(null),
    prev: () => step(-1),
    next: () => step(1),
  };
}
