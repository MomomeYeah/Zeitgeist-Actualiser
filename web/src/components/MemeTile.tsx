import { useState } from "react";
import { Link } from "react-router-dom";

import { imageUrl } from "@/api/client";

import styles from "./MemeTile.module.css";

/**
 * One rendered meme, at one of the three sizes the design draws: 34px in a
 * runs-list row, 42px in a ranking row, 96px in a topic-detail grid.
 *
 * The database is authoritative for whether a render exists, so a row whose
 * PNG is missing is a failed tile rather than a broken image or a crash.
 * That state is reached through the image's own `onError`, which is also how
 * a partially failed run shows itself on the runs list — see "Decisions this
 * phase is required to make", 7.
 *
 * Phase 7 adds the other two states, `confirming` and `generating`.
 */
export function MemeTile({
  renderId,
  size,
  to,
  templateId,
}: {
  renderId: string;
  size: 34 | 42 | 96;
  to?: string;
  templateId?: string;
}) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <span
        className={styles.failed}
        style={{ "--tile": `${size}px` }}
        title={`Render ${renderId} has no image on disk`}
      >
        failed
      </span>
    );
  }

  const image = (
    <img
      className={styles.image}
      src={imageUrl(renderId, size >= 96 ? "full" : "thumb")}
      alt={templateId === undefined ? "meme" : `${templateId} meme`}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );

  return (
    <span className={styles.tile} style={{ "--tile": `${size}px` }}>
      {to === undefined ? image : <Link to={to}>{image}</Link>}
    </span>
  );
}
