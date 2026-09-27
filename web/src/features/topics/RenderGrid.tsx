import type { MouseEvent } from "react";
import { useEffect, useRef } from "react";

import type { GenerationRequest, RenderRecord } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";
import { RenderModal } from "@/features/renders/RenderModal";
import { GeneratingTile, RenderTile } from "@/features/topics/RenderTile";
import { useRenderCursor } from "@/features/topics/useRenderCursor";
import { shortRunId } from "@/format";

import styles from "./RenderGrid.module.css";

/**
 * `2 from …829T090000Z · 1 generating · 1 failed`.
 *
 * "From" counts what there is to look at — ready renders — which is what
 * phase 5's hint counted. The other clauses appear only when there is
 * something to count, so a settled topic reads exactly as it did then.
 */
function hint(renders: RenderRecord[], placeholders: number, runId: string): string {
  const count = (status: RenderRecord["status"]) =>
    renders.filter((render) => render.status === status).length;
  const parts = [`${count("ready")} from ${shortRunId(runId)}`];
  const generating = count("generating") + placeholders;
  if (generating > 0) parts.push(`${generating} generating`);
  const failed = count("failed");
  if (failed > 0) parts.push(`${failed} failed`);
  return parts.join(" · ");
}

/**
 * Whether a click meant "here" rather than "somewhere else".
 *
 * ⌘, ctrl and shift on a link mean a new tab or window, and alt means
 * download; those belong to the browser, and swallowing them would make the
 * tile's href a promise it does not keep. `button` is belt and braces — a
 * middle click fires `auxclick` rather than `click` in current browsers.
 */
function opensHere(event: MouseEvent): boolean {
  return (
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey &&
    event.button === 0
  );
}

/** One placeholder per meme a request still in flight asked for. */
function placeholdersFor(request: GenerationRequest): { label: string; doing: string }[] {
  if (request.mode === "manual") {
    return [{ label: `${request.template_id} · manual`, doing: "rendering…" }];
  }
  return Array.from({ length: request.count }, () => ({
    label: `${request.template_id ?? "choosing…"} · auto`,
    doing: "writing brief…",
  }));
}

/**
 * "Rendered from this topic": every row the topic has, in whatever state
 * it is in, then a placeholder for each meme a request in flight asked for.
 *
 * The placeholders are the handoff's "both buttons immediately append
 * placeholder tiles". They are drawn from the requests themselves while
 * those are on their way, and give way to the server's own `generating`
 * rows the moment a reply lands in the cache — see the plan's
 * "Decisions", 8. They carry no `✕`: there is no row yet to cancel.
 *
 * With nothing at all, the grid's place is taken by the spec's dashed
 * row, which points at the panels right above it.
 *
 * The section's label doubles as a focus anchor. A tile deleted by
 * keyboard unmounts the `✕` that was focused, and focus would fall to the
 * top of the document; it lands here instead, a tab away from whatever
 * tiles remain.
 *
 * Clicking any tile opens the render over the topic, and the modal pages
 * between them — see `useRenderCursor` for what happens when the row it is
 * showing is deleted from under it.
 */
export function RenderGrid({
  renders,
  runId,
  pending,
}: {
  renders: RenderRecord[];
  runId: string;
  pending: GenerationRequest[];
}) {
  const placeholders = pending.flatMap(placeholdersFor);
  const empty = renders.length === 0 && placeholders.length === 0;
  const anchor = useRef<HTMLDivElement | null>(null);
  // Which render the modal is showing, and what happens to it when a row
  // goes: a delete from inside the modal advances to the render that took
  // its place rather than closing. See `useRenderCursor`.
  const cursor = useRenderCursor(renders);
  const wasOpen = useRef(false);

  // Focus needs rescuing in exactly one case: the modal closing because the
  // last render went. `Modal` hands focus back to whatever opened it, but
  // that tile left with the row, and a detached node cannot take focus — so
  // it falls to the document. Every other close has a tile to return to and
  // `Modal` has already used it, which is why this is guarded on the list
  // being empty rather than on the modal merely closing.
  useEffect(() => {
    const open = cursor.record !== null;
    if (wasOpen.current && !open && renders.length === 0) anchor.current?.focus();
    wasOpen.current = open;
  }, [cursor.record, renders.length]);

  return (
    <section className={styles.section}>
      <div ref={anchor} tabIndex={-1}>
        <SectionLabel hint={empty ? undefined : hint(renders, placeholders.length, runId)}>
          Rendered from this topic
        </SectionLabel>
      </div>
      {empty ? (
        <p className={styles.nothing}>Nothing rendered yet — use the panel above</p>
      ) : (
        <ul className={styles.grid}>
          {renders.map((render) => (
            <li
              key={render.id}
              // The open render, marked so the grid behind the scrim says
              // where the arrows are. The attribute carries the meaning and
              // the stylesheet paints from it, so there is one source of
              // truth rather than a class nothing asserts.
              aria-current={render.id === cursor.record?.id ? "true" : undefined}
            >
              <RenderTile
                render={render}
                onRemoved={() => anchor.current?.focus()}
                onOpen={(event) => {
                  if (!opensHere(event)) return;
                  event.preventDefault();
                  cursor.open(render.id);
                }}
              />
            </li>
          ))}
          {placeholders.map((tile, index) => (
            // Index keys are right here: a placeholder has no identity of
            // its own, and all of a request's placeholders go at once.
            <li key={`pending-${index}`}>
              <GeneratingTile label={tile.label} doing={tile.doing} />
            </li>
          ))}
        </ul>
      )}
      {cursor.record !== null && (
        <RenderModal
          record={cursor.record}
          onClose={cursor.close}
          // Nothing to page to with a single render, and then the modal
          // draws neither chevrons nor counter — a topic with one meme looks
          // exactly as it did before paging existed.
          nav={
            cursor.count > 1
              ? {
                  onPrev: cursor.prev,
                  onNext: cursor.next,
                  hasPrev: cursor.hasPrev,
                  hasNext: cursor.hasNext,
                  index: cursor.index,
                  count: cursor.count,
                }
              : undefined
          }
        />
      )}
    </section>
  );
}
