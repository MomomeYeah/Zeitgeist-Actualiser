/**
 * The query-key factory and the six read hooks, in one module so a key
 * cannot drift from the fetch that uses it.
 *
 * Nothing here polls. `useActiveRun` and `useRunEvents` — the two hooks that
 * carry live behaviour — are phase 6's, and an idle app on these screens
 * makes no requests after the ones its route needed.
 */
import { useQuery } from "@tanstack/react-query";

import { apiGet } from "@/api/client";
import type { ApiError } from "@/api/client";
import type {
  RankedTopic,
  RenderRecord,
  RunDetail,
  RunPage,
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
