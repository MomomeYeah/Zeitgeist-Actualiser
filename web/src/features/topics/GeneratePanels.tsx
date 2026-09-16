import type { GenerateMutation } from "@/api/queries";
import type { TemplateOption, TopicRow } from "@/api/types";
import { LlmPanel } from "@/features/topics/LlmPanel";
import { ManualPanel } from "@/features/topics/ManualPanel";

import styles from "./GeneratePanels.module.css";

/**
 * Topic detail's ways to make a meme, side by side at `1fr 340px`.
 *
 * The split is load-bearing, per the handoff: asking the model is the
 * primary action and reads solid; writing it yourself is the deliberate,
 * quieter alternative.
 */
export function GeneratePanels({
  topic,
  templates,
  llm,
  manual,
}: {
  topic: TopicRow;
  templates: TemplateOption[];
  llm: GenerateMutation;
  manual: GenerateMutation;
}) {
  return (
    <div className={styles.panels}>
      <LlmPanel topic={topic} templates={templates} generation={llm} />
      <ManualPanel templates={templates} generation={manual} />
    </div>
  );
}
