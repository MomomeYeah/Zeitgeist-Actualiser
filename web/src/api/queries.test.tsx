import { useQueryClient } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  ACTIVE_POLL_MS,
  GENERATION_POLL_MS,
  MAX_LOG_LINES,
  TICK_INVALIDATE_MS,
  queryKeys,
  useAbortRun,
  useActiveRun,
  useConfigOptions,
  useDeleteRender,
  useDeleteRun,
  useGenerateRenders,
  useRanking,
  useRender,
  useRun,
  useRuns,
  useRunEvents,
  useSaveSettings,
  useSettings,
  useTopicDetail,
  useTopicIndex,
} from "@/api/queries";
import type { RenderRecord } from "@/api/types";
import {
  makeActiveRuns,
  makeConfigOptions,
  makeLogLine,
  makeRankedTopic,
  makeRenderRecord,
  makeRunDetail,
  makeRunPage,
  makeSettingField,
  makeSettingFields,
  makeTopicDetail,
  makeTopicIndex,
} from "@/test/factories";
import { FakeEventSource } from "@/test/eventsource";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

describe("queryKeys", () => {
  it("scopes a ranking under its run, so one run's cache cannot serve another", () => {
    expect(queryKeys.ranking("a")).not.toEqual(queryKeys.ranking("b"));
  });

  it("varies with the topics window and status, which the filter chips change", () => {
    expect(queryKeys.topicIndex({ window: 6 })).not.toEqual(
      queryKeys.topicIndex({ window: 6, status: "trending" }),
    );
  });
});

