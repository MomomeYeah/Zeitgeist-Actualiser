import { SectionLabel } from "@/components/SectionLabel";

import styles from "./ModelCard.module.css";

/**
 * Provider pills over a per-provider model list.
 *
 * The model rows carry no `default` / `slower` / `cheap` annotation. The
 * contract returns bare ids and the registry holds no annotation data, and
 * for ollama it could not: that list is whatever is pulled on this machine.
 * A hardcoded editorial claim that nothing verifies would be worse than the
 * blank. See the phase 6 plan, "Decisions", 3.
 */
export function ModelCard({
  models,
  provider,
  model,
  keyPresent,
  onProvider,
  onModel,
}: {
  models: Record<string, string[]>;
  provider: string;
  model: string;
  keyPresent: boolean;
  onProvider: (provider: string) => void;
  onModel: (model: string) => void;
}) {
  const available = models[provider] ?? [];

  return (
    <section className={styles.card}>
      <SectionLabel>Model</SectionLabel>

      <div className={styles.pills}>
        {Object.keys(models).map((name) => (
          <button
            key={name}
            type="button"
            aria-pressed={name === provider}
            className={name === provider ? styles.pillOn : styles.pill}
            onClick={() => onProvider(name)}
          >
            {name}
          </button>
        ))}
      </div>

      {provider === "anthropic" && (
        <p className={keyPresent ? styles.keyLine : styles.keyMissing}>
          {keyPresent
            ? "key present · ANTHROPIC_API_KEY"
            : "ANTHROPIC_API_KEY is not set · this run would fail"}
        </p>
      )}

      <div className={styles.models} role="radiogroup" aria-label="Model">
        {available.length === 0 ? (
          // Ollama's list comes from `/api/tags` on the configured host and
          // is empty when the daemon is not running. Saying so beats an
          // empty box that looks like a loading state.
          <p className={styles.none}>
            No models found. Is Ollama running on the configured host?
          </p>
        ) : (
          available.map((id) => (
            <button
              key={id}
              type="button"
              role="radio"
              aria-checked={id === model}
              className={id === model ? styles.modelOn : styles.model}
              onClick={() => onModel(id)}
            >
              {id}
            </button>
          ))
        )}
      </div>
    </section>
  );
}
