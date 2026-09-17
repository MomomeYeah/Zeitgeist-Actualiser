import { useState } from "react";

import type { SettingField } from "@/api/types";
import { useConfigOptions, useSaveSettings, useSettings } from "@/api/queries";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { SectionLabel } from "@/components/SectionLabel";
import { CountCard } from "@/features/config/CountCard";
import { ModelCard } from "@/features/config/ModelCard";
import { PlatformCard } from "@/features/config/PlatformCard";
import { SecretRow } from "@/features/settings/SecretRow";
import { SettingRow } from "@/features/settings/SettingRow";
import { RESETTABLE_KEYS, SECTIONS } from "@/features/settings/fields";

import styles from "./SettingsPage.module.css";

/**
 * Which drafts actually differ from what the server holds, as strings ready
 * to send.
 *
 * The comparison switches on the held type rather than comparing raw
 * strings: `held.get(key) !== draft` on the strings would treat a merely
 * reformatted draft like "0.30" over a stored 0.3 as a change, which would
 * send it and pin a value that was only ever a default — but the same
 * reasoning cannot cover a string field, where `Number("http://...")` is
 * `NaN` and a numeric comparison would decide every edit was unchanged. An
 * empty draft (a box mid-edit, or a field nobody touched) is excluded
 * outright: `Number("")` is `0`, which is exactly why the draft is held as
 * a string in the first place, and this filter only decides what to send —
 * the server is what validates real values.
 */
function changedValues(
  fields: readonly SettingField[],
  drafts: Record<string, string>,
): Record<string, string> {
  const held = new Map(fields.map((field) => [field.key, field.value]));
  return Object.fromEntries(
    Object.entries(drafts).filter(([key, draft]) => {
      if (draft === "") return false;
      const current = held.get(key);
      // A secret reports `null` always, so there is nothing to compare: any
      // non-empty draft is a new key.
      if (current === null || current === undefined) return true;
      if (typeof current === "number") {
        const parsed = Number(draft);
        // Number("http://...") is NaN, which is why this branch is guarded
        // by the held type rather than by whether the draft parses.
        return Number.isFinite(parsed) && current !== parsed;
      }
      return String(current) !== draft;
    }),
  );
}

