import { useState } from "react";
import { useParams } from "react-router-dom";

import { imageUrl } from "@/api/client";
import { useRender, useTopicDetail } from "@/api/queries";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Chip } from "@/components/Chip";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { SectionLabel } from "@/components/SectionLabel";
import { formatClock, shortRunId } from "@/format";

import styles from "./RenderDetailPage.module.css";

export function RenderDetailPage() {
  const { renderId } = useParams();
  const render = useRender(renderId);
  // The breadcrumb wants the topic's title, which `RenderRecord` does not
  // carry — it carries the ids that address it.
  const topic = useTopicDetail(render.data?.run_id, render.data?.topic_id);
  const [size, setSize] = useState<string>("");
  const [failed, setFailed] = useState(false);

  return (
    <QueryBoundary query={render} missing="No such render.">
      {(record) => {
        // Used for both the page title and its own breadcrumb entry, so the
        // two can never drift apart.
        const topicLabel = topic.data?.topic.label ?? record.topic_id;

        return (
          <div className={styles.page}>
            <Breadcrumb
              trail={[
                { label: "Topics", to: "/" },
                {
                  label: topicLabel,
                  to: `/topics/${encodeURIComponent(record.run_id)}/${encodeURIComponent(record.topic_id)}`,
                },
                { label: record.template_id },
              ]}
            />

            <header className={styles.header}>
              <h1 className={styles.title}>{topicLabel}</h1>
              <div className={styles.chips} data-testid="chips">
                <Chip tone="accent">{record.template_id}</Chip>
                <Chip>{record.origin.provenance}</Chip>
              </div>
              <MetaLine>
                {[record.run_id, formatClock(record.created_at), size]
                  .filter((part) => part !== "")
                  .join(" · ")}
              </MetaLine>
            </header>

            <div className={styles.body}>
              <figure className={styles.frame}>
                {failed ? (
                  // The database is authoritative for whether a render
                  // exists, so a PNG deleted out from under this row is a
                  // styled failed state, not a broken-image icon — the same
                  // rule `MemeTile` already follows for the tiles that link
                  // here. The id is shortened because this is the one
                  // screen built to be deep-linked, and so the most likely
                  // to be read by someone who did not arrive from a tile.
                  <span className={styles.failed}>
                    {`Render ${shortRunId(record.id)} has no image on disk`}
                  </span>
                ) : (
                  <img
                    className={styles.image}
                    src={imageUrl(record.id, "full")}
                    alt={`${record.template_id} meme`}
                    // The contract carries no dimensions or byte size for a
                    // render, so this reports what the browser decoded rather
                    // than numbers nothing sent it.
                    onLoad={(event) =>
                      setSize(
                        `${event.currentTarget.naturalWidth}×${event.currentTarget.naturalHeight}`,
                      )
                    }
                    onError={() => setFailed(true)}
                  />
                )}
              </figure>

              <aside className={styles.brief}>
                <SectionLabel>The brief</SectionLabel>
                <dl className={styles.slots}>
                  {Object.entries(record.caption_slots).map(([slot, caption]) => (
                    <div key={slot} className={styles.slot}>
                      <dt className={styles.slotName}>{slot}</dt>
                      <dd className={styles.caption}>{caption}</dd>
                    </div>
                  ))}
                </dl>

                {record.origin.provenance === "auto" ? (
                  <>
                    <SectionLabel>Why this template</SectionLabel>
                    <p className={styles.rationale}>{record.origin.rationale}</p>
                  </>
                ) : (
                  <p className={styles.byHand}>written by hand</p>
                )}

                {!failed && (
                  <div className={styles.footer}>
                    <a
                      className={styles.download}
                      href={imageUrl(record.id, "full")}
                      download={`${record.template_id}-${record.id}.png`}
                    >
                      Download PNG
                    </a>
                  </div>
                )}
              </aside>
            </div>
          </div>
        );
      }}
    </QueryBoundary>
  );
}
