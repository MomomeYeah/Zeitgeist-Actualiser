import type { Dossier } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";
import { formatScore } from "@/format";

import styles from "./DossierCards.module.css";

export function DossierCards({
  dossier,
  scoreComponents,
}: {
  dossier: Dossier | null;
  scoreComponents: Record<string, number>;
}) {
  if (dossier === null) {
    // The dormant path and a stale checkpoint. The topic was still ranked,
    // so the page keeps its header and its ranking context and says what is
    // missing rather than blanking out.
    return <p className={styles.absent}>No dossier was written for this topic.</p>;
  }

  const components = Object.entries(scoreComponents)
    .map(([name, value]) => `${name} ${formatScore(value)}`)
    .join(" · ");

  return (
    <div className={styles.grid}>
      <section className={styles.card}>
        <SectionLabel>What happened</SectionLabel>
        <p className={styles.prose}>{dossier.what_happened}</p>
        {(dossier.key_entities ?? []).length > 0 && (
          <ul className={styles.entities}>
            {(dossier.key_entities ?? []).map((entity) => (
              <li key={entity} className={styles.entity}>
                {entity}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.card}>
        <SectionLabel>How the conversation is going</SectionLabel>
        <p className={styles.prose}>{dossier.conversation_summary}</p>
        {components !== "" && (
          <>
            <hr className={styles.rule} />
            <p className={styles.components}>score_components · {components}</p>
          </>
        )}
      </section>
    </div>
  );
}
