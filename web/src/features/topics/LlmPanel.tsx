import { useId, useState } from "react";

import type { GenerateMutation } from "@/api/queries";
import type { TemplateOption, TopicRow } from "@/api/types";

import styles from "./LlmPanel.module.css";

/** HOW MANY. The design's `5` is past `MAX_RENDERS` — "Decisions", 2. */
const COUNTS = [1, 3];
const DEFAULT_COUNT = 3;

/**
 * `picks the templates that suit funny / riffing` — the topic's event
 * sentiment and conversation register, which is what the model chooses
 * by. A topic with no dossier has neither, and the line says so rather
 * than ending on an empty "suit ".
 */
function suits(topic: TopicRow): string {
  const traits = [topic.event_sentiment, topic.conversation_register].filter(
    (trait): trait is string => typeof trait === "string" && trait !== "",
  );
  return traits.length === 0
    ? "picks the templates that suit this topic"
    : `picks the templates that suit ${traits.join(" / ")}`;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/**
 * Ask the LLM: the primary way to make a meme, so it reads solid.
 *
 * The template is optional. **Let the LLM choose** is the default and
 * posts `template_id: null`, which offers the model the whole library;
 * picking a tile narrows it to that one template. The tiles are the loaded
 * library, never the four templates the handoff drew.
 *
 * Real radio inputs, visually hidden, with the row and the tiles as their
 * labels: one choice from a set is what a radio group is, and it gives a
 * keyboard and a screen reader the arrow-key behaviour for free.
 */
export function LlmPanel({
  topic,
  templates,
  generation,
}: {
  topic: TopicRow;
  templates: TemplateOption[];
  generation: GenerateMutation;
}) {
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [count, setCount] = useState(DEFAULT_COUNT);
  const titleId = useId();
  const groupId = useId();
  const countId = useId();
  const radioName = useId();

  return (
    <section className={styles.panel} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.title}>
        Ask the LLM
      </h2>
      <p className={styles.subhead}>
        Writes fresh briefs from the dossier, then renders them. Costs a model call
        each.
      </p>

      <div className={styles.labelRow}>
        <span id={groupId} className={styles.fieldLabel}>
          Template
        </span>
        <span className={styles.optional}>optional</span>
      </div>
      <div role="radiogroup" aria-labelledby={groupId}>
        <label className={templateId === null ? styles.chooseOn : styles.choose}>
          <input
            type="radio"
            className={styles.srOnly}
            name={radioName}
            checked={templateId === null}
            onChange={() => setTemplateId(null)}
          />
          <span className={styles.dot} aria-hidden="true" />
          <span className={styles.chooseText}>
            <span className={styles.chooseTitle}>Let the LLM choose</span>
            <span className={styles.chooseHint}>{suits(topic)}</span>
          </span>
        </label>
        <div className={styles.tiles}>
          {templates.map((template) => (
            <label
              key={template.id}
              className={templateId === template.id ? styles.tileOn : styles.tile}
            >
              <input
                type="radio"
                className={styles.srOnly}
                name={radioName}
                checked={templateId === template.id}
                onChange={() => setTemplateId(template.id)}
              />
              <span className={styles.stripe} aria-hidden="true" />
              <span className={styles.tileText}>
                <span className={styles.tileId}>{template.id}</span>
                <span className={styles.slots}>
                  {plural(template.slots.length, "slot", "slots")}
                </span>
              </span>
            </label>
          ))}
        </div>
      </div>

      <div className={styles.bottom}>
        <div>
          <span id={countId} className={styles.fieldLabel}>
            How many
          </span>
          <div className={styles.pills} role="group" aria-labelledby={countId}>
            {COUNTS.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={count === option}
                className={count === option ? styles.pillOn : styles.pill}
                onClick={() => setCount(option)}
              >
                {option}
              </button>
            ))}
          </div>
        </div>
        <button
          type="button"
          className={styles.generate}
          disabled={generation.isPending}
          onClick={() => generation.mutate({ mode: "llm", template_id: templateId, count })}
        >
          {`Generate ${plural(count, "meme", "memes")}`}
        </button>
      </div>

      {generation.isError && (
        <p role="alert" className={styles.error}>
          {generation.error.detail}
        </p>
      )}
    </section>
  );
}
