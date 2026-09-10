/**
 * Typed fixtures — the frontend's `tests/run_factory.py`.
 *
 * Every factory returns a value the generated contract types accept in full,
 * so a response model that gains a required field breaks these rather than
 * the twenty tests that use them. Options are named for what a test wants to
 * vary, never for the wire field, so a rename on the wire touches this file
 * alone.
 */
import type {
  ActiveRuns,
  ConfigOptions,
  Dossier,
  IndexedTopic,
  LogLine,
  QueuedRun,
  RankedTopic,
  RenderRecord,
  RunConfig,
  RunDetail,
  RunError,
  RunPage,
  RunRecordRow,
  RunStatus,
  RunSummary,
  SettingField,
  SettingSource,
  Stage,
  StageRecord,
  StageStatus,
  TopicDetail,
  TopicIndex,
  TopicRow,
  TrendStatus,
} from "@/api/types";

/** Frozen, like `run_factory.FIXED_TIME`: relative dates make flaky tests. */
export const FIXED_START = "2026-08-29T09:00:00Z";
export const FIXED_END = "2026-08-29T09:06:41Z";

export function makeRunConfig(overrides: Partial<RunConfig> = {}): RunConfig {
  return {
    sources: ["bluesky"],
    trend_limit: 25,
    posts_per_trend: 30,
    top_count: 5,
    meme_potential_weight: 0.3,
    phrase_min_authors: 3,
    distil_char_budget: 6000,
    distil_concurrency: 4,
    llm_provider: "anthropic",
    llm_model: "claude-opus-5",
    template_ids: null,
    ...overrides,
  };
}

export function makeRunRecord(
  options: {
    runId?: string;
    status?: RunStatus;
    finishedAt?: string | null;
    error?: RunError | null;
    trendsFound?: number | null;
    topicsKept?: number | null;
    phrasesFound?: number | null;
    config?: Partial<RunConfig>;
  } = {},
): RunRecordRow {
  return {
    run_id: options.runId ?? "20260829T090000Z",
    status: options.status ?? "ok",
    started_at: FIXED_START,
    finished_at: options.finishedAt === undefined ? FIXED_END : options.finishedAt,
    config: makeRunConfig(options.config),
    error: options.error ?? null,
    item_count: 750,
    trends_found: options.trendsFound === undefined ? 25 : options.trendsFound,
    topics_kept: options.topicsKept === undefined ? 5 : options.topicsKept,
    phrases_found: options.phrasesFound === undefined ? 18 : options.phrasesFound,
  };
}

export function makeRunSummary(
  options: {
    runId?: string;
    status?: RunStatus;
    error?: RunError | null;
    labels?: string[];
    renderIds?: string[];
    finishedAt?: string | null;
    trendsFound?: number | null;
    topicsKept?: number | null;
    config?: Partial<RunConfig>;
  } = {},
): RunSummary {
  return {
    run: makeRunRecord(options),
    topic_labels: options.labels ?? ["Airport cat", "Stadium rat"],
    render_ids: options.renderIds ?? ["render-1", "render-2"],
  };
}

export function makeRunPage(
  runs: RunSummary[] = [makeRunSummary()],
  nextCursor: string | null = null,
): RunPage {
  return { runs, next_cursor: nextCursor };
}

export function makeStageRecord(
  options: {
    stage?: Stage;
    status?: StageStatus;
    startedAt?: string | null;
    finishedAt?: string | null;
    payloadBytes?: number | null;
    summary?: string;
  } = {},
): StageRecord {
  return {
    stage: options.stage ?? "ingest",
    status: options.status ?? "ok",
    started_at: options.startedAt === undefined ? FIXED_START : options.startedAt,
    finished_at:
      options.finishedAt === undefined ? "2026-08-29T09:01:12Z" : options.finishedAt,
    payload_bytes:
      options.payloadBytes === undefined ? 1_363_148 : options.payloadBytes,
    summary: options.summary ?? "25 trends, 750 posts",
  };
}

export function makeRunDetail(
  options: {
    runId?: string;
    status?: RunStatus;
    error?: RunError | null;
    stages?: StageRecord[];
    resumeStage?: Stage | null;
    config?: Partial<RunConfig>;
  } = {},
): RunDetail {
  return {
    run: makeRunRecord(options),
    stages: options.stages ?? [
      makeStageRecord({ stage: "ingest" }),
      makeStageRecord({ stage: "analyse", summary: "25 distilled" }),
      makeStageRecord({ stage: "evaluate", summary: "5 kept of 25" }),
      makeStageRecord({ stage: "generate", summary: "5 of 5 rendered" }),
    ],
    resume_stage: options.resumeStage === undefined ? "generate" : options.resumeStage,
  };
}

