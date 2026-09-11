import { useDeleteRender } from "@/api/queries";
import type { RenderRecord } from "@/api/types";
import { InlineConfirm } from "@/components/InlineConfirm";
import { MemeTile } from "@/components/MemeTile";

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
}: {
  label: string;
  doing: string;
  onCancel?: () => void;
}) {
  return (
    <div className={styles.generating}>
      <div className={styles.working}>
        <span className={styles.track} aria-hidden="true">
          <span className={styles.sweep} />
        </span>
        <span className={styles.doing}>{doing}</span>
      </div>
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
 * - **failed** — kept rather than vanishing, per the handoff, with the
 *   server's own sentence in the footer. Its `✕` dismisses at once: there
 *   is no image to lose.
 * - **deleting** — dimmed until the row leaves the cache, so one click
 *   cannot become two DELETEs.
 *
 * See the plan's "Decisions", 5 and 6.
 */
export function RenderTile({ render }: { render: RenderRecord }) {
  const remove = useDeleteRender();
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
          onCancel={() => remove.mutate(render)}
        />
        {failure}
      </>
    );
  }

  if (render.status === "failed") {
    return (
      <div className={styles.failed}>
        <div className={styles.failedPreview}>
          <span className={styles.failedWord}>failed</span>
          <span className={styles.failedLine}>
            {`${render.template_id ?? "no template"} · ${provenance}`}
          </span>
        </div>
        <div className={styles.footer}>
          <span className={styles.error} title={render.error ?? undefined}>
            {render.error ?? "No reason was recorded."}
          </span>
          <button
            type="button"
            className={styles.cross}
            aria-label="Dismiss render"
            onClick={() => remove.mutate(render)}
          >
            ✕
          </button>
        </div>
        {failure}
      </div>
    );
  }

  const to =
    `/runs/${encodeURIComponent(render.run_id)}` +
    `/renders/${encodeURIComponent(render.id)}`;
  return (
    <div className={styles.tile}>
      <MemeTile
        renderId={render.id}
        size="grid"
        to={to}
        templateId={render.template_id ?? undefined}
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
        onConfirm={() => remove.mutate(render)}
      />
      {failure}
    </div>
  );
}
