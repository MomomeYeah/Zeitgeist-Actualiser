import { useState } from "react";

import { imageUrl } from "@/api/client";
import { useDeleteRender } from "@/api/queries";
import type { RenderRecord } from "@/api/types";
import { Chip } from "@/components/Chip";
import { CopyLinkButton } from "@/components/CopyLinkButton";
import { InlineConfirm } from "@/components/InlineConfirm";
import { SectionLabel } from "@/components/SectionLabel";
import { WorkingBar } from "@/components/WorkingBar";
import { renderPath, templateLabel } from "@/features/renders/render";
import { shortRunId } from "@/format";

import styles from "./RenderDetail.module.css";

/**
 * What a caller that can page hands down.
 *
 * It lives on `RenderDetail` rather than on `RenderModal` because the
 * chevrons sit on the image frame, and the frame is this component's.
 * Positioning them from outside would mean guessing the frame's height and
 * would break the moment its padding changed.
 */
export interface RenderNav {
  onPrev: () => void;
  onNext: () => void;
  hasPrev: boolean;
  hasNext: boolean;
  /** 0-based. The counter draws `index + 1`. */
  index: number;
  count: number;
}

/**
 * What the frame holds.
 *
 * A render only has an image once it is `ready`, and even then the PNG can
 * be gone from disk, so there are four cases and the picture is one of
 * them. The rules are `RenderTile`'s own rather than new ones — the tile
 * and the modal must not disagree about what a failed render is.
 */
function Frame({
  record,
  broken,
  onBroken,
}: {
  record: RenderRecord;
  /** Whether the image has already failed to load. */
  broken: boolean;
  onBroken: () => void;
}) {
  if (record.status === "generating") {
    return (
      <WorkingBar
        doing={record.origin.provenance === "manual" ? "rendering…" : "writing brief…"}
      />
    );
  }

  if (record.status === "failed") {
    // The row's own reason, in full. The tile says only that it failed, so
    // this is the only place it can be read.
    return (
      <span className={styles.failed}>{record.error ?? "No reason was recorded."}</span>
    );
  }

  if (broken) {
    // The database is authoritative for whether a render exists, so a PNG
    // deleted from under the row is a styled panel naming the shortened id,
    // not a broken-image icon. A different failure from the one above, so a
    // different sentence in the same panel.
    return (
      <span className={styles.failed}>
        {`Render ${shortRunId(record.id)} has no image on disk`}
      </span>
    );
  }

  return (
    <img
      className={styles.image}
      src={imageUrl(record.id, "full")}
      alt={`${templateLabel(record)} meme`}
      onError={onBroken}
    />
  );
}

/**
 * One render, at full size: the meme, what made it, and what can be done
 * with it. Drawn by the permanent route and by the modal the topic screen
 * opens, identically — the page adds a breadcrumb and a heading above it,
 * the modal adds a close button, and neither changes what is inside.
 *
 * It takes the record rather than fetching one. The topic screen is already
 * holding every field this needs in `TopicDetail.renders`, so the modal
 * opens on the current frame with no spinner and no second request, and
 * cannot disagree with the tile that opened it.
 *
 * The slot captions are deliberately absent: they are drawn on the meme in
 * the frame above. So are the run id, the generated time and the decoded
 * dimensions — see `2026-09-20-render-modal-design.md`, "What the body
 * shows".
 */
export function RenderDetail({
  record,
  onDeleted,
  nav,
}: {
  record: RenderRecord;
  /**
   * Called once the row has gone. The standalone page is the real
   * consumer: it navigates back to the topic. The modal path passes a
   * no-op — `RenderGrid`'s cursor derives what to show next from the list
   * itself, because a row can leave for reasons that are not a delete from
   * the modal. See `useRenderCursor`.
   */
  onDeleted: () => void;
  /**
   * Prev/next, when there is more than one render to look at. Absent on the
   * standalone route and on a topic with a single render, and then the
   * frame draws no chevrons and no counter.
   */
  nav?: RenderNav;
}) {
  const [broken, setBroken] = useState(false);
  const remove = useDeleteRender();
  const template = templateLabel(record);
  const destroy = () => remove.mutate(record, { onSuccess: onDeleted });
  // Something to hand over only exists on a ready row whose PNG loaded.
  const downloadable = record.status === "ready" && !broken;

  // For `auto`, the reason the model gave. A `generating` auto row has none
  // yet — the column is an empty string until the brief lands — and a
  // heading over an empty paragraph is worse than no heading.
  const why =
    record.origin.provenance === "manual" ? (
      <p className={styles.byHand}>written by hand</p>
    ) : record.origin.rationale === "" ? null : (
      <>
        <SectionLabel>Why this template</SectionLabel>
        <p className={styles.rationale}>{record.origin.rationale}</p>
      </>
    );

  return (
    <div className={styles.detail}>
      <div className={styles.chips} data-testid="chips">
        <Chip tone="accent">{template}</Chip>
        <Chip>{record.origin.provenance}</Chip>
      </div>

      <figure className={styles.frame}>
        {nav !== undefined && (
          <button
            type="button"
            className={`${styles.chevron} ${styles.prev}`}
            aria-label="Previous render"
            disabled={!nav.hasPrev}
            onClick={nav.onPrev}
          >
            ‹
          </button>
        )}
        <Frame record={record} broken={broken} onBroken={() => setBroken(true)} />
        {nav !== undefined && (
          <>
            <button
              type="button"
              className={`${styles.chevron} ${styles.next}`}
              aria-label="Next render"
              disabled={!nav.hasNext}
              onClick={nav.onNext}
            >
              ›
            </button>
            {/* The glyphs above say nothing to a screen reader, which is
                what the aria-labels are for; this line is for the eye and
                needs no label of its own. */}
            <span className={styles.counter}>{`${nav.index + 1} / ${nav.count}`}</span>
          </>
        )}
      </figure>

      {why}

      <div className={styles.footer}>
        {downloadable && (
          <a
            className={styles.download}
            href={imageUrl(record.id, "full")}
            download={`${template}-${record.id}.png`}
          >
            Download PNG
          </a>
        )}
        <CopyLinkButton path={renderPath(record)} />
        {/* Offered whether or not there is an image: a render whose PNG is
            gone, or which never had one, is the likeliest to want deleting.
            Pushed away from the two safe actions rather than sitting beside
            them.

            The margin is on a wrapper, not on `InlineConfirm`'s
            `className`: that prop reaches only the resting trigger, so the
            question that replaces it would lose the margin and jump left
            across the footer at the moment of being read.

            Only a ready render asks first. A failed or generating row has
            no image to lose, which is why the tile's own ✕ does not ask
            either — one rule, drawn twice. */}
        <div className={styles.delete}>
          {record.status === "ready" ? (
            <InlineConfirm
              label="Delete"
              question="Delete this render?"
              disabled={remove.isPending}
              onConfirm={destroy}
            />
          ) : (
            <button
              type="button"
              className={styles.dismiss}
              disabled={remove.isPending}
              onClick={destroy}
            >
              {record.status === "failed" ? "Dismiss" : "Cancel"}
            </button>
          )}
        </div>
      </div>
      {remove.isError && (
        <p role="alert" className={styles.deleteError}>
          {remove.error.detail}
        </p>
      )}
    </div>
  );
}
