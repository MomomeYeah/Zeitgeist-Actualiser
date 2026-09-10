import { useState } from "react";

import type { SettingField } from "@/api/types";
import { useSaveSettings, useSettings } from "@/api/queries";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { SectionLabel } from "@/components/SectionLabel";
import { SettingRow } from "@/features/settings/SettingRow";
import { CARDS, SETTING_KEYS } from "@/features/settings/fields";

import styles from "./SettingsPage.module.css";

/**
 * Which drafts actually differ from what the server holds, as strings ready
 * to send.
 *
 * The comparison is numeric, not textual: `held.get(key) !== value` on the
 * raw strings — what the plan originally specified — treats a merely
 * reformatted draft like "0.30" over a stored 0.3 as a change, which would
 * send it and pin a value that was only ever a default. An empty draft (a
 * box mid-edit) and a non-numeric one are excluded rather than compared:
 * `Number("")` is `0`, which is exactly why the draft is held as a string
 * in the first place, and this filter only decides what to send — the
 * server is what validates real values.
 */
function changedValues(
  fields: readonly SettingField[],
  drafts: Record<string, string>,
): Record<string, string> {
  const held = new Map(fields.map((field) => [field.key, field.value]));
  return Object.fromEntries(
    Object.entries(drafts).filter(([key, draft]) => {
      if (draft === "") return false;
      const parsed = Number(draft);
      return Number.isFinite(parsed) && held.get(key) !== parsed;
    }),
  );
}

export function SettingsPage() {
  const settings = useSettings();
  const save = useSaveSettings();
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  function commit(changed: Record<string, string>) {
    // Only what was actually edited. Sending all seven would write a
    // settings row for every one of them, pinning six values that were
    // only ever defaults — and a later `.env` edit would then be invisible.
    // `changed` is computed once by the caller and reused for the button's
    // disabled state, so a no-op is never reachable from here anyway; the
    // guard is just belt-and-suspenders.
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
        const changed = changedValues(fields, drafts);
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
