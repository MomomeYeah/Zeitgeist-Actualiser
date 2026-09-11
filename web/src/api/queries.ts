/**
 * The query-key factory and every hook the app fetches or mutates through,
 * in one module so a key cannot drift from the fetch that uses it.
 *
 * `useActiveRun` and `useRunEvents` are the two hooks that carry live
 * behaviour: the first polls while a run is in flight, and the second opens
 * an SSE stream through the injectable transport in `client.ts`. `useRun`
 * polls too, but only when a caller showing the run in flight asks it to
 * (`poll`). Every other hook here fires once per mount, like phase 5's read
 * hooks did.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { ApiError, apiDelete, apiGet, apiSend, openRunEvents, parseLogEvent } from "@/api/client";
import type {
  ActiveRuns,
  ConfigOptions,
  GenerationRequest,
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

/**
 * One run's detail.
 *
 * `poll` is for the surfaces that show the run in flight away from its own
 * page — the sidebar card and the Runs list's pinned card. Run detail keeps
 * itself current from its stream's ticks, but no other screen opens one, so
 * without a poll of their own those cards froze at the stage they first
 * loaded: `useActiveRun`'s poll refreshes `["runs", "active"]`, which says
 * *which* run is in flight and nothing about how far it has got. Same
 * interval as that poll, because the two answer halves of one question.
 */
