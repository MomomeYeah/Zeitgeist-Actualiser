import type { TrendStatus } from "@/api/types";

import styles from "./StatusFilters.module.css";

const ORDER: readonly TrendStatus[] = ["trending", "saturating", "cooling", "stale"];

/**
 * The chip row. Clicking the active chip clears the filter — the design
 * draws no "all" chip, so the active one has to be the way back.
 *
 * `status_totals` counts the whole window rather than the filtered list, so
 * every chip keeps its number while one of them is active.
 */
export function StatusFilters({
  totals,
  active,
  onChange,
}: {
  totals: Record<string, number>;
  active: TrendStatus | undefined;
  onChange: (status: TrendStatus | undefined) => void;
}) {
  return (
    <div className={styles.row}>
      {ORDER.map((status) => (
        <button
          key={status}
          type="button"
          aria-pressed={active === status}
          className={[
            styles.chip,
            active === status ? styles.active : "",
            status === "stale" ? styles.stale : "",
          ]
            .filter(Boolean)
            .join(" ")}
          onClick={() => onChange(active === status ? undefined : status)}
        >
          {status} {totals[status] ?? 0}
        </button>
      ))}
    </div>
  );
}
