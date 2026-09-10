import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  ACTIVE_POLL_MS,
  MAX_LOG_LINES,
  queryKeys,
  useAbortRun,
  useActiveRun,
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
import {
  makeActiveRuns,
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
});
