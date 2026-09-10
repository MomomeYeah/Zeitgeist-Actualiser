import { Outlet } from "react-router-dom";

import { Sidebar } from "@/app/Sidebar";

import styles from "./AppLayout.module.css";

/**
 * The rail plus the content column.
 *
 * `app-width` (1180px) is the shell's own cap, per the handoff's geometry
 * table; the detail screens narrow themselves to `content-width` (1000px)
 * inside it rather than the shell knowing which routes are detail screens.
 */
export function AppLayout() {
  return (
    <div className={styles.shell}>
      <Sidebar />
      <main className={styles.content}>
        <Outlet />
      </main>
    </div>
  );
}
