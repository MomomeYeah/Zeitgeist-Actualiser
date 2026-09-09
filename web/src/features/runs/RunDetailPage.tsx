import { useParams } from "react-router-dom";

import type { RankedTopic, RunDetail, StageRecord } from "@/api/types";
import { useRanking, useRun } from "@/api/queries";
import { Breadcrumb } from "@/components/Breadcrumb";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { StatusPill } from "@/components/StatusPill";
import { RankingList } from "@/features/runs/RankingList";
import { StageCards } from "@/features/runs/StageCards";
import { survivedFor } from "@/features/runs/survived";
import { formatDuration, shortRunId } from "@/format";

import styles from "./RunDetailPage.module.css";

/** Sources, the three fan-out numbers, the model, the duration. */
function configLine(detail: RunDetail): string {
  const { run } = detail;
  const config = run.config;
  return [
    config.sources.join(" · "),
    `trend_limit ${config.trend_limit}`,
    `posts_per_trend ${config.posts_per_trend}`,
    `top_count ${config.top_count}`,
    config.llm_model,
    formatDuration(run.started_at, run.finished_at),
  ].join(" · ");
}

/**
 * The generate stage ran and produced nothing.
 *
 * Both halves are needed: a run that died in analyse also has zero renders,
 * and telling that user every brief failed would send them looking for a
 * renderer problem that does not exist.
 */
function everyBriefFailed(stages: StageRecord[], ranking: RankedTopic[]): boolean {
  const generate = stages.find((stage) => stage.stage === "generate");
  if (generate === undefined || generate.status === "queued") return false;
  return (
    ranking.length > 0 &&
    ranking.every((entry) => entry.render_count === 0)
  );
}

export function RunDetailPage() {
  const { runId } = useParams();
  const run = useRun(runId);
  const ranking = useRanking(runId);

  return (
    <QueryBoundary query={run} missing="No such run.">
      {(detail) => (
        <div className={styles.page}>
          <Breadcrumb
            trail={[
              { label: "Runs", to: "/runs" },
              // Shortened rather than the mockup's full id: the header two
              // lines down already shows it in full, and `findByText` (and
              // a reader's eye) needs the run id to appear once, not twice,
              // in identical text.
              { label: shortRunId(detail.run.run_id) },
            ]}
          />

          <header className={styles.header}>
            <div className={styles.identity}>
              <StatusPill status={detail.run.status} />
              <span className={styles.runId}>{detail.run.run_id}</span>
            </div>
            <MetaLine>{configLine(detail)}</MetaLine>
            {detail.run.error !== null && (
              <p className={styles.error}>
                {detail.run.error.kind} in {detail.run.error.stage} —{" "}
                {detail.run.error.message} · {survivedFor(detail.run.error.stage)}
              </p>
            )}
          </header>

          <StageCards stages={detail.stages} />

          <QueryBoundary query={ranking} missing="No such run.">
            {(rows) =>
              rows.length === 0 ? (
                <p className={styles.noRanking}>
                  This run wrote no ranking — it did not reach evaluate.
                </p>
              ) : (
                <RankingList
                  ranking={rows}
                  topCount={detail.run.config.top_count}
                  everyBriefFailed={everyBriefFailed(detail.stages, rows)}
                />
              )
            }
          </QueryBoundary>
        </div>
      )}
    </QueryBoundary>
  );
}