describe("useRun", () => {
  it("resolves the run detail for the id it was given", async () => {
    server.use(
      http.get("/api/runs/:runId", ({ params }) =>
        HttpResponse.json(makeRunDetail({ runId: String(params.runId) })),
      ),
    );

    const { result } = renderHook(() => useRun("20260829T090000Z"), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.run.run_id).toBe("20260829T090000Z");
  });

  it("surfaces a 404 as an ApiError rather than retrying it", async () => {
    // The default retry would turn every mistyped run id into three requests
    // and a several-second wait before the screen could say "no such run".
    server.use(
      http.get("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "No such run: nope" }, { status: 404 }),
      ),
    );

    const { result } = renderHook(() => useRun("nope"), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.status).toBe(404);
    expect(result.current.failureCount).toBe(1);
  });

  it("does not fire until it has a run id", () => {
    const { result } = renderHook(() => useRun(undefined), {
      wrapper: renderWithProviders.Wrapper,
    });

    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useRanking", () => {
  it("returns the rows in the order the API sent them", async () => {
    server.use(
      http.get("/api/runs/:runId/topics", () =>
        HttpResponse.json([
          makeRankedTopic({ topicId: "t1", finalRank: 1 }),
          makeRankedTopic({ topicId: "t2", finalRank: 2 }),
        ]),
      ),
    );

    const { result } = renderHook(() => useRanking("r1"), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.map((row) => row.topic.topic_id)).toEqual(["t1", "t2"]);
  });
});

describe("useRuns", () => {
  it("sends the limit it was given", async () => {
    let seen = "";
    server.use(
      http.get("/api/runs", ({ request }) => {
        seen = new URL(request.url).search;
        return HttpResponse.json(makeRunPage());
      }),
    );

    const { result } = renderHook(() => useRuns(10), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(seen).toBe("?limit=10");
  });
});

describe("useTopicDetail", () => {
  it("does not fire until it has both a run id and a topic id", () => {
    // Two ids, so the guard is an `&&`. Mutated to `||`, this would request
    // `/api/runs/undefined/topics/t1` — a 404 the screen would report as a
    // missing topic, sending someone looking for a data problem that is
    // really a routing one.
    const { result: onlyRun } = renderHook(() => useTopicDetail("r1", undefined), {
      wrapper: renderWithProviders.Wrapper,
    });
    expect(onlyRun.current.fetchStatus).toBe("idle");

    const { result: onlyTopic } = renderHook(() => useTopicDetail(undefined, "t1"), {
      wrapper: renderWithProviders.Wrapper,
    });
    expect(onlyTopic.current.fetchStatus).toBe("idle");
  });

  it("addresses the topic under its run once both ids are present", async () => {
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", ({ params }) =>
        HttpResponse.json(
          makeTopicDetail({
            runId: String(params.runId),
            topicId: String(params.topicId),
          }),
        ),
      ),
    );

    const { result } = renderHook(() => useTopicDetail("r1", "t1"), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.topic.topic_id).toBe("t1");
  });
});

describe("useRender", () => {
  it("resolves the render for the id it was given", async () => {
    server.use(
      http.get("/api/renders/:renderId", ({ params }) =>
        HttpResponse.json(makeRenderRecord({ id: String(params.renderId) })),
      ),
    );

    const { result } = renderHook(() => useRender("render-9"), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe("render-9");
  });

  it("does not fire until it has a render id", () => {
    const { result } = renderHook(() => useRender(undefined), {
      wrapper: renderWithProviders.Wrapper,
    });

    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useTopicIndex", () => {
  it("sends the window and the status filter", async () => {
    let seen = "";
    server.use(
      http.get("/api/topics", ({ request }) => {
        seen = new URL(request.url).search;
        return HttpResponse.json(makeTopicIndex());
      }),
    );

    const { result } = renderHook(() => useTopicIndex({ window: 6, status: "cooling" }), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(seen).toBe("?window=6&status=cooling");
  });
});

describe("useActiveRun", () => {
  it("does not poll while nothing is running", async () => {
    let calls = 0;
    server.use(
      http.get("/api/runs/active", () => {
        calls += 1;
        return HttpResponse.json(makeActiveRuns({ current: null }));
      }),
    );

    const { result } = renderHook(() => useActiveRun(), {
      wrapper: renderWithProviders.Wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    await new Promise((resolve) => setTimeout(resolve, ACTIVE_POLL_MS + 200));
    expect(calls).toBe(1);
  });

  it("polls while a run is in flight", async () => {
    let calls = 0;
    server.use(
      http.get("/api/runs/active", () => {
        calls += 1;
        return HttpResponse.json(makeActiveRuns({ current: "r1" }));
      }),
    );

    const { result } = renderHook(() => useActiveRun(), {
      wrapper: renderWithProviders.Wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    await waitFor(() => expect(calls).toBeGreaterThan(1), {
      timeout: ACTIVE_POLL_MS * 3,
    });
  });
});

describe("useRunEvents", () => {
  it("accumulates the lines the stream sends", async () => {
    const { result } = renderHook(() => useRunEvents("r1", true), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => {
      FakeEventSource.latest().emitLog([makeLogLine({ seq: 1, message: "one" })]);
      FakeEventSource.latest().emitLog([makeLogLine({ seq: 2, message: "two" })]);
    });

    await waitFor(() => expect(result.current).toHaveLength(2));
    expect(result.current.map((line) => line.message)).toEqual(["one", "two"]);
  });

  it("keeps only the most recent lines once the cap is reached", async () => {
    // A DEBUG run logs per distilled topic and per rendered meme; the DOM
    // would otherwise grow for as long as the run does.
    const { result } = renderHook(() => useRunEvents("r1", true), {
      wrapper: renderWithProviders.Wrapper,
    });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    const flood = Array.from({ length: MAX_LOG_LINES + 5 }, (_, index) =>
      makeLogLine({ seq: index, message: `line ${index}` }),
    );
    act(() => FakeEventSource.latest().emitLog(flood));

    await waitFor(() => expect(result.current).toHaveLength(MAX_LOG_LINES));
    expect(result.current[0]?.message).toBe("line 5");
  });

  it("opens the run's own stream and refreshes it on a tick, at most once a second", async () => {
    // Half of this hook is the tick handler, and nothing else in the plan
    // calls `emitTick`. Delete the listener, or drop the throttle so all
    // four ticks a second refetch run detail, and no other test notices.
    // The URL is asserted here for the same reason: a wrong path delivers
    // no events at all, silently.
    let detailCalls = 0;
    server.use(
      http.get("/api/runs/r1", () => {
        detailCalls += 1;
        return HttpResponse.json(makeRunDetail({ runId: "r1", status: "running" }));
      }),
    );

    const { result } = renderHook(
      () => ({ run: useRun("r1"), lines: useRunEvents("r1", true) }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.run.isSuccess).toBe(true));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(FakeEventSource.latest().url).toBe("/api/runs/r1/events");

    act(() => {
      FakeEventSource.latest().emitTick();
      FakeEventSource.latest().emitTick();
      FakeEventSource.latest().emitTick();
    });

    // One refetch for the burst, not three: the stream ticks four times a
    // second and the rows behind it change once a stage.
    await waitFor(() => expect(detailCalls).toBe(2));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(detailCalls).toBe(2);
  });

  it("holds each line once when a reconnected stream replays the buffer", async () => {
    // The server sends no `id:` lines, so an `EventSource` that reconnects
    // mid-run starts again at `since(0)` and replays everything the buffer
    // still holds. Appended as they came, those lines doubled the log and
    // repeated the `seq` the rows are keyed by.
    const { result } = renderHook(() => useRunEvents("r1", true), {
      wrapper: renderWithProviders.Wrapper,
    });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    const upTo = (last: number) =>
      Array.from({ length: last }, (_, index) =>
        makeLogLine({ seq: index + 1, message: `line ${index + 1}` }),
      );
    act(() => FakeEventSource.latest().emitLog(upTo(3)));
    await waitFor(() => expect(result.current).toHaveLength(3));

    act(() => FakeEventSource.latest().emitLog(upTo(5)));

    await waitFor(() =>
      expect(result.current.map((line) => line.seq)).toEqual([1, 2, 3, 4, 5]),
    );
  });

  it("refreshes once more at the end of a window a tick was throttled in", async () => {
    // The tick after a run's final status write usually lands inside the
    // window the previous tick opened, and was dropped — so run detail kept
    // saying "Stopping…", clock still counting, until the stream
    // reconnected seconds later. A throttled tick now leaves one refresh
    // for the window's end.
    let detailCalls = 0;
    server.use(
      http.get("/api/runs/r1", () => {
        detailCalls += 1;
        return HttpResponse.json(makeRunDetail({ runId: "r1", status: "running" }));
      }),
    );

    const { result } = renderHook(
      () => ({ run: useRun("r1"), lines: useRunEvents("r1", true) }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.run.isSuccess).toBe(true));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.latest().emitTick();
      FakeEventSource.latest().emitTick();
    });
    await waitFor(() => expect(detailCalls).toBe(2));

    await waitFor(() => expect(detailCalls).toBe(3), {
      timeout: TICK_INVALIDATE_MS * 2,
    });
    // One trailing refresh for the window, not one per throttled tick.
    await new Promise((resolve) => setTimeout(resolve, TICK_INVALIDATE_MS + 200));
    expect(detailCalls).toBe(3);
  });

  it("refreshes on the first tick of a reopened stream, without waiting out the old window", async () => {
    // A resumed run goes live again on the same page, which closes the
    // stream and opens a new one. The throttle's clock belonged to the old
    // stream; carried over, the new stream's first tick waited out a window
    // that had nothing to do with it.
    let detailCalls = 0;
    server.use(
      http.get("/api/runs/r1", () => {
        detailCalls += 1;
        return HttpResponse.json(makeRunDetail({ runId: "r1", status: "running" }));
      }),
    );

    const { result, rerender } = renderHook(
      ({ live }: { live: boolean }) => ({
        run: useRun("r1"),
        lines: useRunEvents("r1", live),
      }),
      { wrapper: renderWithProviders.Wrapper, initialProps: { live: true } },
    );
    await waitFor(() => expect(result.current.run.isSuccess).toBe(true));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => FakeEventSource.latest().emitTick());
    await waitFor(() => expect(detailCalls).toBe(2));

    rerender({ live: false });
    rerender({ live: true });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
    act(() => FakeEventSource.latest().emitTick());

    await waitFor(() => expect(detailCalls).toBe(3), {
      timeout: TICK_INVALIDATE_MS / 2,
    });
  });

  it("opens no stream, and closes an open one, when it is not enabled", async () => {
    const { rerender } = renderHook(
      ({ live }: { live: boolean }) => useRunEvents("r1", live),
      { wrapper: renderWithProviders.Wrapper, initialProps: { live: true } },
    );
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    rerender({ live: false });

    await waitFor(() => expect(FakeEventSource.latest().closed).toBe(true));
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});

describe("the run mutations", () => {
  it("abort posts to the run and refreshes what is active", async () => {
    let aborted = "";
    let activeCalls = 0;
    server.use(
      http.post("/api/runs/:runId/abort", ({ params }) => {
        aborted = String(params.runId);
        return HttpResponse.json({ run_id: aborted, requested: "abort" }, { status: 202 });
      }),
      http.get("/api/runs/active", () => {
        activeCalls += 1;
        return HttpResponse.json(makeActiveRuns({ current: null }));
      }),
    );

    const { result } = renderHook(
      () => ({ active: useActiveRun(), abort: useAbortRun("r1") }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.active.isSuccess).toBe(true));

    await act(async () => {
      await result.current.abort.mutateAsync();
    });

    expect(aborted).toBe("r1");
    await waitFor(() => expect(activeCalls).toBeGreaterThan(1));
  });

  it("saving settings writes the reply straight into the cache", async () => {
    // PUT /api/settings returns the same shape as the GET, on purpose, so
    // the source chips re-render from the reply rather than from a second
    // request. A refetch here would be a wasted round trip and a visible
    // flicker on the chip that just changed.
    let getCalls = 0;
    server.use(
      http.get("/api/settings", () => {
        getCalls += 1;
        return HttpResponse.json(makeSettingFields());
      }),
      http.put("/api/settings", () =>
        HttpResponse.json([
          makeSettingField({ key: "phrase_min_authors", value: 9, source: "settings" }),
        ]),
      ),
    );

    const { result } = renderHook(
      () => ({ settings: useSettings(), save: useSaveSettings() }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.settings.isSuccess).toBe(true));

    await act(async () => {
      await result.current.save.mutateAsync({ values: { phrase_min_authors: "9" } });
    });

    await waitFor(() => expect(result.current.settings.data).toHaveLength(1));
    expect(result.current.settings.data?.[0]?.value).toBe(9);
    expect(getCalls).toBe(1);
  });

  it("saving settings refreshes the defaults the New run screen draws", async () => {
    // Found on a real run: with `bluesky_trend_limit` just lowered on the
    // settings screen, New run still said "of 25 trends analysed" from the
    // options it already held, until a stale-time refetch caught up. The
    // settings reply goes into its own cache; the options are a second
    // answer the same write changed.
    const defaults = makeConfigOptions().defaults;
    let trendLimit = "25";
    server.use(
      http.get("/api/config/options", () =>
        HttpResponse.json(
          makeConfigOptions({
            defaults: { ...defaults, bluesky_trend_limit: trendLimit },
          }),
        ),
      ),
      http.put("/api/settings", () => {
        trendLimit = "4";
        return HttpResponse.json(
          makeSettingFields({ bluesky_trend_limit: { value: 4, source: "settings" } }),
        );
      }),
    );

    const { result } = renderHook(
      () => ({ options: useConfigOptions(), save: useSaveSettings() }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.options.isSuccess).toBe(true));
    expect(result.current.options.data?.defaults.bluesky_trend_limit).toBe("25");

    await act(async () => {
      await result.current.save.mutateAsync({ values: { bluesky_trend_limit: "4" } });
    });

    await waitFor(() =>
      expect(result.current.options.data?.defaults.bluesky_trend_limit).toBe("4"),
    );
  });
});

describe("useTopicDetail while renders generate", () => {
  it("polls while a render is generating, and stops once none is", async () => {
    // Asserted as a quiet window rather than a call count. The render
    // finishing triggers a refresh of its own — this detail is one of the
    // views that count renders — and how many requests that makes is the
    // implementation's business. What polling means is that requests keep
    // coming a poll interval apart, so the proof it stopped is a stretch
    // longer than one interval with no request at all.
    const requestedAt: number[] = [];
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () => {
        requestedAt.push(Date.now());
        // Generating on the first answer, ready on every one after.
        const status = requestedAt.length === 1 ? "generating" : "ready";
        return HttpResponse.json(
          makeTopicDetail({ renders: [makeRenderRecord({ id: "r1", status })] }),
        );
      }),
    );

    const { result } = renderHook(() => useTopicDetail("r1", "t1"), {
      wrapper: renderWithProviders.Wrapper,
    });

    // Reaching "ready" at all needs a poll: the first answer was generating.
    await waitFor(() => expect(result.current.data?.renders[0]?.status).toBe("ready"), {
      timeout: GENERATION_POLL_MS * 2,
    });
    await new Promise((resolve) => setTimeout(resolve, GENERATION_POLL_MS + 500));

    const quiet = Date.now() - (requestedAt.at(-1) ?? 0);
    expect(quiet).toBeGreaterThan(GENERATION_POLL_MS);
  }, 10_000);

  it("does not poll a topic with nothing generating", async () => {
    // A failed render is settled too: it will never become anything else,
    // so it is no reason to keep asking.
    let calls = 0;
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () => {
        calls += 1;
        return HttpResponse.json(
          makeTopicDetail({
            renders: [
              makeRenderRecord({ id: "r1", status: "ready" }),
              makeRenderRecord({ id: "r2", status: "failed", error: "overflow" }),
            ],
          }),
        );
      }),
    );

    const { result } = renderHook(() => useTopicDetail("r1", "t1"), {
      wrapper: renderWithProviders.Wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    await new Promise((resolve) => setTimeout(resolve, GENERATION_POLL_MS + 300));
    expect(calls).toBe(1);
  });

  it("refreshes the run's ranking when a render finishes", async () => {
    // `render_count` counts ready renders only, so a render finishing here
    // changes a number the ranking holds. Nothing else would tell it.
    let detailCalls = 0;
    let rankingCalls = 0;
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () => {
        detailCalls += 1;
        const status = detailCalls === 1 ? "generating" : "ready";
        return HttpResponse.json(
          makeTopicDetail({ renders: [makeRenderRecord({ id: "r1", status })] }),
        );
      }),
      http.get("/api/runs/:runId/topics", () => {
        rankingCalls += 1;
        return HttpResponse.json([makeRankedTopic()]);
      }),
    );

    const { result } = renderHook(
      () => ({ detail: useTopicDetail("r1", "t1"), ranking: useRanking("r1") }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.ranking.isSuccess).toBe(true));
    expect(rankingCalls).toBe(1);

    await waitFor(() => expect(rankingCalls).toBe(2), {
      timeout: GENERATION_POLL_MS * 3,
    });
  });
});

describe("useGenerateRenders", () => {
  it("posts to the topic's renders and puts the rows it returns straight into the cache", async () => {
    // The rows go into the cache from the reply itself. Waiting for a
    // refetch instead would leave a gap between the placeholders going and
    // the rows arriving. Every detail request after the first is held open,
    // so the only way "new" can reach the cache is the mutation's own write
    // — an implementation that invalidated rather than wrote never gets
    // there, deterministically rather than depending on which response
    // lands first.
    let detailCalls = 0;
    let posted: unknown = null;
    let postedTo = "";
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", async () => {
        detailCalls += 1;
        if (detailCalls > 1) await new Promise(() => undefined);
        return HttpResponse.json(
          makeTopicDetail({ renders: [makeRenderRecord({ id: "old" })] }),
        );
      }),
      http.post("/api/runs/:runId/topics/:topicId/renders", async ({ request, params }) => {
        posted = await request.json();
        postedTo = `${String(params.runId)}/${String(params.topicId)}`;
        return HttpResponse.json(
          [
            makeRenderRecord({
              id: "new",
              status: "generating",
              templateId: null,
              captionSlots: {},
            }),
          ],
          { status: 202 },
        );
      }),
    );

    const { result } = renderHook(
      () => ({ detail: useTopicDetail("r1", "t1"), generate: useGenerateRenders("r1", "t1") }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));

    await act(async () => {
      await result.current.generate.mutateAsync({ mode: "llm", template_id: null, count: 1 });
    });

    expect(postedTo).toBe("r1/t1");
    expect(posted).toEqual({ mode: "llm", template_id: null, count: 1 });
    // TanStack notifies observers on a setTimeout(0) batch, so this can lag
    // mutateAsync's own resolution by a tick. Every later detail GET is
    // held open, so only the mutation's own cache write can ever satisfy
    // this — a refetch can't get there first.
    await waitFor(() =>
      expect(result.current.detail.data?.renders.map((render) => render.id)).toEqual([
        "old",
        "new",
      ]),
    );
  });

  it("is not undone by a detail fetch that was sent before the rows existed", async () => {
    // The poll or a refocus can have a detail request on its way when the
    // reply lands. Answered from before the post, it lacks the new rows;
    // written over them, it would take the tiles away, and with nothing
    // left generating the poll that would find them again would stop.
    const created = makeRenderRecord({
      id: "new",
      status: "generating",
      templateId: null,
      captionSlots: {},
    });
    let renders = [makeRenderRecord({ id: "old" })];
    let detailCalls = 0;
    let staleAnswered = false;
    let releaseStale: () => void = () => undefined;
    const stale = new Promise<void>((resolve) => {
      releaseStale = resolve;
    });
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", async () => {
        detailCalls += 1;
        // Answered from the server's state at the moment it was asked.
        const answer = makeTopicDetail({ renders });
        if (detailCalls === 2) {
          await stale;
          staleAnswered = true;
        }
        return HttpResponse.json(answer);
      }),
      http.post("/api/runs/:runId/topics/:topicId/renders", () => {
        renders = [...renders, created];
        return HttpResponse.json([created], { status: 202 });
      }),
    );

    const { result } = renderHook(
      () => ({ detail: useTopicDetail("r1", "t1"), generate: useGenerateRenders("r1", "t1") }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));

    // A second fetch, sent and held before anything is posted.
    void result.current.detail.refetch();
    await waitFor(() => expect(detailCalls).toBe(2));

    await act(async () => {
      await result.current.generate.mutateAsync({ mode: "llm", template_id: null, count: 1 });
    });
    releaseStale();
    // Wait for the stale answer to have been sent and for the query to
    // settle, rather than for a fixed interval: a sleep that ran out before
    // the stale response was processed would let this test pass against
    // the very bug it names. Without the cancel, the query stays fetching
    // until that response lands and overwrites the cache; with it, the
    // query is already idle.
    await waitFor(() => expect(staleAnswered).toBe(true));
    await waitFor(() => expect(result.current.detail.isFetching).toBe(false));

    expect(result.current.detail.data?.renders.map((render) => render.id)).toEqual([
      "old",
      "new",
    ]);
  });

  it("does not draw a row twice when a fetch already brought it in", async () => {
    // A poll or a refocus can read the database after the post committed
    // its rows and land before the post's own reply. The rows are then
    // already in the cache, and appending the reply again would draw each
    // tile twice under one key.
    //
    // The fixture's initial GET already answers with both rows — that is
    // the scenario itself — so the pre-mutation snapshot and the desired
    // post-mutation state are the same array. A plain `waitFor` right after
    // `mutateAsync` can therefore pass on its very first, synchronous check
    // against that stale pre-mutation snapshot, before TanStack's
    // `setTimeout(0)` observer-notify batch has run at all — which would
    // "pass" identically whether or not the bug is fixed. The explicit
    // macrotask flush below forces that batch to run first, so the
    // assertion reads the mutation's actual cache write, not a snapshot the
    // mutation never touched.
    const created = makeRenderRecord({
      id: "new",
      status: "generating",
      templateId: null,
      captionSlots: {},
    });
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(
          makeTopicDetail({ renders: [makeRenderRecord({ id: "old" }), created] }),
        ),
      ),
      http.post("/api/runs/:runId/topics/:topicId/renders", () =>
        HttpResponse.json([created], { status: 202 }),
      ),
    );

    const { result } = renderHook(
      () => ({ detail: useTopicDetail("r1", "t1"), generate: useGenerateRenders("r1", "t1") }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));

    await act(async () => {
      await result.current.generate.mutateAsync({ mode: "llm", template_id: null, count: 1 });
    });
    // Flush the pending observer-notify macrotask before reading `data`.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(result.current.detail.data?.renders.map((render) => render.id)).toEqual([
      "old",
      "new",
    ]);
  });
});

