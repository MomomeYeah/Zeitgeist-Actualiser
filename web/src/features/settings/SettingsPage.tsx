import { useState } from "react";

import type { SettingField } from "@/api/types";
import { useSaveSettings, useSettings } from "@/api/queries";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { SectionLabel } from "@/components/SectionLabel";
import { SettingRow } from "@/features/settings/SettingRow";
import { CARDS, SETTING_KEYS } from "@/features/settings/fields";

import styles from "./SettingsPage.module.css";

export function SettingsPage() {
  const settings = useSettings();
  const save = useSaveSettings();
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  function commit(fields: SettingField[]) {
    // Only what was actually edited. Sending all seven would write a
    // settings row for every one of them, pinning six values that were
    // only ever defaults — and a later `.env` edit would then be invisible.
    const held = new Map(fields.map((field) => [field.key, String(field.value)]));
    const changed = Object.fromEntries(
      Object.entries(drafts).filter(([key, value]) => held.get(key) !== value),
    );
    if (Object.keys(changed).length === 0) return;
    save.mutate({ values: changed }, { onSuccess: () => setDrafts({}) });
  }

  function reset() {
    // An empty string clears that field's row so the `.env` fallback
    // applies again. Writing the default back would pin the value.
    save.mutate(
      { values: Object.fromEntries(SETTING_KEYS.map((key) => [key, ""])) },
      { onSuccess: () => setDrafts({}) },
    );
  }

  return (
    <QueryBoundary query={settings} missing="No settings.">
      {(fields) => {
        const byKey = new Map(fields.map((field) => [field.key, field]));
        return (
          <div className={styles.page}>
            <header className={styles.header}>
              <h1 className={styles.title}>Settings</h1>
              <MetaLine>the seven fields a run can be tuned with</MetaLine>
            </header>

            <div className={styles.layout}>
              <div className={styles.cards}>
                {CARDS.map((card) => (
                  <section key={card.label} className={styles.card}>
                    <SectionLabel>{card.label}</SectionLabel>
                    {card.fields.map((spec) => {
                      const field = byKey.get(spec.key);
                      // A key the server did not return is a contract
                      // change, not a state: skipping it beats rendering a
                      // row with nothing behind it.
                      return field === undefined ? null : (
                        <SettingRow
                          key={spec.key}
                          field={field}
                          spec={spec}
                          draft={drafts[spec.key]}
                          onDraft={(value) =>
                            setDrafts((held) => ({ ...held, [spec.key]: value }))
                          }
                        />
                      );
                    })}
                  </section>
                ))}
              </div>

              <aside className={styles.side}>
                <button
                  type="button"
                  className={styles.save}
                  disabled={save.isPending}
                  onClick={() => commit(fields)}
                >
                  Save
                </button>
                <button
                  type="button"
                  className={styles.reset}
                  disabled={save.isPending}
                  onClick={reset}
                >
                  Reset to .env
                </button>
                <p className={styles.note}>
                  Changes apply to new runs. A run in flight keeps the config it
                  froze.
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
  );
}
