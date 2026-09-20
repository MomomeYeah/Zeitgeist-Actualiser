import { useNavigate, useParams } from "react-router-dom";

import { useRender, useTopicDetail } from "@/api/queries";
import { Breadcrumb } from "@/components/Breadcrumb";
import { QueryBoundary } from "@/components/QueryBoundary";
import { RenderDetail } from "@/features/renders/RenderDetail";
import { templateLabel } from "@/features/renders/render";

import styles from "./RenderDetailPage.module.css";

/**
 * A render at its permanent address — what Copy link hands out, and the
 * only way in for someone who did not arrive from a tile.
 *
 * It fetches; the modal does not. Arriving here there are two ids and
 * nothing else, so the record and the topic's title both have to be asked
 * for. The body below the heading is the same component the modal draws.
 */
export function RenderDetailPage() {
  const { renderId } = useParams();
  const render = useRender(renderId);
  // The breadcrumb and the heading want the topic's title, which
  // `RenderRecord` does not carry — it carries the ids that address it.
  const topic = useTopicDetail(render.data?.run_id, render.data?.topic_id);
  const navigate = useNavigate();

  return (
    <QueryBoundary query={render} missing="No such render.">
      {(record) => {
        // Used for both the heading and its own breadcrumb entry, so the
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
                { label: templateLabel(record) },
              ]}
            />

            <header className={styles.header}>
              <h1 className={styles.title}>{topicLabel}</h1>
            </header>

            <RenderDetail
              record={record}
              onDeleted={() =>
                void navigate(
                  `/topics/${encodeURIComponent(record.run_id)}` +
                    `/${encodeURIComponent(record.topic_id)}`,
                )
              }
            />
          </div>
        );
      }}
    </QueryBoundary>
  );
}
