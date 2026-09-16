import { useId, useState } from "react";

import type { GenerateMutation } from "@/api/queries";
import type { TemplateOption } from "@/api/types";

import styles from "./ManualPanel.module.css";

/**
 * Write it yourself: straight to the renderer, no model call. Quieter than
 * the LLM panel on purpose — dashed, muted, a ghost button — because it is
 * the deliberate alternative rather than the primary action.
 *
 * One field per slot of the chosen template, named for the slot, read from
 * the manifest rather than hardcoded. Captions are held by slot name across
 * template changes, so looking at another template and coming back loses
 * nothing; only the chosen template's slots are posted, because the server
 * refuses any others.
 *
 * Render stays disabled until every slot has a caption. The server refuses
 * a blank one with a 400 anyway; refusing here saves the round trip.
 * Captions are trimmed on the way out, since leading and trailing spaces
 * are nothing anyone meant to draw.
 */
export function ManualPanel({
  templates,
  generation,
}: {
  templates: TemplateOption[];
  generation: GenerateMutation;
}) {
  const [templateId, setTemplateId] = useState(() => templates[0]?.id ?? "");
  const [captions, setCaptions] = useState<Record<string, string>>({});
  const titleId = useId();

  const slots = templates.find((template) => template.id === templateId)?.slots ?? [];
  const complete =
    slots.length > 0 && slots.every((slot) => (captions[slot] ?? "").trim() !== "");

  function render() {
    generation.mutate({
      mode: "manual",
      template_id: templateId,
      caption_slots: Object.fromEntries(
        slots.map((slot) => [slot, (captions[slot] ?? "").trim()]),
      ),
    });
  }

  return (
    <section className={styles.panel} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.title}>
        Write it yourself
      </h2>
      <p className={styles.subhead}>Straight to the renderer. No model call.</p>

      {templates.length === 0 ? (
        <p className={styles.empty}>The template library is empty.</p>
      ) : (
        <>
          <label className={styles.picker}>
            <span className={styles.srOnly}>Template</span>
            <select
              className={styles.select}
              value={templateId}
              onChange={(event) => setTemplateId(event.target.value)}
            >
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.id}
                </option>
              ))}
            </select>
            <span className={styles.change} aria-hidden="true">
              change ▾
            </span>
          </label>

          <div className={styles.fields}>
            {slots.map((slot) => (
              <label key={slot} className={styles.field}>
                <span className={styles.slotName}>{slot}</span>
                <input
                  type="text"
                  className={styles.input}
                  placeholder="type a caption…"
                  value={captions[slot] ?? ""}
                  onChange={(event) =>
                    setCaptions((held) => ({ ...held, [slot]: event.target.value }))
                  }
                />
              </label>
            ))}
          </div>
        </>
      )}

      <button
        type="button"
        className={styles.render}
        disabled={!complete || generation.isPending}
        onClick={render}
      >
        Render
      </button>

      {generation.isError && (
        <p role="alert" className={styles.error}>
          {generation.error.detail}
        </p>
      )}
    </section>
  );
}