export function useRun(runId: string | undefined, options: { poll?: boolean } = {}) {
  return useQuery<RunDetail, ApiError>({
    queryKey: queryKeys.run(runId ?? ""),
    queryFn: () => apiGet<RunDetail>(`/api/runs/${encodeURIComponent(runId ?? "")}`),
    enabled: runId !== undefined,
    refetchInterval: options.poll === true ? ACTIVE_POLL_MS : false,
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

/** How often topic detail re-asks while one of its renders is generating. */
export const GENERATION_POLL_MS = 1500;

function generatingCount(detail: TopicDetail | undefined): number {
  return detail?.renders.filter((render) => render.status === "generating").length ?? 0;
}

/**
 * Everything that counts renders: the runs list's thumbnails, every run's
 * ranking, and the topics index's meme counts. Each counts ready renders
 * only, so each is stale the moment a render becomes ready or is deleted.
 *
 * `["runs"]` also covers the topic detail on screen, which refetches once
 * more. That is one request, and it is the page confirming what it drew.
 */
function invalidateRenderViews(client: QueryClient) {
  void client.invalidateQueries({ queryKey: ["runs"] });
  void client.invalidateQueries({ queryKey: ["topics"] });
}

/**
 * One topic's dossier and renders.
 *
 * Polls while any render is `generating`, and only then — a settled topic
 * makes one request, like every other read hook. A render finishing is the
 * only thing on this screen that changes on its own.
 *
 * When the number still generating drops, one of them became ready or
 * failed, so the counts other screens hold are refreshed. Watching the
 * count rather than each row keeps this to one comparison per render of
 * the hook.
 */
export function useTopicDetail(runId: string | undefined, topicId: string | undefined) {
  const client = useQueryClient();
  const query = useQuery<TopicDetail, ApiError>({
    queryKey: queryKeys.topicDetail(runId ?? "", topicId ?? ""),
    queryFn: () =>
      apiGet<TopicDetail>(
        `/api/runs/${encodeURIComponent(runId ?? "")}` +
          `/topics/${encodeURIComponent(topicId ?? "")}`,
      ),
    enabled: runId !== undefined && topicId !== undefined,
    refetchInterval: (current) =>
      generatingCount(current.state.data) > 0 ? GENERATION_POLL_MS : false,
  });

  const generating = generatingCount(query.data);
  const previous = useRef(generating);
  useEffect(() => {
    if (generating < previous.current) invalidateRenderViews(client);
    previous.current = generating;
  }, [generating, client]);

  return query;
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
 * Post one of topic detail's two panels, or the below-the-cut link.
 *
 * The reply's rows — already `generating`, with real ids — go straight into
 * the topic's cached detail rather than waiting for a refetch. TanStack
 * awaits `onSuccess` before the mutation stops being pending, and the
 * page draws placeholders from the pending request's `variables`, so the
 * placeholders give way to the real rows with nothing in between.
 *
 * An in-flight fetch of the detail is cancelled first. It was sent before
 * these rows existed; landing after the write, it would put back a detail
 * without them, and with nothing generating in it the poll that would
 * have found them again would stop.
 *
 * Only cancels a fetch already in flight, not one that already landed: a
 * poll, a window-focus refetch, or another render's "finished" invalidation
 * can read the rows this POST just committed and have its reply land first,
 * so appended ids already present in the cache are skipped rather than
 * drawn a second time.
 *
 * Nothing else is invalidated. A generating row is counted nowhere —
 * every count is ready renders only — so the counts change when a render
 * finishes, which `useTopicDetail` watches for.
 */
export function useGenerateRenders(runId: string, topicId: string) {
  const client = useQueryClient();
  return useMutation<RenderRecord[], ApiError, GenerationRequest>({
    mutationFn: (body) =>
      apiSend<RenderRecord[]>(
        "POST",
        `/api/runs/${encodeURIComponent(runId)}/topics/${encodeURIComponent(topicId)}/renders`,
        body,
      ),
    onSuccess: async (created) => {
      const key = queryKeys.topicDetail(runId, topicId);
      await client.cancelQueries({ queryKey: key, exact: true });
      client.setQueryData<TopicDetail>(key, (held) => {
        if (held === undefined) return held;
        const ids = new Set(created.map((render) => render.id));
        return {
          ...held,
          renders: [...held.renders.filter((row) => !ids.has(row.id)), ...created],
        };
      });
    },
  });
}

/** What a panel is handed: one generate mutation, pending state and all. */
export type GenerateMutation = ReturnType<typeof useGenerateRenders>;

/**
 * Delete a render — the row, the PNG and the thumbnail, server-side.
 *
 * A 404 counts as done. The end state asked for is "no such render", which
 * is what the server reports, and a render deleted in another tab must
 * still leave this one rather than sit there with an error nobody can act
 * on.
 *
 * The row leaves the cached detail at once: "the tile disappearing is the
 * confirmation", per the handoff, and a round trip before it went would
 * read as the click not having worked. Then everything that counts renders
 * is refreshed, because each of them just lost one.
 */
export function useDeleteRender() {
  const client = useQueryClient();
  return useMutation<void, ApiError, RenderRecord>({
    mutationFn: async (render) => {
      try {
        await apiDelete(`/api/renders/${encodeURIComponent(render.id)}`);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return;
        throw error;
      }
    },
    onSuccess: async (_, render) => {
      const key = queryKeys.topicDetail(render.run_id, render.topic_id);
      await client.cancelQueries({ queryKey: key, exact: true });
      client.setQueryData<TopicDetail>(key, (held) =>
        held === undefined
          ? held
          : { ...held, renders: held.renders.filter((row) => row.id !== render.id) },
      );
      invalidateRenderViews(client);
      // Marked stale without a refetch: the full-size view is navigating
      // away on success, and a fetch of a page nobody is looking at would
      // be wasted. Without this, the app's 30s staleTime let pressing Back
      // show the deleted render from cache.
      void client.invalidateQueries({ queryKey: queryKeys.render(render.id), refetchType: "none" });
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
 *
 * A line at or below the highest `seq` already taken is dropped. The server
 * sends no `id:` lines, so an `EventSource` that reconnects mid-run starts
 * the server's generator again at `since(0)` and gets the whole buffer a
 * second time; appended as it came, that doubled the log and repeated the
 * `seq` each row is keyed by. `seq` is the handler's total order over one
 * run's lines, so it is the right thing to deduplicate on.
 *
 * The tick throttle has a trailing edge as well as a leading one. The tick
 * after a run's final status write usually lands inside the window the
 * previous one opened, and a leading-edge-only throttle dropped it — so the
 * page stayed live, "Stopping…" and a counting clock, until the stream
 * reconnected about three seconds later. A throttled tick now leaves one
 * refresh for the end of its window, and a burst of them leaves only that
 * one.
 */
export function useRunEvents(runId: string | undefined, enabled: boolean) {
  const client = useQueryClient();
  const [lines, setLines] = useState<LogLine[]>([]);
  const pending = useRef<LogLine[]>([]);
  const frame = useRef<number | null>(null);
  const lastInvalidated = useRef(0);
  const trailing = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Negative infinity rather than 0: nothing has been taken yet, so no
  // `seq` — whatever the server starts numbering at — is a replay.
  const highestSeq = useRef(Number.NEGATIVE_INFINITY);

  useEffect(() => {
    if (runId === undefined || !enabled) return;
    setLines([]);
    // Reset with the lines they describe: a resumed run's new stream is a
    // new buffer, and its numbering is checked against nothing held.
    highestSeq.current = Number.NEGATIVE_INFINITY;
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
      const fresh = parseLogEvent(eventData(event)).filter(
        (line) => line.seq > highestSeq.current,
      );
      if (fresh.length === 0) return;
      for (const line of fresh) {
        highestSeq.current = Math.max(highestSeq.current, line.seq);
      }
      pending.current = [...pending.current, ...fresh];
      if (frame.current === null) {
        frame.current = requestAnimationFrame(flush);
      }
    };

    const invalidate = () => {
      lastInvalidated.current = Date.now();
      void client.invalidateQueries({ queryKey: ["runs"] });
    };

    const onTick = () => {
      const elapsed = Date.now() - lastInvalidated.current;
      if (elapsed >= TICK_INVALIDATE_MS) {
        // A trailing refresh can still be pending if its timer ran late;
        // this one supersedes it rather than following it by a few ms.
        if (trailing.current !== null) clearTimeout(trailing.current);
        trailing.current = null;
        invalidate();
        return;
      }
      if (trailing.current !== null) return;
      trailing.current = setTimeout(() => {
        trailing.current = null;
        invalidate();
      }, TICK_INVALIDATE_MS - elapsed);
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
      if (trailing.current !== null) clearTimeout(trailing.current);
      trailing.current = null;
      // The window belonged to this stream. A resumed run's new one should
      // refresh on its first tick rather than wait out the old window.
      lastInvalidated.current = 0;
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
