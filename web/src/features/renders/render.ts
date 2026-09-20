import type { RenderRecord } from "@/api/types";

/**
 * What to call a render's template.
 *
 * `template_id` is null on a render whose model never chose one — a
 * `generating` row that left the choice open, or a `failed` row whose brief
 * died first. The chip, the alt text, the download's file name and the
 * page's breadcrumb all still need a word, and it has to be the same word
 * in each.
 */
export function templateLabel(record: RenderRecord): string {
  return record.template_id ?? "no template chosen";
}

/** A render's permanent address — the route, and what Copy link copies. */
export function renderPath(record: RenderRecord): string {
  return (
    `/runs/${encodeURIComponent(record.run_id)}` +
    `/renders/${encodeURIComponent(record.id)}`
  );
}
