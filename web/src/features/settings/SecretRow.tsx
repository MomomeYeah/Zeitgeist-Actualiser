import type { SettingField } from "@/api/types";

import styles from "./SecretRow.module.css";

/**
 * The API key: a control with no current value to show.
 *
 * Not a `SettingRow`, whose whole premise is a draft compared against a
 * held value. The server returns `value: null` for a secret field always,
 * so there is nothing to compare and nothing to prefill — `source` is the
 * only thing that distinguishes a stored key from an unset one.
 */
export function SecretRow({
  field,
  draft,
  onDraft,
  onClear,
}: {
  field: SettingField;
  draft: string | undefined;
  onDraft: (value: string) => void;
  onClear: () => void;
}) {
  const present = field.source === "settings";
  return (
    <div className={styles.row}>
      <div className={styles.head}>
        <label className={styles.key} htmlFor={`setting-${field.key}`}>
          {field.key}
        </label>
        <span className={present ? styles.set : styles.unset}>
          {present ? "SET" : "NOT SET"}
        </span>
        <input
          id={`setting-${field.key}`}
          type="password"
          autoComplete="off"
          className={styles.input}
          placeholder={present ? "replace the stored key" : "paste a key"}
          value={draft ?? ""}
          onChange={(event) => onDraft(event.target.value)}
        />
      </div>
      {present && (
        <button type="button" className={styles.clear} onClick={onClear}>
          Clear
        </button>
      )}
    </div>
  );
}