export function makeTopicRow(
  options: {
    runId?: string;
    topicId?: string;
    label?: string;
    trendStatus?: TrendStatus;
    sentiment?: string | null;
    register?: string | null;
    memePotential?: number | null;
    trendScore?: number;
    finalScore?: number;
    finalRank?: number;
    postCount?: number;
    topPhrase?: string | null;
    topPhraseAuthors?: number | null;
  } = {},
): TopicRow {
  const label = options.label ?? "Airport cat";
  return {
    run_id: options.runId ?? "20260829T090000Z",
    topic_id: options.topicId ?? "topic-1",
    label,
    label_slug: label.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
    trend_status: options.trendStatus ?? "trending",
    event_sentiment: options.sentiment === undefined ? "funny" : options.sentiment,
    conversation_register: options.register === undefined ? "riffing" : options.register,
    meme_potential: options.memePotential === undefined ? 0.86 : options.memePotential,
    trend_score: options.trendScore ?? 0.91,
    final_score: options.finalScore ?? 0.895,
    final_rank: options.finalRank ?? 1,
    post_count: options.postCount ?? 412,
    top_phrase: options.topPhrase === undefined ? "absolute unit" : options.topPhrase,
    top_phrase_authors:
      options.topPhraseAuthors === undefined ? 31 : options.topPhraseAuthors,
  };
}

export function makeRankedTopic(
  options: Parameters<typeof makeTopicRow>[0] & {
    renderCount?: number;
    aboveCut?: boolean;
  } = {},
): RankedTopic {
  return {
    topic: makeTopicRow(options),
    render_count: options.renderCount ?? 1,
    above_cut: options.aboveCut ?? true,
  };
}

export function makeDossier(overrides: Partial<Dossier> = {}): Dossier {
  return {
    what_happened: "A cat got loose in an airport terminal and stopped boarding.",
    key_entities: ["the cat", "the terminal", "ground staff"],
    conversation_summary: "Everyone is writing the cat's incident report for it.",
    conversation_register: "riffing",
    secondary_registers: ["delight"],
    event_sentiment: "funny",
    meme_potential: 0.86,
    recurring_phrases: [
      { text: "absolute unit", occurrences: 48, distinct_authors: 31 },
      { text: "ground control", occurrences: 22, distinct_authors: 14 },
    ],
    ...overrides,
  };
}

export function makeRenderRecord(
  options: {
    id?: string;
    runId?: string;
    topicId?: string;
    templateId?: string;
    rationale?: string | null;
    status?: RenderRecord["status"];
    error?: string | null;
    captionSlots?: Record<string, string>;
    createdAt?: string;
  } = {},
): RenderRecord {
  const rationale = options.rationale;
  return {
    id: options.id ?? "render-1",
    run_id: options.runId ?? "20260829T090000Z",
    topic_id: options.topicId ?? "topic-1",
    template_id: options.templateId ?? "drake",
    caption_slots: options.captionSlots ?? {
      rejected: "Filing an incident report",
      preferred: "Becoming the incident",
    },
    origin:
      rationale === null
        ? { provenance: "manual" }
        : { provenance: "auto", rationale: rationale ?? "Two panels, one reversal." },
    status: options.status ?? "ready",
    error: options.error ?? null,
    created_at: options.createdAt ?? FIXED_END,
  };
}

export function makeTopicDetail(
  options: Parameters<typeof makeTopicRow>[0] & {
    dossier?: Dossier | null;
    scoreComponents?: Record<string, number>;
    replies?: TopicDetail["replies"];
    renders?: RenderRecord[];
    runCount?: number;
    firstSeenRunId?: string | null;
  } = {},
): TopicDetail {
  return {
    topic: makeTopicRow(options),
    dossier: options.dossier === undefined ? makeDossier() : options.dossier,
    score_components: options.scoreComponents ?? { bluesky: 0.91, corroboration: 1.0 },
    replies: options.replies ?? [
      { text: "ground control to major tom", like_count: 1412, created_at: FIXED_END },
      { text: "he has a boarding pass and everything", like_count: 903, created_at: FIXED_END },
    ],
    renders: options.renders ?? [makeRenderRecord()],
    recurrence: {
      run_count: options.runCount ?? 3,
      first_seen_run_id:
        options.firstSeenRunId === undefined ? "20260826T090000Z" : options.firstSeenRunId,
    },
  };
}