describe("useDeleteRender", () => {
  // `makeRenderRecord`'s own run and topic, which is what the hook keys the
  // cached detail by.
  const RUN = "20260829T090000Z";
  const TOPIC = "topic-1";

  /**
   * Answers the first detail request and holds every later one open, so the
   * only way a row can leave the cache in these tests is the mutation's own
   * write — not a refetch that happens to agree with it.
   */
  function serveDetailOnce(renders: RenderRecord[]) {
    let calls = 0;
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", async () => {
        calls += 1;
        if (calls > 1) await new Promise(() => undefined);
        return HttpResponse.json(makeTopicDetail({ renders }));
      }),
    );
  }

  it("takes the row out of the cached topic at once, not after a refetch", async () => {
    // "The tile disappearing is the confirmation", per the handoff.
    serveDetailOnce([makeRenderRecord({ id: "keep" }), makeRenderRecord({ id: "gone" })]);
    server.use(
      http.delete("/api/renders/:renderId", () => new HttpResponse(null, { status: 204 })),
    );

    const { result } = renderHook(
      () => ({ detail: useTopicDetail(RUN, TOPIC), remove: useDeleteRender() }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));

    await act(async () => {
      await result.current.remove.mutateAsync(makeRenderRecord({ id: "gone" }));
    });

    // TanStack notifies observers on a setTimeout(0) batch, so this can lag
    // mutateAsync's own resolution by a tick. Every later detail GET is
    // held open, so only the mutation's own cache write can ever satisfy
    // this — a refetch can't get there first.
    await waitFor(() =>
      expect(result.current.detail.data?.renders.map((render) => render.id)).toEqual(["keep"]),
    );
  });

  it("counts a render that is already gone as deleted", async () => {
    // Deleted in another tab. The end state asked for is the state the
    // server reports; a tile that stayed put with an error nobody can act
    // on would be the wrong answer to it.
    serveDetailOnce([makeRenderRecord({ id: "gone" })]);
    server.use(
      http.delete("/api/renders/:renderId", () =>
        HttpResponse.json({ detail: "No such render: gone" }, { status: 404 }),
      ),
    );

    const { result } = renderHook(
      () => ({ detail: useTopicDetail(RUN, TOPIC), remove: useDeleteRender() }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));

    await act(async () => {
      await result.current.remove.mutateAsync(makeRenderRecord({ id: "gone" }));
    });

    // TanStack notifies observers on a setTimeout(0) batch, so this can lag
    // mutateAsync's own resolution by a tick. Every later detail GET is
    // held open, so only the mutation's own cache write can ever satisfy
    // this — a refetch can't get there first.
    await waitFor(() => expect(result.current.detail.data?.renders).toEqual([]));
  });

  it("refreshes the ranking, which just lost a meme", async () => {
    let rankingCalls = 0;
    serveDetailOnce([makeRenderRecord({ id: "gone" })]);
    server.use(
      http.get("/api/runs/:runId/topics", () => {
        rankingCalls += 1;
        return HttpResponse.json([makeRankedTopic()]);
      }),
      http.delete("/api/renders/:renderId", () => new HttpResponse(null, { status: 204 })),
    );

    const { result } = renderHook(
      () => ({
        detail: useTopicDetail(RUN, TOPIC),
        ranking: useRanking(RUN),
        remove: useDeleteRender(),
      }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.ranking.isSuccess).toBe(true));

    await act(async () => {
      await result.current.remove.mutateAsync(makeRenderRecord({ id: "gone" }));
    });

    await waitFor(() => expect(rankingCalls).toBe(2));
  });

  it("refreshes the topics index, whose meme counts just lost one", async () => {
    // The index counts ready renders per topic, as the ranking does, but
    // lives under its own key rather than under the run's.
    let indexCalls = 0;
    serveDetailOnce([makeRenderRecord({ id: "gone" })]);
    server.use(
      http.get("/api/topics", () => {
        indexCalls += 1;
        return HttpResponse.json(makeTopicIndex());
      }),
      http.delete("/api/renders/:renderId", () => new HttpResponse(null, { status: 204 })),
    );

    const { result } = renderHook(
      () => ({
        detail: useTopicDetail(RUN, TOPIC),
        index: useTopicIndex(),
        remove: useDeleteRender(),
      }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.index.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));

    await act(async () => {
      await result.current.remove.mutateAsync(makeRenderRecord({ id: "gone" }));
    });

    await waitFor(() => expect(indexCalls).toBe(2));
  });

  it("leaves the row where it was when the server refuses", async () => {
    // A 500 is a render that still exists. Taking it out of the cache
    // anyway — TanStack's optimistic `onMutate` pattern with no rollback,
    // which "the tile disappearing is the confirmation" invites — would
    // show a deletion that did not happen, and unmount the tile that
    // carries the server's reason.
    serveDetailOnce([makeRenderRecord({ id: "keep" }), makeRenderRecord({ id: "stuck" })]);
    server.use(
      http.delete("/api/renders/:renderId", () =>
        HttpResponse.json({ detail: "Permission denied: renders/stuck.png" }, { status: 500 }),
      ),
    );

    const { result } = renderHook(
      () => ({ detail: useTopicDetail(RUN, TOPIC), remove: useDeleteRender() }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));

    act(() => {
      result.current.remove.mutate(makeRenderRecord({ id: "stuck" }));
    });
    await waitFor(() => expect(result.current.remove.isError).toBe(true));

    expect(result.current.detail.data?.renders.map((render) => render.id)).toEqual([
      "keep",
      "stuck",
    ]);
  });

  it("invalidates the render's own query, so Back does not show it from a stale cache", async () => {
    // With the app's 30s staleTime, pressing Back after deleting from the
    // full-size view would otherwise show the deleted render from cache,
    // with no refetch. The test client's default staleTime is 0, so
    // `isStale` can't tell "invalidated" apart from "always stale" —
    // `isInvalidated` on the cache's own query state is a marker
    // `invalidateQueries` sets independently of staleTime, so it is the
    // honest observable here.
    serveDetailOnce([makeRenderRecord({ id: "gone" })]);
    server.use(
      http.get("/api/renders/:renderId", () =>
        HttpResponse.json(makeRenderRecord({ id: "gone" })),
      ),
      http.delete("/api/renders/:renderId", () => new HttpResponse(null, { status: 204 })),
    );

    const { result } = renderHook(
      () => ({
        detail: useTopicDetail(RUN, TOPIC),
        render: useRender("gone"),
        remove: useDeleteRender(),
        client: useQueryClient(),
      }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.render.isSuccess).toBe(true));

    await act(async () => {
      await result.current.remove.mutateAsync(makeRenderRecord({ id: "gone" }));
    });

    await waitFor(() =>
      expect(
        result.current.client.getQueryState(queryKeys.render("gone"))?.isInvalidated,
      ).toBe(true),
    );
  });
});

