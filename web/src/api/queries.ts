/**
 * The query-key factory and all sixteen hooks — six read, four mutations,
 * `useActiveRun`'s poll and `useRunEvents`'s stream — in one module so a
 * key cannot drift from the fetch that uses it.
 *
 * `useActiveRun` and `useRunEvents` are the two hooks that carry live
 * behaviour: the first polls while a run is in flight, and the second opens
 * an SSE stream through the injectable transport in `client.ts`. Every
 * other hook here fires once per mount, like phase 5's read hooks did.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { apiGet, apiSend, openRunEvents, parseLogEvent } from "@/api/client";
import type { ApiError } from "@/api/client";
import type {
  ActiveRuns,
  ConfigOptions,
  LogLine,
  QueuedRun,
  RankedTopic,
  RenderRecord,
  ResumeBody,
  RunActionAck,
  RunDetail,
  RunPage,
  SettingField,
  SettingsUpdate,
  StartRunBody,
  TopicDetail,
  TopicIndex,
  TrendStatus,
} from "@/api/types";

export interface TopicIndexOptions {
  window?: number;
  status?: TrendStatus;
}

export const queryKeys = {
  runs: (limit?: number) => ["runs", { limit }],
  run: (runId: string) => ["runs", runId],
  ranking: (runId: string) => ["runs", runId, "topics"],
  topicDetail: (runId: string, topicId: string) => ["runs", runId, "topics", topicId],
  topicIndex: (options: TopicIndexOptions) => ["topics", options],
  render: (renderId: string) => ["renders", renderId],
  active: () => ["runs", "active"],
  log: (runId: string, verbose: boolean) => ["runs", runId, "log", { verbose }],
  configOptions: () => ["config", "options"],
  settings: () => ["settings"],
};

/** The three rows the design's run strip shows, and the runs list's page. */
export const DEFAULT_RUN_LIMIT = 25;
/** "across the last 6 runs", per the Topics header. */
export const DEFAULT_WINDOW = 6;

export function useRuns(limit: number = DEFAULT_RUN_LIMIT) {
  return useQuery<RunPage, ApiError>({
    queryKey: queryKeys.runs(limit),
    queryFn: () => apiGet<RunPage>("/api/runs", { limit }),
  });
}

export function useRun(runId: string | undefined) {
  return useQuery<RunDetail, ApiError>({
    queryKey: queryKeys.run(runId ?? ""),
    queryFn: () => apiGet<RunDetail>(`/api/runs/${encodeURIComponent(runId ?? "")}`),
    enabled: runId !== undefined,
  });
}

export function useRanking(runId: string | undefined) {
  return useQuery<RankedTopic[], ApiError>({
    queryKey: queryKeys.ranking(runId ?? ""),
    queryFn: () =>
      apiGet<RankedTopic[]>(`/api/runs/${encodeURIComponent(runId ?? "")}/topics`),
    enabled: runId !== undefined,
  });
}

export function useTopicDetail(runId: string | undefined, topicId: string | undefined) {
  return useQuery<TopicDetail, ApiError>({
    queryKey: queryKeys.topicDetail(runId ?? "", topicId ?? ""),
    queryFn: () =>
      apiGet<TopicDetail>(
        `/api/runs/${encodeURIComponent(runId ?? "")}` +
          `/topics/${encodeURIComponent(topicId ?? "")}`,
      ),
    enabled: runId !== undefined && topicId !== undefined,
  });
}

export function useTopicIndex(options: TopicIndexOptions = {}) {
  const window = options.window ?? DEFAULT_WINDOW;
  return useQuery<TopicIndex, ApiError>({
    queryKey: queryKeys.topicIndex({ window, status: options.status }),
    queryFn: () =>
      apiGet<TopicIndex>("/api/topics", { window, status: options.status }),
  });
}

export function useRender(renderId: string | undefined) {
  return useQuery<RenderRecord, ApiError>({
    queryKey: queryKeys.render(renderId ?? ""),
    queryFn: () =>
      apiGet<RenderRecord>(`/api/renders/${encodeURIComponent(renderId ?? "")}`),
    enabled: renderId !== undefined,
  });
}

/** How often the active-run query re-asks while something is running. */
export const ACTIVE_POLL_MS = 2000;
/**
 * The floor between two tick-driven invalidations.
 *
 * The stream ticks every 250ms (`control.POLL_SECONDS`). Refetching run
 * detail four times a second would spend most of a run re-reading rows that
 * change once a stage, so a tick is a hint to refresh rather than an
 * instruction to.
 */
export const TICK_INVALIDATE_MS = 1000;
/** Lines held in the DOM before the oldest are dropped. */
export const MAX_LOG_LINES = 2000;

/**
 * The in-flight run and the queue — the single source of truth for the
 * sidebar card, the run strip, the Runs in-flight card and New run's queue
 * notice.
 *
 * `refetchInterval` is `false` while nothing is running, so an idle app
 * makes no requests at all. A run started from this app invalidates the
 * query on success, and `refetchOnWindowFocus` (left on in `providers.tsx`)
 * covers coming back to a tab after one was started elsewhere.
 */
export function useActiveRun() {
  return useQuery<ActiveRuns, ApiError>({
    queryKey: queryKeys.active(),
    queryFn: () => apiGet<ActiveRuns>("/api/runs/active"),
    refetchInterval: (query) =>
      query.state.data === undefined || query.state.data.current === null
        ? false
        : ACTIVE_POLL_MS,
    staleTime: 0,
  });
}

/**
 * A finished run's log.
 *
 * `verbose` is a server-side filter here, unlike the live log's, because
 * there is no buffer on the client to filter — the lines come from
 * `log_lines` and the endpoint already knows how to narrow them.
 */