export function makeIndexedTopic(
  options: Parameters<typeof makeTopicRow>[0] & {
    runCount?: number;
    renderCount?: number;
  } = {},
): IndexedTopic {
  return {
    topic: makeTopicRow(options),
    run_count: options.runCount ?? 3,
    render_count: options.renderCount ?? 2,
  };
}

export function makeTopicIndex(
  options: {
    topics?: IndexedTopic[];
    statusTotals?: Record<string, number>;
    sentimentTotals?: Record<string, number>;
    previousSentimentTotals?: Record<string, number>;
  } = {},
): TopicIndex {
  return {
    topics: options.topics ?? [makeIndexedTopic()],
    status_totals: options.statusTotals ?? {
      trending: 9,
      saturating: 6,
      cooling: 4,
      stale: 31,
    },
    sentiment_totals: options.sentimentTotals ?? {
      funny: 9,
      cute: 5,
      schadenfreude: 3,
      mundane: 2,
    },
    previous_sentiment_totals: options.previousSentimentTotals ?? {
      funny: 7,
      cute: 6,
      schadenfreude: 3,
      mundane: 3,
    },
  };
}

export function makeActiveRuns(
  options: { current?: string | null; queued?: string[] } = {},
): ActiveRuns {
  return {
    current: options.current === undefined ? null : options.current,
    queued: options.queued ?? [],
  };
}

export function makeQueuedRun(
  options: { runId?: string; position?: number } = {},
): QueuedRun {
  return {
    run_id: options.runId ?? "20260829T140200Z",
    position: options.position ?? 0,
  };
}

export function makeLogLine(
  options: {
    seq?: number;
    level?: string;
    logger?: string;
    message?: string;
    loggedAt?: string;
  } = {},
): LogLine {
  return {
    seq: options.seq ?? 1,
    logged_at: options.loggedAt ?? FIXED_START,
    level: options.level ?? "INFO",
    logger: options.logger ?? "zeitgeist.pipeline",
    message: options.message ?? "Fetched 25 trends",
  };
}

export function makeConfigOptions(
  options: {
    models?: Record<string, string[]>;
    platforms?: ConfigOptions["platforms"];
    templates?: ConfigOptions["templates"];
    defaults?: Record<string, string>;
    anthropicKeyPresent?: boolean;
  } = {},
): ConfigOptions {
  return {
    models: options.models ?? {
      anthropic: ["claude-opus-5", "claude-sonnet-5"],
      ollama: ["qwen3.5:latest"],
    },
    platforms: options.platforms ?? [
      { name: "lemmy", enabled: false },
      { name: "wikipedia", enabled: false },
      { name: "bluesky", enabled: true },
    ],
    templates: options.templates ?? [
      { id: "drake", slots: ["rejected", "preferred"] },
      { id: "two_buttons", slots: ["left", "right", "sweating"] },
    ],
    defaults: options.defaults ?? {
      bluesky_fetch_concurrency: "8",
      bluesky_posts_per_trend: "10",
      bluesky_trend_limit: "25",
      distil_char_budget: "24000",
      distil_concurrency: "4",
      llm_model: "claude-sonnet-5",
      llm_provider: "anthropic",
      meme_potential_weight: "0.3",
      phrase_min_authors: "3",
      // The Python repr, because `options.py` builds every default with
      // `str(...)` and `Settings.sources` is a list. The New run screen
      // deliberately ignores this key; the fixture carries it so a screen
      // that started reading it would be tested against what the server
      // really sends.
      sources: "['bluesky']",
      topic_count: "5",
    },
    anthropic_key_present: options.anthropicKeyPresent ?? true,
  };
}

export function makeSettingField(
  options: { key?: string; value?: number; source?: SettingSource } = {},
): SettingField {
  return {
    key: options.key ?? "phrase_min_authors",
    value: options.value ?? 3,
    source: options.source ?? "default",
  };
}

/** All seven, in the order `GET /api/settings` returns them: sorted by key. */
export function makeSettingFields(
  overrides: Partial<Record<string, Partial<SettingField>>> = {},
): SettingField[] {
  const base: SettingField[] = [
    { key: "bluesky_fetch_concurrency", value: 8, source: "default" },
    { key: "bluesky_posts_per_trend", value: 10, source: "default" },
    { key: "bluesky_trend_limit", value: 25, source: "default" },
    { key: "distil_char_budget", value: 24000, source: "default" },
    { key: "distil_concurrency", value: 4, source: "default" },
    { key: "meme_potential_weight", value: 0.3, source: "default" },
    { key: "phrase_min_authors", value: 3, source: "default" },
  ];
  return base.map((field) => ({ ...field, ...(overrides[field.key] ?? {}) }));
}
