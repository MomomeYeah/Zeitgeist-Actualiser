/**
 * The three cards, the seven fields, and what each one does.
 *
 * The explanations are lifted from the comments already in `config.py`,
 * which explain every one of these better than new copy would — and which
 * a reader who goes looking will find saying the same thing.
 *
 * Keys are the real ones. The spec's card grouping names `trend_limit` and
 * `posts_per_trend`; the writable keys are `bluesky_trend_limit` and
 * `bluesky_posts_per_trend`, and this screen's whole job is telling you
 * which layer supplied which key. See the phase 6 plan, "Decisions", 4.
 */
import type { SettingSource } from "@/api/types";

export interface FieldSpec {
  key: string;
  explanation: string;
  /** A constraint that is not a preference. Only one field has one. */
  hint?: string;
}

export interface SettingCard {
  label: string;
  fields: readonly FieldSpec[];
}

export const CARDS: readonly SettingCard[] = [
  {
    label: "Fan-out",
    fields: [
      {
        key: "bluesky_trend_limit",
        explanation:
          "Trends fetched per run. Not a tuning parameter above 25 — the endpoint refuses it.",
        hint: "max 25 · API ceiling",
      },
      {
        key: "bluesky_posts_per_trend",
        explanation:
          "Posts read per trend. With the trend limit, this is the real fan-out budget — one number could not express trends-by-posts.",
      },
      {
        key: "bluesky_fetch_concurrency",
        explanation:
          "Parallel fetches. A semaphore of zero blocks every fetch forever with no diagnostic, so the floor is one.",
      },
    ],
  },
  {
    label: "Ranking",
    fields: [
      {
        key: "meme_potential_weight",
        explanation:
          "Share of the ranking given to the dossier's meme potential, the rest going to trend score. Raise it to favour what will actually make a meme over what is merely loud.",
      },
      {
        key: "phrase_min_authors",
        explanation:
          "Distinct accounts a phrase needs before it counts as recurring. Below this, a repeated phrase is one person or a small ring, not a zeitgeist.",
      },
    ],
  },
  {
    label: "Distillation",
    fields: [
      {
        key: "distil_char_budget",
        explanation:
          "Reply characters sent per distillation call. A single trend can yield six hundred replies, and a 32k-context local model truncates silently well before that.",
      },
      {
        key: "distil_concurrency",
        explanation:
          "Parallel distillation calls. Local Ollama serialises on one GPU, so one or two is right there; a hosted provider benefits from more.",
      },
    ],
  },
];

/**
 * Four, though the design drew three.
 *
 * A shell variable outranks the settings table, so `environment` is a real
 * answer — and it is the one state where Save cannot change what the next
 * run actually uses. See the phase 6 plan, "Decisions", 5.
 */
export const SOURCE_LABELS: Readonly<Record<SettingSource, string>> = {
  settings: "SET HERE",
  environment: "FROM ENV",
  dotenv: "FROM .env",
  default: "DEFAULT",
};

/** Every writable key, in the order the cards draw them. */
export const SETTING_KEYS: readonly string[] = CARDS.flatMap((card) =>
  card.fields.map((field) => field.key),
);
