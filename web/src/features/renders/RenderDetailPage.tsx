import { useState } from "react";
import { useParams } from "react-router-dom";

import { imageUrl } from "@/api/client";
import { useRender, useTopicDetail } from "@/api/queries";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Chip } from "@/components/Chip";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { SectionLabel } from "@/components/SectionLabel";
import { formatClock } from "@/format";

import styles from "./RenderDetailPage.module.css";

export function RenderDetailPage() {
  const { renderId } = useParams();
  const render = useRender(renderId);
  // The breadcrumb wants the topic's title, which `RenderRecord` does not
  // carry — it carries the ids that address it.
  const topic = useTopicDetail(render.data?.run_id, render.data?.topic_id);
  const [size, setSize] = useState<string>("");

  return (
    <QueryBoundary query={render} missing="No such render.">
      {(record) => (
        <div className={styles.page}>
          <Breadcrumb
            trail={[
              { label: "Topics", to: "/" },
              {
                label: topic.data?.topic.label ?? record.topic_id,
                to: `/topics/${encodeURIComponent(record.run_id)}/${encodeURIComponent(record.topic_id)}`,
              },
              { label: record.template_id },
            ]}
          />

          <header className={styles.header}>
            <h1 className={styles.title}>
              {topic.data?.topic.label ?? record.topic_id}
            </h1>
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
              />
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

              <div className={styles.footer}>
                <a
                  className={styles.download}
                  href={imageUrl(record.id, "full")}
                  download={`${record.template_id}-${record.id}.png`}
                >
                  Download PNG
                </a>
              </div>
            </aside>
          </div>
        </div>
      )}
    </QueryBoundary>
  );
}
