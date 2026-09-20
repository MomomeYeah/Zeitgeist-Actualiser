import { useState } from "react";

import { imageUrl } from "@/api/client";
import { useDeleteRender } from "@/api/queries";
import type { RenderRecord } from "@/api/types";
import { Chip } from "@/components/Chip";
import { CopyLinkButton } from "@/components/CopyLinkButton";
import { InlineConfirm } from "@/components/InlineConfirm";
import { SectionLabel } from "@/components/SectionLabel";
import { renderPath, templateLabel } from "@/features/renders/render";
import { shortRunId } from "@/format";

import styles from "./RenderDetail.module.css";

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
 * dimensions — see the design spec, "What the body shows".
 */
export function RenderDetail({
  record,
  onDeleted,
}: {
  record: RenderRecord;
  /** Called once the row has gone: the page navigates, the modal closes. */
  onDeleted: () => void;
}) {
  const [failed, setFailed] = useState(false);
  const remove = useDeleteRender();
  const template = templateLabel(record);

  return (
    <div className={styles.detail}>
      <div className={styles.chips} data-testid="chips">
        <Chip tone="accent">{template}</Chip>
        <Chip>{record.origin.provenance}</Chip>
      </div>

      <figure className={styles.frame}>
        {failed ? (
          // The database is authoritative for whether a render exists, so a
          // PNG deleted out from under this row is a styled failed state,
          // not a broken-image icon — the same rule `MemeTile` follows for
          // the tiles that open this. The id is shortened because a full
          // 32-character one is noise rather than something to hold onto.
          <span className={styles.failed}>
            {`Render ${shortRunId(record.id)} has no image on disk`}
          </span>
        ) : (
          <img
            className={styles.image}
            src={imageUrl(record.id, "full")}
            alt={`${template} meme`}
            onError={() => setFailed(true)}
          />
        )}
      </figure>

      {record.origin.provenance === "auto" ? (
        <>
          <SectionLabel>Why this template</SectionLabel>
          <p className={styles.rationale}>{record.origin.rationale}</p>
        </>
      ) : (
        <p className={styles.byHand}>written by hand</p>
      )}

      <div className={styles.footer}>
        {!failed && (
          <a
            className={styles.download}
            href={imageUrl(record.id, "full")}
            download={`${template}-${record.id}.png`}
          >
            Download PNG
          </a>
        )}
        <CopyLinkButton path={renderPath(record)} />
        {/* Offered whether or not the image loaded: a render whose PNG is
            gone is the likeliest to want deleting. Pushed away from the two
            safe actions rather than sitting beside them.

            The margin is on a wrapper, not on `InlineConfirm`'s `className`:
            that prop reaches only the resting trigger, so the question that
            replaces it would lose the margin and jump left across the
            footer at the moment of being read. */}
        <div className={styles.delete}>
          <InlineConfirm
            label="Delete"
            question="Delete this render?"
            disabled={remove.isPending}
            onConfirm={() => remove.mutate(record, { onSuccess: onDeleted })}
          />
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
