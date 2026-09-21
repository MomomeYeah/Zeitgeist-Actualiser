import type { MouseEvent } from "react";
import { Link } from "react-router-dom";

import { useDeleteRender } from "@/api/queries";
import type { RenderRecord } from "@/api/types";
import { InlineConfirm } from "@/components/InlineConfirm";
import { MemeTile } from "@/components/MemeTile";
import { WorkingBar } from "@/components/WorkingBar";
import { renderPath } from "@/features/renders/render";

import styles from "./RenderTile.module.css";

/**
 * A tile still being made: the handoff's generating state, and — with no
 * `onCancel` — the placeholder the grid draws for a request in flight.
 *
 * The bar sweeps rather than standing at the mockup's 45%: nothing reports
 * how far along a brief is, so a fixed fraction would be a number made up
 * for the screen. See the plan's "Decisions", 4.
 */
export function GeneratingTile({
  label,
  doing,
  onCancel,
  to,
  onOpen,
}: {
  label: string;
  doing: string;
  onCancel?: () => void;
  /**
   * The render's permanent address. Absent on the grid's placeholders —
   * a request in flight has no row, so there is nothing to address.
   */
  to?: string;
  /** First refusal on a click of the preview — see `RenderGrid`. */
  onOpen?: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
  const working = (
    <div className={styles.working}>
      <WorkingBar doing={doing} />
    </div>
  );

  return (
    <div className={styles.generating}>
      {to === undefined ? (
        working
      ) : (
        <Link className={styles.previewLink} to={to} onClick={onOpen}>
          {working}
        </Link>
      )}
      <div className={styles.footer}>
        <span className={styles.line}>{label}</span>
        {onCancel !== undefined && (
          <button
            type="button"
            className={styles.cross}
            aria-label="Cancel render"
            onClick={onCancel}
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * One tile of "Rendered from this topic", in whichever state its row is.
 *
 * - **ready** — the image, linked to its full-size view, and a `✕` that
 *   asks first: a ready render is a PNG someone may want.
 * - **generating** — `GeneratingTile`, whose `✕` cancels at once: nothing
 *   has been made, so there is nothing to lose but the wait. The job keeps
 *   running server-side and its result is dropped, because a deleted row
 *   stays deleted (`generation._draw`).
 * - **failed** — kept rather than vanishing, per the handoff. The footer
 *   says only `Render failed`; the server's reason is in the modal the
 *   preview opens, which has room for a sentence. Its `✕` dismisses at
 *   once: there is no image to lose.
 * - **deleting** — dimmed until the row leaves the cache, so one click
 *   cannot become two DELETEs.
 *
 * See the plan's "Decisions", 5 and 6.
 */
export function RenderTile({
  render,
  onRemoved,
  onOpen,
}: {
  render: RenderRecord;
  /**
   * Called once the row has left the cache, so the grid can take the focus
   * this tile is about to unmount with.
   */
  onRemoved?: () => void;
  /** First refusal on a click of a ready tile's image — see `MemeTile`. */
  onOpen?: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
  const remove = useDeleteRender();
  const drop = () => remove.mutate(render, { onSuccess: onRemoved });
  const provenance = render.origin.provenance;
  const failure = remove.isError ? (
    <p role="alert" className={styles.deleteError}>
      {remove.error.detail}
    </p>
  ) : null;

  if (remove.isPending) {
    return (
      <div className={styles.deleting}>
        <div className={styles.preview} />
        <div className={styles.footer}>
          <span className={styles.line}>deleting…</span>
        </div>
      </div>
    );
  }

  if (render.status === "generating") {
    return (
      <>
        <GeneratingTile
          label={`${render.template_id ?? "choosing…"} · ${provenance}`}
          doing={provenance === "manual" ? "rendering…" : "writing brief…"}
          onCancel={drop}
          to={renderPath(render)}
          onOpen={onOpen}
        />
        {failure}
      </>
    );
  }

  if (render.status === "failed") {
    return (
      <div className={styles.failed}>
        <Link className={styles.previewLink} to={renderPath(render)} onClick={onOpen}>
          <span className={styles.failedPreview}>
            <span className={styles.failedWord}>failed</span>
            <span className={styles.failedLine}>
              {`${render.template_id ?? "no template"} · ${provenance}`}
            </span>
          </span>
        </Link>
        <div className={styles.footer}>
          {/* The server's sentence lives in the modal now. A footer line
              either truncates it or stretches the tile, and the modal has
              room to show it whole. */}
          <span className={styles.error}>Render failed</span>
          <button
            type="button"
            className={styles.cross}
            aria-label="Dismiss render"
            onClick={drop}
          >
            ✕
          </button>
        </div>
        {failure}
      </div>
    );
  }

  return (
    <div className={styles.tile}>
      <MemeTile
        renderId={render.id}
        size="grid"
        to={renderPath(render)}
        templateId={render.template_id ?? undefined}
        onActivate={onOpen}
      />
      <InlineConfirm
        variant="tile"
        label="✕"
        ariaLabel="Delete render"
        question="Delete this render?"
        resting={
          <span className={styles.line}>
            {`${render.template_id ?? "no template"} · ${provenance}`}
          </span>
        }
        onConfirm={drop}
      />
      {failure}
    </div>
  );
}
