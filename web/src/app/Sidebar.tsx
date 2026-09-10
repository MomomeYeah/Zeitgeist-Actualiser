import { Link, NavLink } from "react-router-dom";

import { useActiveRun, useRun } from "@/api/queries";
import { activeStage } from "@/features/runs/progress";
import { useNow } from "@/features/runs/useNow";
import { formatElapsed } from "@/format";

import styles from "./Sidebar.module.css";

/**
 * 180px, one step darker than the page, three destinations and a card.
 *
 * Topics, Runs and Settings, in that order. The spec merges the landing
 * dashboard and the topics index into `/`, so the first two are the
 * handoff's own nav; Settings sits beneath them, which is the one place
 * these screens change the handoff's layout rather than extending it. The
 * in-flight card still pins to the bottom via `margin-top: auto`, so
 * nothing else moves.
 */
export function Sidebar() {
  return (
    <nav className={styles.rail}>
      <span className={styles.wordmark}>Zeitgeist</span>
      <ul className={styles.nav}>
        <li>
          {/* `end` because "/" prefix-matches every route in the app. */}
          <NavLink to="/" end className={navClass}>
            Topics
          </NavLink>
        </li>
        <li>
          <NavLink to="/runs" className={navClass}>
            Runs
          </NavLink>
        </li>
        <li>
          <NavLink to="/settings" className={navClass}>
            Settings
          </NavLink>
        </li>
      </ul>
      <InFlight />
    </nav>
  );
}

/**
 * Rendered only while a run is active, per the handoff.
 *
 * Two queries rather than one: `active` says *whether*, and is the app's
 * single source of truth for that; the run's own detail says *which stage*,
 * which `ActiveRuns` does not carry. The second is `enabled` only when the
 * first names a run, so an idle app issues neither.
 */
function InFlight() {
  const active = useActiveRun();
  const runId = active.data?.current ?? undefined;
  const run = useRun(runId);
  const now = useNow(runId !== undefined);

  if (runId === undefined || run.data === undefined) return null;

  const stage = activeStage(run.data.stages) ?? "finishing";
  return (
    <Link to={`/runs/${encodeURIComponent(runId)}`} className={styles.card}>
      <span className={styles.cardLabel}>IN FLIGHT</span>
      <span className={styles.cardDetail}>
        {stage} · {formatElapsed(run.data.run.started_at, now)}
      </span>
    </Link>
  );
}

function navClass({ isActive }: { isActive: boolean }): string | undefined {
  return isActive ? `${styles.item} ${styles.active}` : styles.item;
}
