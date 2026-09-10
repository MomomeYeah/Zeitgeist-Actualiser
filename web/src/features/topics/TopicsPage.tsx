import { useState } from "react";

import type { TrendStatus } from "@/api/types";
import { useActiveRun, useRuns, useTopicIndex } from "@/api/queries";
import { EmptyState } from "@/components/EmptyState";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { SectionLabel } from "@/components/SectionLabel";
import { NewRunButton } from "@/features/newrun/NewRunButton";
import { RunStrip } from "@/features/runs/RunStrip";
import { HeroTopic } from "@/features/topics/HeroTopic";
import { MoodBar } from "@/features/topics/MoodBar";
import { RecentTable } from "@/features/topics/RecentTable";
import { StatusFilters } from "@/features/topics/StatusFilters";
import { TopicCard } from "@/features/topics/TopicCard";
import { byRank } from "@/features/topics/ordering";
import { formatClock } from "@/format";

import styles from "./TopicsPage.module.css";

/** Three, matching the run strip phase 6 puts beside the mood bar. */
const RUN_STRIP = 3;
const TRENDING_CARDS = 3;

export function TopicsPage() {
  const [status, setStatus] = useState<TrendStatus | undefined>(undefined);
  const index = useTopicIndex({ status });
  const runs = useRuns(RUN_STRIP);
  const active = useActiveRun();

  return (
    <QueryBoundary query={index} missing="No topics.">
      {(data) => {
        const ordered = byRank(data.topics);
        const hero = ordered[0];
        const trending = ordered.filter(
          (entry) => entry.topic.trend_status === "trending",
        );
        const recent = ordered.filter(
          (entry) => entry.topic.trend_status !== "trending",
        );
        const latestRun = runs.data?.runs[0];
        const noRunsAtAll = runs.isSuccess && runs.data.runs.length === 0;

        return (
          <div className={styles.page}>
            <header className={styles.header}>
              <div className={styles.titleRow}>
                <h1 className={styles.title}>Right now</h1>
                <NewRunButton />
              </div>
              <MetaLine>
                {[
                  `${data.status_totals.trending ?? 0} trending`,
                  `${data.status_totals.saturating ?? 0} saturating`,
                  `${data.status_totals.cooling ?? 0} cooling`,
                  ...(runs.isError
                    ? []
                    : [
                        latestRun === undefined
                          ? "no runs yet"
                          : `as of ${formatClock(latestRun.run.finished_at ?? latestRun.run.started_at)}`,
                      ]),
                ].join(" · ")}
              </MetaLine>
            </header>

            {noRunsAtAll ? (
              <EmptyState
                headline="Nothing has run yet"
                body="A run reads Bluesky, works out what is trending, and generates memes about it. The first one takes a few minutes."
                action={<NewRunButton />}
              />
            ) : (
              <>
                {hero !== undefined && (
                  <div className={styles.heroRow}>
                    <HeroTopic entry={hero} />
                  </div>
                )}

                <div className={styles.bottom}>
                  <div>
                    <SectionLabel>The mood today</SectionLabel>
                    <MoodBar
                      totals={data.sentiment_totals}
                      previous={data.previous_sentiment_totals}
                    />
                  </div>
                  <div className={styles.runs}>
                    <SectionLabel>Runs</SectionLabel>
                    <RunStrip
                      runs={runs.data?.runs ?? []}
                      activeRunId={active.data?.current ?? null}
                    />
                  </div>
                </div>

                <div className={styles.filters}>
                  <StatusFilters
                    totals={data.status_totals}
                    active={status}
                    onChange={setStatus}
                  />
                </div>

                {data.topics.length === 0 ? (
                  status === undefined ? (
                    <EmptyState
                      headline="No topics in the last 6 runs"
                      body="Everything has gone stale. Start a run to see what is trending now."
                    />
                  ) : (
                    <p className={styles.filtered}>No topics with this status.</p>
                  )
                ) : (
                  <>
                    {trending.length > 0 && (
                      <section className={styles.block} data-testid="trending-now">
                        <SectionLabel>Trending now</SectionLabel>
                        <div className={styles.cards}>
                          {trending.slice(0, TRENDING_CARDS).map((entry, position) => (
                            <TopicCard
                              key={`${entry.topic.run_id}-${entry.topic.topic_id}`}
                              entry={entry}
                              highlighted={position === 0}
                            />
                          ))}
                        </div>
                      </section>
                    )}

                    {recent.length > 0 && (
                      <section className={styles.block}>
                        <SectionLabel>Recently trending — saturating &amp; cooling</SectionLabel>
                        <RecentTable topics={recent} />
                      </section>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        );
      }}
    </QueryBoundary>
  );
}
