import type { MouseEvent } from "react";
import { useEffect, useRef, useState } from "react";

import type { GenerationRequest, RenderRecord } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";
import { RenderModal } from "@/features/renders/RenderModal";
import { GeneratingTile, RenderTile } from "@/features/topics/RenderTile";
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
  // The id rather than the record: the row behind it can change — a
  // generating render turning ready — and a copy taken at click time would
  // show a frame that has already moved on.
  const [openId, setOpenId] = useState<string | null>(null);
  const open = renders.find((render) => render.id === openId) ?? null;

  // The open render's row leaving the list is how a delete finishes: the
  // mutation drops it from the cache, so `open` goes null and the modal
  // unmounts on the very next render. That is also why the modal cannot
  // report the delete through a callback — react-query does not run a
  // `mutate()` callback whose component has already gone, and this one
  // has.
  //
  // Focus is what needs rescuing. `Modal` hands it back to whatever opened
  // it, but that tile went with the row, and a detached node cannot take
  // focus, so it falls to the document. This effect runs after that
  // cleanup and puts it on the section label instead — where a tile-level
  // delete already sends it, a tab away from whatever tiles remain.
  useEffect(() => {
    if (openId !== null && open === null) {
      setOpenId(null);
      anchor.current?.focus();
    }
  }, [openId, open]);

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
            <li key={render.id}>
              <RenderTile
                render={render}
                onRemoved={() => anchor.current?.focus()}
                onOpen={(event) => {
                  if (!opensHere(event)) return;
                  event.preventDefault();
                  setOpenId(render.id);
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
      {open !== null && <RenderModal record={open} onClose={() => setOpenId(null)} />}
    </section>
  );
}
