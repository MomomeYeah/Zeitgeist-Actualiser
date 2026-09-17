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
          onChange={(event) => onDraft(event.target.value)}
        />
      </div>
      <p className={styles.explanation}>
        {spec.explanation}
        {spec.hint !== undefined && <span className={styles.hint}>{spec.hint}</span>}
      </p>
    </div>
  );
}
