import { useState } from "react";
import { Link } from "react-router-dom";

import { imageUrl } from "@/api/client";

import styles from "./MemeTile.module.css";

/**
 * One rendered meme, at one of the two sizes the app draws: 34px in a
 * runs-list row, and `"grid"` — the full width of a topic-detail tile,
 * 112px tall. The design's 42px ranking tile is not among them: a ranking
 * row states its meme count instead, because `RankedTopic` carries no
 * render ids to address an image with.
 *
 * The database is authoritative for whether a render exists, so a row whose
 * PNG is missing is a failed tile rather than a broken image or a crash.
 * That state is reached through the image's own `onError`, which is also how
 * a partially failed run shows itself on the runs list — see "Decisions this
 * phase is required to make", 7.
 *
 * The tile's other states — generating, failed as a row, confirming a
 * delete — belong to the card around it, `features/topics/RenderTile`,
 * because they live in its footer and its preview rather than in the image.
 */
export function MemeTile({
  renderId,
  size,
  to,
  templateId,
}: {
  renderId: string;
  size: 34 | "grid";
  to?: string;
  templateId?: string;
}) {
  const [failed, setFailed] = useState(false);

  const grid = size === "grid";
  // The grid tile is drawn far wider than the 96px thumbnail, so it gets
  // the full PNG; a 34px row tile would only be throwing bytes away.
  const source = grid ? "full" : "thumb";
  const box = grid ? undefined : { "--tile": `${size}px` };

  if (failed) {
    return (
      <span
        className={grid ? `${styles.failed} ${styles.grid}` : styles.failed}
        style={box}
        title={`Render ${renderId} has no image on disk`}
      >
        failed
      </span>
    );
  }

  const image = (
    <img
      className={styles.image}
      src={imageUrl(renderId, source)}
      alt={templateId === undefined ? "meme" : `${templateId} meme`}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );

  return (
    <span className={grid ? `${styles.tile} ${styles.grid}` : styles.tile} style={box}>
      {to === undefined ? image : <Link to={to}>{image}</Link>}
    </span>
  );
}
