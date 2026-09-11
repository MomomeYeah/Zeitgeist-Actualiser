import type { RunConfig } from "@/api/types";

/**
 * The six tunables a run freezes, as the `overrides` the New run form posts
 * when re-running from a source run's config.
 *
 * Mirrors `RunConfig.as_overrides` on the server (Task 14): keyed by
 * *setting* name, not by this model's field name, because `RunConfig` groups
 * a run's per-run choices and its settings-table tunables under one
 * vocabulary while `Settings` does not (`top_count` here is `topic_count`
 * on `Settings`, `trend_limit` is `bluesky_trend_limit`, and so on). Values
 * are strings because `StartRunBody.overrides` is `Record<string, string>`,
 * the same as any other form field.
 *
 * The four cards (provider, model, platform, meme count) are deliberately
 * absent: those come from form state in `NewRunPage`, seeded from the
 * preset but editable, so a change made while re-running still wins.
 * `bluesky_fetch_concurrency` is absent too, for the same reason it is
 * absent from `as_overrides` — it has no field on `RunConfig` at all, so
 * there is nothing frozen to replay and it keeps resolving from whatever
 * current settings say.
 */
export function frozenTunables(preset: RunConfig): Record<string, string> {
  return {
    bluesky_trend_limit: String(preset.trend_limit),
    bluesky_posts_per_trend: String(preset.posts_per_trend),
    meme_potential_weight: String(preset.meme_potential_weight),
    phrase_min_authors: String(preset.phrase_min_authors),
    distil_char_budget: String(preset.distil_char_budget),
    distil_concurrency: String(preset.distil_concurrency),
  };
}