export function SettingsPage() {
  const settings = useSettings();
  const configOptions = useConfigOptions();
  const save = useSaveSettings();
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  function commit(changed: Record<string, string>) {
    // Only what was actually edited. Sending every field would write a
    // settings row for each one, pinning values that were only ever
    // defaults — and a later change to a field's declared default would
    // then be invisible. `changed` is computed once by the caller and
    // reused for the button's disabled state, so a no-op is never
    // reachable from here anyway; the guard is just belt-and-suspenders.
    if (Object.keys(changed).length === 0) return;
    save.mutate({ values: changed }, { onSuccess: () => setDrafts({}) });
  }

  function reset() {
    // An empty string clears that field's row so the field default applies
    // again. Writing the default back would pin the value. Every settable
    // key but the secret: losing an API key to a button labelled "Reset to
    // defaults" is a trap, and `SecretRow`'s own Clear is the explicit way.
    save.mutate(
      { values: Object.fromEntries(RESETTABLE_KEYS.map((key) => [key, ""])) },
      { onSuccess: () => setDrafts({}) },
    );
  }

  // The secret's Clear cannot go through `drafts`: `changedValues` drops
  // every empty draft before it ever reaches `commit`, so a clear written
  // as "set this key's draft to empty string" would be filtered out and
  // the button would silently do nothing. This calls the mutation
  // directly instead.
  function clearSecret(key: string) {
    save.mutate({ values: { [key]: "" } }, { onSuccess: () => setDrafts({}) });
  }

  function setDraft(key: string, value: string) {
    setDrafts((held) => ({ ...held, [key]: value }));
  }

  return (
    <QueryBoundary query={settings} missing="No settings.">
      {(fields) => (
        <QueryBoundary query={configOptions} missing="No configuration.">
          {(config) => {
            const byKey = new Map(fields.map((field) => [field.key, field]));
            const changed = changedValues(fields, drafts);

            // What a card-driven field currently reads: the draft if
            // someone has touched it this session, otherwise whatever the
            // settings row holds. Seeding from `fields` rather than from
            // `config.defaults` is deliberate — the cards must agree with
            // the database this screen is editing, not with the resolved
            // defaults a fresh run would compute.
            function cardValue(key: string, fallback: string): string {
              const draft = drafts[key];
              if (draft !== undefined) return draft;
              const value = byKey.get(key)?.value;
              return value === null || value === undefined ? fallback : String(value);
            }

            const provider = cardValue("llm_provider", "anthropic");
            const model = cardValue("llm_model", "");
            const platform = cardValue("sources", "");
            const count = Number(cardValue("topic_count", "5"));
            const trendLimit = cardValue("bluesky_trend_limit", "25");

            function chooseProvider(next: string) {
              setDrafts((held) => {
                const updated: Record<string, string> = { ...held, llm_provider: next };
                // The model list is per-provider, so a model carried over
                // from the old one would post `claude-sonnet-5` to ollama
                // and fail on the worker thread with a model nobody chose.
                const available = config.models[next] ?? [];
                if (!available.includes(model)) {
                  updated.llm_model = available[0] ?? "";
                }
                return updated;
              });
            }

            return (
              <div className={styles.page}>
                <header className={styles.header}>
                  <h1 className={styles.title}>Settings</h1>
                  <MetaLine>what every run starts from</MetaLine>
                </header>

                <div className={styles.layout}>
                  <div className={styles.sections}>
                    {SECTIONS.map((section) => (
                      <section key={section.label}>
                        <h2 className={styles.sectionTitle}>{section.label}</h2>
                        <MetaLine>{section.blurb}</MetaLine>

                        <div className={styles.cards}>
                          {section.cards.map((card) => (
                            <section key={card.label} className={styles.card}>
                              <SectionLabel>{card.label}</SectionLabel>
                              {card.fields.map((spec) => {
                                const field = byKey.get(spec.key);
                                // A key the server did not return is a
                                // contract change, not a state: skipping it
                                // beats rendering a row with nothing behind
                                // it.
                                if (field === undefined) return null;
                                return field.secret ? (
                                  <SecretRow
                                    key={spec.key}
                                    field={field}
                                    draft={drafts[spec.key]}
                                    onDraft={(value) => setDraft(spec.key, value)}
                                    onClear={() => clearSecret(spec.key)}
                                  />
                                ) : (
                                  <SettingRow
                                    key={spec.key}
                                    field={field}
                                    spec={spec}
                                    draft={drafts[spec.key]}
                                    onDraft={(value) => setDraft(spec.key, value)}
                                  />
                                );
                              })}
                            </section>
                          ))}

                          {/* The four run-default cards have no `FieldSpec`:
                              they read their option lists from
                              `useConfigOptions` and are seeded from the
                              settings rows above rather than from a card's
                              own component default, so they belong beside
                              the fan-out/ranking/distillation cards rather
                              than inside `SECTIONS`. */}
                          {section.label === "Defaults for new runs" && (
                            <>
                              <ModelCard
                                models={config.models}
                                provider={provider}
                                model={model}
                                keyPresent={config.anthropic_key_present}
                                onProvider={chooseProvider}
                                onModel={(value) => setDraft("llm_model", value)}
                              />
                              <PlatformCard
                                platforms={config.platforms}
                                selected={platform}
                                onSelect={(value) => setDraft("sources", value)}
                              />
                              <CountCard
                                count={count}
                                trendLimit={trendLimit}
                                onCount={(value) =>
                                  setDraft("topic_count", String(value))
                                }
                              />
                            </>
                          )}
                        </div>
                      </section>
                    ))}
                  </div>

                  <aside className={styles.side}>
                    <button
                      type="button"
                      className={styles.save}
                      disabled={save.isPending || Object.keys(changed).length === 0}
                      onClick={() => commit(changed)}
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      className={styles.reset}
                      disabled={save.isPending}
                      onClick={reset}
                    >
                      Reset to defaults
                    </button>
                    <p className={styles.note}>
                      Changes apply to new runs. A run in flight keeps the config
                      it froze.
                    </p>
                    {save.error !== null && (
                      <p className={styles.failure}>{save.error.detail}</p>
                    )}
                  </aside>
                </div>
              </div>
            );
          }}
        </QueryBoundary>
      )}
    </QueryBoundary>
  );
}
