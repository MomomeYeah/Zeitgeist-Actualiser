import type { TemplateOption } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";

import styles from "./TemplateCard.module.css";

/**
 * `all N` plus one chip per template, where N is the library's real size.
 *
 * The handoff names four templates and the repository ships a different
 * set; only `drake` overlaps. Every chip is driven by the loaded manifests,
 * so this reads `all 5` today and stays correct as the library changes.
 *
 * `all N` sends null rather than an explicit list of every id, which is the
 * pipeline's own convention for "the whole library" and is what keeps a run
 * started today from freezing a template list that a manifest added
 * tomorrow would not be in.
 */
export function TemplateCard({
  templates,
  selected,
  onSelect,
}: {
  templates: TemplateOption[];
  selected: string[] | null;
  onSelect: (selected: string[] | null) => void;
}) {
  function toggle(id: string) {
    const held = selected ?? [];
    const next = held.includes(id)
      ? held.filter((other) => other !== id)
      : [...held, id];
    onSelect(next.length === 0 ? null : next);
  }

  return (
    <section className={styles.card}>
      <SectionLabel hint="default: whole library">Templates</SectionLabel>

      <div className={styles.chips}>
        <button
          type="button"
          aria-pressed={selected === null}
          className={selected === null ? styles.chipOn : styles.chip}
          onClick={() => onSelect(null)}
        >
          all {templates.length}
        </button>
        {templates.map((template) => (
          <button
            key={template.id}
            type="button"
            aria-pressed={selected?.includes(template.id) ?? false}
            className={
              (selected?.includes(template.id) ?? false) ? styles.chipOn : styles.chip
            }
            onClick={() => toggle(template.id)}
          >
            {template.id}
          </button>
        ))}
      </div>
    </section>
  );
}