export function useRunLog(
  runId: string | undefined,
  verbose: boolean,
  enabled = true,
) {
  return useQuery<LogLine[], ApiError>({
    queryKey: queryKeys.log(runId ?? "", verbose),
    queryFn: () =>
      apiGet<LogLine[]>(`/api/runs/${encodeURIComponent(runId ?? "")}/log`, {
        verbose,
      }),
    enabled: enabled && runId !== undefined,
  });
}

export function useConfigOptions() {
  return useQuery<ConfigOptions, ApiError>({
    queryKey: queryKeys.configOptions(),
    queryFn: () => apiGet<ConfigOptions>("/api/config/options"),
  });
}

export function useSettings() {
  return useQuery<SettingField[], ApiError>({
    queryKey: queryKeys.settings(),
    queryFn: () => apiGet<SettingField[]>("/api/settings"),
  });
}

/**
 * Everything under `["runs", ...]`: the list, every detail, every ranking,
 * and `active`. One invalidation rather than four, because every mutation
 * here can change all of them — a started run is a new row, a new active
 * run, and a page whose counts moved.
 */
function useRunsInvalidator() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["runs"] });
  };
}

export function useStartRun() {
  const invalidate = useRunsInvalidator();
  return useMutation<QueuedRun, ApiError, StartRunBody>({
    mutationFn: (body) => apiSend<QueuedRun>("POST", "/api/runs", body),
    onSuccess: invalidate,
  });
}

export function useResumeRun(runId: string) {
  const invalidate = useRunsInvalidator();
  return useMutation<QueuedRun, ApiError, ResumeBody>({
    mutationFn: (body) =>
      apiSend<QueuedRun>("POST", `/api/runs/${encodeURIComponent(runId)}/resume`, body),
    onSuccess: invalidate,
  });
}

export function useStopRun(runId: string) {
  const invalidate = useRunsInvalidator();
  return useMutation<RunActionAck, ApiError, void>({
    mutationFn: () =>
      apiSend<RunActionAck>("POST", `/api/runs/${encodeURIComponent(runId)}/stop`),
    onSuccess: invalidate,
  });
}

export function useAbortRun(runId: string) {
  const invalidate = useRunsInvalidator();
  return useMutation<RunActionAck, ApiError, void>({
    mutationFn: () =>
      apiSend<RunActionAck>("POST", `/api/runs/${encodeURIComponent(runId)}/abort`),
    onSuccess: invalidate,
  });
}

/**
 * `PUT /api/settings` answers with the same shape as the `GET`, so the
 * reply goes straight into the cache. A refetch instead would be a wasted
 * round trip and a visible flicker on the very chip that just changed.
 *
 * The config options are invalidated rather than written: their `defaults`
 * are the same values resolved again, which the reply does not carry in
 * that shape. Without it New run kept saying "of 25 trends analysed" for a
 * limit just lowered here, until its stale time ran out.
 */
export function useSaveSettings() {
  const client = useQueryClient();
  return useMutation<SettingField[], ApiError, SettingsUpdate>({
    mutationFn: (body) => apiSend<SettingField[]>("PUT", "/api/settings", body),
    onSuccess: (fields) => {
      client.setQueryData(queryKeys.settings(), fields);
      void client.invalidateQueries({ queryKey: queryKeys.configOptions() });
    },
  });
}

/**
 * The run's live log, and the nudge that keeps the rest of the screen
 * current.
 *
 * Lines accumulate in local state rather than in the query cache: they
 * arrive as a stream of appends, and a cache entry rewritten on every frame
 * would invalidate every consumer of it on every frame.
 *
 * Incoming lines are batched to an animation frame. A DEBUG run emits a
 * line per distilled topic from a thread pool, so appending one at a time
 * would re-render the log once per line.
 */
export function useRunEvents(runId: string | undefined, enabled: boolean) {
  const client = useQueryClient();
  const [lines, setLines] = useState<LogLine[]>([]);
  const pending = useRef<LogLine[]>([]);
  const frame = useRef<number | null>(null);
  const lastInvalidated = useRef(0);

  useEffect(() => {
    if (runId === undefined || !enabled) return;
    setLines([]);
    const source = openRunEvents(runId);

    const flush = () => {
      frame.current = null;
      const batch = pending.current;
      pending.current = [];
      if (batch.length === 0) return;
      setLines((held) => {
        const next = [...held, ...batch];
        return next.length > MAX_LOG_LINES
          ? next.slice(next.length - MAX_LOG_LINES)
          : next;
      });
    };

    const onLog = (event: Event) => {
      pending.current = [...pending.current, ...parseLogEvent(eventData(event))];
      if (frame.current === null) {
        frame.current = requestAnimationFrame(flush);
      }
    };

    const onTick = () => {
      const now = Date.now();
      if (now - lastInvalidated.current < TICK_INVALIDATE_MS) return;
      lastInvalidated.current = now;
      void client.invalidateQueries({ queryKey: ["runs"] });
    };

    source.addEventListener("log", onLog);
    source.addEventListener("tick", onTick);
    return () => {
      source.removeEventListener("log", onLog);
      source.removeEventListener("tick", onTick);
      source.close();
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
      pending.current = [];
    };
  }, [runId, enabled, client]);

  return lines;
}

/**
 * An SSE frame's payload.
 *
 * `addEventListener` on a name outside `EventSourceEventMap` is typed with
 * a plain `Event`, so the narrowing is real rather than ceremonial — and it
 * is a narrowing, not an assertion, which is what keeps this out of
 * `client.ts`.
 */
function eventData(event: Event): string {
  return event instanceof MessageEvent && typeof event.data === "string"
    ? event.data
    : "";
}
