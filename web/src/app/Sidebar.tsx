import { NavLink } from "react-router-dom";

import styles from "./Sidebar.module.css";

/**
 * 180px, one step darker than the page, two destinations.
 *
 * Topics and Runs, in that order, per the handoff. The spec merges the
 * landing dashboard and the topics index into `/`, so those two are the
 * whole nav in this phase; phase 6 adds Settings beneath them, and the
 * in-flight card that pins to the bottom via `margin-top: auto`.
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
      </ul>
    </nav>
  );
}

function navClass({ isActive }: { isActive: boolean }): string | undefined {
  return isActive ? `${styles.item} ${styles.active}` : styles.item;
}