describe("useDeleteRun", () => {
  const RUN = "20260829T090000Z";

  /**
   * Answers each of the run's own reads once and holds every later one
   * open. A refetch then sits at `fetchStatus: "fetching"` for good, so a
   * check made after the mutation cannot miss one that came and went.
   */
  function serveRunOnce() {
    let runCalls = 0;
    let rankingCalls = 0;
    server.use(
      http.get("/api/runs/:runId", async () => {
        runCalls += 1;
        if (runCalls > 1) await new Promise(() => undefined);
        return HttpResponse.json(makeRunDetail({ runId: RUN }));
      }),
      http.get("/api/runs/:runId/topics", async () => {
        rankingCalls += 1;
        if (rankingCalls > 1) await new Promise(() => undefined);
        return HttpResponse.json([makeRankedTopic()]);
      }),
    );
  }

  it("does not refetch the run's own queries, which the page is still showing", async () => {
    // Refetched, the detail 404s and the page draws "No such run." for a
    // frame before it navigates away.
    serveRunOnce();
    server.use(
      http.delete("/api/runs/:runId", () => new HttpResponse(null, { status: 204 })),
    );

    const { result } = renderHook(
      () => ({
        run: useRun(RUN),
        ranking: useRanking(RUN),
        remove: useDeleteRun(RUN),
        client: useQueryClient(),
      }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.run.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.ranking.isSuccess).toBe(true));

    await act(async () => {
      await result.current.remove.mutateAsync();
    });

    const { client } = result.current;
    expect(client.getQueryState(queryKeys.run(RUN))?.fetchStatus).toBe("idle");
    expect(client.getQueryState(queryKeys.ranking(RUN))?.fetchStatus).toBe("idle");
    // ...but stale, so arriving back at the run — or its ranking — asks
    // the server again rather than drawing a deleted run from cache.
    expect(client.getQueryState(queryKeys.run(RUN))?.isInvalidated).toBe(true);
    expect(client.getQueryState(queryKeys.ranking(RUN))?.isInvalidated).toBe(true);
  });

  it("refreshes the runs list and the topics index, which both just lost a run", async () => {
    let listCalls = 0;
    let indexCalls = 0;
    server.use(
      http.get("/api/runs", () => {
        listCalls += 1;
        return HttpResponse.json(makeRunPage());
      }),
      http.get("/api/topics", () => {
        indexCalls += 1;
        return HttpResponse.json(makeTopicIndex());
      }),
      http.delete("/api/runs/:runId", () => new HttpResponse(null, { status: 204 })),
    );

    const { result } = renderHook(
      () => ({ runs: useRuns(), topics: useTopicIndex(), remove: useDeleteRun(RUN) }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.runs.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.topics.isSuccess).toBe(true));

    await act(async () => {
      await result.current.remove.mutateAsync();
    });

    await waitFor(() => expect(listCalls).toBe(2));
    await waitFor(() => expect(indexCalls).toBe(2));
  });

  it("counts a run that is already gone as deleted", async () => {
    // Deleted in another tab. The end state asked for is the one the
    // server reports.
    server.use(
      http.delete("/api/runs/:runId", () =>
        HttpResponse.json({ detail: `No such run: ${RUN}` }, { status: 404 }),
      ),
    );

    const { result } = renderHook(() => useDeleteRun(RUN), {
      wrapper: renderWithProviders.Wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync();
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("passes any other refusal through for the page to show", async () => {
    server.use(
      http.delete("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "Memes are still generating" }, { status: 409 }),
      ),
    );

    const { result } = renderHook(() => useDeleteRun(RUN), {
      wrapper: renderWithProviders.Wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync().catch(() => undefined);
    });

    await waitFor(() => expect(result.current.error?.status).toBe(409));
    expect(result.current.error?.detail).toBe("Memes are still generating");
  });
});
