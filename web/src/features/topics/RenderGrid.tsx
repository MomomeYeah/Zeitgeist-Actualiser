import { useRef } from "react";

import type { GenerationRequest, RenderRecord } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";
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
              <RenderTile render={render} onRemoved={() => anchor.current?.focus()} />
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
    </section>
  );
}
