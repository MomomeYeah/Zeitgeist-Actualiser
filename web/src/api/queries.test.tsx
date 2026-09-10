import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  queryKeys,
  useRanking,
  useRender,
  useRun,
  useRuns,
  useTopicDetail,
  useTopicIndex,
} from "@/api/queries";
import {
  makeRankedTopic,
  makeRenderRecord,
  makeRunDetail,
  makeRunPage,
  makeTopicDetail,
  makeTopicIndex,
} from "@/test/factories";
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
