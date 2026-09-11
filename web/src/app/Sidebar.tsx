import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
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
 * first names a run, so an idle app issues neither. It polls at the same
 * rate as the first, because run detail's stream is the only other thing
 * that refreshes it and the sidebar is on every screen but that one.
 *
 * This is also where the app notices a run starting or ending, wherever
 * someone happens to be looking. The sidebar is the one component mounted
 * on every screen, and `active` is already polled here. When the run it
 * names changes — a queued run starting, or `null` because the run ended
 * — everything under `["runs"]` and `["topics"]` is invalidated: the Runs
 * list and the Topics run strip would otherwise keep saying "running"
 * until a 30s stale time ran out, and the Topics index would never pick up
 * what the run produced while it stayed open.
 *
 * The first answer is not a change. Invalidating on it would refetch every
 * list on the screen a second time on every page load.
 */
function InFlight() {
  const client = useQueryClient();
  const active = useActiveRun();
  const current = active.data?.current;
  const runId = current ?? undefined;
  const run = useRun(runId, { poll: true });
  const now = useNow(runId !== undefined);
  const previous = useRef(current);

  useEffect(() => {
    if (previous.current === current) return;
    const answered = previous.current !== undefined;
    previous.current = current;
    if (!answered) return;
    void client.invalidateQueries({ queryKey: ["runs"] });
    void client.invalidateQueries({ queryKey: ["topics"] });
  }, [current, client]);

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
