/**
 * The two sections, the cards within them, and what each field does.
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

export interface SettingSection {
  label: string;
  blurb: string;
  cards: readonly SettingCard[];
}

export const SECTIONS: readonly SettingSection[] = [
  {
    label: "Global",
    blurb: "one value, used by everything",
    cards: [
      {
        label: "Provider",
        fields: [
          {
            key: "anthropic_api_key",
            explanation:
              "Your Anthropic key. Stored in this machine's database and never sent back to the browser — replace it or clear it, but you cannot read it here.",
          },
          {
            key: "ollama_host",
            explanation:
              "Where a local Ollama answers. 127.0.0.1 rather than localhost: IPv6-first resolution of localhost cost over two seconds on the machine this was measured on, close to the model registry's own timeout.",
          },
        ],
      },
      {
        label: "Machine",
        fields: [
          {
            key: "bluesky_fetch_concurrency",
            explanation:
              "Parallel fetches. A property of this machine and its network rather than a choice about a run, which is why it is set once here. A semaphore of zero blocks every fetch forever with no diagnostic, so the floor is one.",
          },
          {
            key: "font_path",
            explanation:
              "A .ttf for the meme text. Empty means the scalable font Pillow ships; set it to something like C:/Windows/Fonts/impact.ttf for the authentic look.",
          },
        ],
      },
    ],
  },
  {
    label: "Defaults for new runs",
    blurb: "what New run starts from · a run can override any of these",
    cards: [
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
    ],
  },
];

/**
 * What Reset clears: every settable key except the secret.
 *
 * The four card-driven keys are listed rather than derived, because they are
 * not `FieldSpec`s — deriving from `SECTIONS` alone would silently exempt
 * them and leave Reset doing three quarters of its job. `anthropic_api_key`
 * is exempt on purpose: losing a key to a button labelled "Reset to
 * defaults" is a trap, and `SecretRow`'s Clear is the explicit way to do it.
 */
export const RESETTABLE_KEYS: readonly string[] = [
  ...SECTIONS.flatMap((section) =>
    section.cards.flatMap((card) =>
      card.fields
        .map((field) => field.key)
        .filter((key) => key !== "anthropic_api_key"),
    ),
  ),
  "llm_provider",
  "llm_model",
  "sources",
  "topic_count",
];

/**
 * What each source label reads on screen.
 *
 * There were four of these once, because a shell variable could outrank the
 * settings table and the table itself could fall back to a declared
 * default. `.env` is gone and nothing outranks the table any more, so a
 * field's value came from a stored row or it did not — two labels, not
 * four.
 */
export const SOURCE_LABELS: Readonly<Record<SettingSource, string>> = {
  settings: "SET HERE",
  default: "DEFAULT",
};
