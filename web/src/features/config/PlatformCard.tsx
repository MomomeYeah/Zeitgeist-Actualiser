import type { PlatformOption } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";

import styles from "./PlatformCard.module.css";

/**
 * 3-up radio cards, `exactly one`, and the dormant platforms shown but
 * unpickable.
 *
 * Lemmy and Wikipedia are in `KNOWN_SOURCES` and have code and tests, but
 * nothing consumes a flat item list and `Settings` rejects them. Hiding
 * them would leave someone wondering why a platform they know exists is not
 * offered; disabling them says which and why.
 */
export function PlatformCard({
  platforms,
  selected,
  onSelect,
}: {
  platforms: PlatformOption[];
  selected: string;
  onSelect: (name: string) => void;
}) {
  return (
    <section className={styles.card}>
      <SectionLabel hint="exactly one">Platform</SectionLabel>

      <div className={styles.grid} role="radiogroup" aria-label="Platform">
        {platforms.map((platform) => (
          <button
            key={platform.name}
            type="button"
            role="radio"
            disabled={!platform.enabled}
            aria-checked={platform.name === selected}
            className={[
              styles.option,
              platform.enabled ? "" : styles.dormant,
              platform.name === selected ? styles.chosen : "",
            ]
              .filter(Boolean)
              .join(" ")}
            onClick={() => onSelect(platform.name)}
          >
            <span className={styles.name}>{platform.name}</span>
            <span className={styles.sublabel}>
              {platform.enabled ? "clusters its own trends" : "dormant · no clustering"}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
