import type { Phrase } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";

import styles from "./PhraseCard.module.css";

/**
 * 15px, 13px, then 12px for everything after — the design's three steps.
 *
 * No explicit return type: under `noUncheckedIndexedAccess`, a CSS module's
 * properties type as `string | undefined`, same as `StatusPill`'s `tone`.
 */
function sizeClass(index: number) {
  if (index === 0) return styles.first;
  if (index === 1) return styles.second;
  return styles.rest;
}

export function PhraseCard({
  phrases,
  minAuthors,
}: {
  phrases: Phrase[];
  /**
   * The run's own frozen `phrase_min_authors`, from `RunDetail`.
   * `TopicDetail` does not carry the config, and the number of phrases that
   * fell *below* the threshold is nowhere in the contract — so the footer
   * names the threshold rather than claiming a count of what it removed.
   */
  minAuthors: number | undefined;
}) {
  return (
    <section className={styles.card}>
      <SectionLabel>Recurring phrases</SectionLabel>
      <ul className={styles.list}>
        {phrases.map((phrase, index) => (
          <li key={phrase.text}>
            <span className={`${styles.phrase} ${sizeClass(index)}`}>{phrase.text}</span>
            <span className={styles.meta}>
              {phrase.occurrences}× · {phrase.distinct_authors} authors
            </span>
          </li>
        ))}
      </ul>
      {minAuthors !== undefined && (
        <p className={styles.footer}>filtered at phrase_min_authors={minAuthors}</p>
      )}
    </section>
  );
}
