import { useParams } from "react-router-dom";

import { useRun, useTopicDetail } from "@/api/queries";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Chip } from "@/components/Chip";
import { QueryBoundary } from "@/components/QueryBoundary";
import { DossierCards } from "@/features/topics/DossierCards";
import { PhraseCard } from "@/features/topics/PhraseCard";
import { RenderGrid } from "@/features/topics/RenderGrid";
import { ReplyList } from "@/features/topics/ReplyList";
import { formatScore } from "@/format";

import styles from "./TopicDetailPage.module.css";

export function TopicDetailPage() {
  const { runId, topicId } = useParams();
  const detail = useTopicDetail(runId, topicId);
  // Only for `phrase_min_authors`: TopicDetail carries no config, and the
  // phrases footer names the run's own frozen threshold.
  const run = useRun(runId);

  return (
    <QueryBoundary query={detail} missing="No such topic in this run.">
      {(data) => {
        const { topic, dossier, recurrence } = data;
        const seen =
          recurrence.first_seen_run_id === null
            ? "new this run"
            : `first seen ${recurrence.first_seen_run_id}`;

        return (
          <div className={styles.page}>
            <Breadcrumb
              trail={[{ label: "Topics", to: "/" }, { label: `${topic.topic_id} · ${seen}` }]}
            />

            <header className={styles.header}>
              <div>
                <h1 className={styles.title}>{topic.label}</h1>
                <div className={styles.chips}>
                  {topic.event_sentiment != null && (
                    <Chip tone="accent">{topic.event_sentiment}</Chip>
                  )}
                  {topic.conversation_register != null && (
                    <Chip>{topic.conversation_register}</Chip>
                  )}
                  {(dossier?.secondary_registers ?? []).length > 0 && (
                    <Chip>{`2nd: ${(dossier?.secondary_registers ?? []).join(", ")}`}</Chip>
                  )}
                  <Chip tone="contrast">{topic.trend_status}</Chip>
                </div>
              </div>

              <dl className={styles.stats} data-testid="stats">
                <div>
                  <dt>TREND</dt>
                  <dd>{formatScore(topic.trend_score)}</dd>
                </div>
                <div>
                  <dt>MEME</dt>
                  <dd className={styles.meme}>{formatScore(topic.meme_potential)}</dd>
                </div>
                <div>
                  <dt>RANK</dt>
                  <dd>{topic.final_rank}</dd>
                </div>
              </dl>
            </header>

            <DossierCards dossier={dossier} scoreComponents={data.score_components} />

            <div className={styles.conversation}>
              <ReplyList replies={data.replies} />
              <PhraseCard
                phrases={dossier?.recurring_phrases ?? []}
                minAuthors={run.data?.run.config.phrase_min_authors}
              />
            </div>

            <RenderGrid renders={data.renders} runId={topic.run_id} />
          </div>
        );
      }}
    </QueryBoundary>
  );
}
