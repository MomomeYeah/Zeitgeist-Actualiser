import type { RunStatus, RunSummary } from "@/api/types";
import { useRuns } from "@/api/queries";
import { EmptyState } from "@/components/EmptyState";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { RunRow } from "@/features/runs/RunRow";

import styles from "./RunsPage.module.css";

/** Every status, in the order the line names them. */
const STATUS_ORDER: readonly RunStatus[] = [
  "ok",
  "failed",
  "aborted",
  "interrupted",
  "running",
];

/**
 * The page it is looking at, not an archive total.
 *
 * `GET /api/runs` is cursor-paginated and returns no totals; the handoff's
 * `27 total` would be a new field on a contract phase 4 closed. So the line
 * says "shown", which is both true and visibly about this page.
 *
 * Each status present is named with its own count rather than grouped into
 * the handoff's `ok · failed` pair. `RunStatus` has five members, and both
 * ways of forcing them into two are wrong on this line: grouping
 * everything-not-ok under "failed" calls an aborted run a failure, and
 * counting only the two named statuses prints a total the parts do not add
 * up to. The sources clause names every distinct source across the page
 * rather than claiming one, because a page can mix them.
 */
function summarise(runs: RunSummary[]): string {
  const counts = new Map<RunStatus, number>();
  for (const entry of runs) {
    counts.set(entry.run.status, (counts.get(entry.run.status) ?? 0) + 1);
  }
  const statuses = STATUS_ORDER.filter((status) => counts.has(status)).map(
    (status) => `${counts.get(status) ?? 0} ${status}`,
  );
  const sources = [...new Set(runs.flatMap((entry) => entry.run.config.sources))];
  return [`${runs.length} shown`, ...statuses, ...sources].join(" · ");
}

export function RunsPage() {
  const query = useRuns();

  return (
    <QueryBoundary query={query} missing="No runs.">
      {(page) => (
        <>
          <header className={styles.header}>
            <h1 className={styles.title}>Runs</h1>
            {page.runs.length > 0 && <MetaLine>{summarise(page.runs)}</MetaLine>}
          </header>

          {page.runs.length === 0 ? (
            <EmptyState
              headline="Nothing has run yet"
              body="A run reads Bluesky, works out what is trending, and generates memes about it. The first one takes a few minutes."
            />
          ) : (
            <ul className={styles.rows}>
              {page.runs.map((summary) => (
                <li key={summary.run.run_id}>
                  <RunRow summary={summary} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </QueryBoundary>
  );
}
