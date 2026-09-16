import type { SettingField } from "@/api/types";
import type { FieldSpec } from "@/features/settings/fields";
import { SOURCE_LABELS } from "@/features/settings/fields";

import styles from "./SettingRow.module.css";

/**
 * One tunable: its key, its value, where the value came from, and what it
 * does.
 *
 * The input is uncontrolled-looking but controlled: `draft` is the edited
 * string, falling back to the server's value. Keeping the draft as a string
 * rather than a number is deliberate — the field must be allowed to be
 * empty while someone is retyping it, and `Number("")` is `0`, which would
 * silently rewrite the value the moment the box was cleared.
 *
 * A field the environment supplies is read-only, and says why. A shell
 * `BLUESKY_TREND_LIMIT=10` outranks the settings table — deliberately, as
 * the more explicit act — so Save on such a field wrote a row that changed
 * nothing anybody could see: the value snapped straight back on the reply,
 * with the chip beside it still reading FROM ENV and no account of what had
 * happened. The row was the only thing on the screen that could not do what
 * it appeared to. Refusing the edit and naming the variable is the honest
 * version of the same fact, and it leaves "Reset to .env" working, which is
 * how the stored row gets cleared if an earlier save pinned one.
 */
export function SettingRow({
  field,
  spec,
  draft,
  onDraft,
}: {
  field: SettingField;
  spec: FieldSpec;
  draft: string | undefined;
  onDraft: (value: string) => void;
}) {
  const fromEnvironment = field.source === "environment";
  const variable = field.key.toUpperCase();
  return (
    <div className={styles.row}>
      <div className={styles.head}>
        <label className={styles.key} htmlFor={`setting-${field.key}`}>
          {field.key}
        </label>
        <span className={styles[field.source] ?? ""}>
          {SOURCE_LABELS[field.source]}
        </span>
        <input
          id={`setting-${field.key}`}
          type="number"
          step="any"
          className={styles.input}
          value={draft ?? String(field.value)}
          // `readOnly`, not `disabled`: the value still has to be readable
          // and reachable by keyboard — it is what the next run will
          // actually use, and a disabled input is skipped by the tab order
          // and dimmed out of contrast.
          readOnly={fromEnvironment}
          aria-describedby={fromEnvironment ? `setting-${field.key}-why` : undefined}
          onChange={(event) => onDraft(event.target.value)}
        />
      </div>
      <p className={styles.explanation}>
        {spec.explanation}
        {spec.hint !== undefined && <span className={styles.hint}>{spec.hint}</span>}
      </p>
      {fromEnvironment && (
        <p className={styles.pinned} id={`setting-${field.key}-why`}>
          {variable} is set in this server&rsquo;s environment, which outranks
          this screen. Unset it and restart to edit the value here.
        </p>
      )}
    </div>
  );
}
