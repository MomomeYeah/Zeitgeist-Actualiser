import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { ApiError, apiGet, imageUrl } from "@/api/client";
import { server } from "@/test/server";

describe("apiGet", () => {
  it("returns the decoded body", async () => {
    server.use(
      http.get("/api/runs/:runId", () => HttpResponse.json({ hello: "world" })),
    );

    await expect(apiGet<{ hello: string }>("/api/runs/abc")).resolves.toEqual({
      hello: "world",
    });
  });

  it("appends the parameters it was given", async () => {
    let seen = "";
    server.use(
      http.get("/api/topics", ({ request }) => {
        seen = new URL(request.url).search;
        return HttpResponse.json({ topics: [] });
      }),
    );

    await apiGet("/api/topics", { window: 6, status: "trending" });

    expect(seen).toBe("?window=6&status=trending");
  });

  it("omits a parameter that is undefined rather than sending the string", async () => {
    // `status` is the filter chip's "no filter" state. Sending
    // `status=undefined` would filter on a status no topic has, and the
    // screen would silently render empty.
    let seen = "";
    server.use(
      http.get("/api/topics", ({ request }) => {
        seen = new URL(request.url).search;
        return HttpResponse.json({ topics: [] });
      }),
    );

    await apiGet("/api/topics", { window: 6, status: undefined });

    expect(seen).toBe("?window=6");
  });

  it("raises ApiError carrying the status and FastAPI's own detail", async () => {
    server.use(
      http.get("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "No such run: nope" }, { status: 404 }),
      ),
    );

    await expect(apiGet("/api/runs/nope")).rejects.toThrowError(
      // vitest types `expect.objectContaining` as returning `any` — a gap
      // in its own declarations, not an untyped value this file introduced.
      // eslint-disable-next-line @typescript-eslint/no-unsafe-argument
      expect.objectContaining({ status: 404, detail: "No such run: nope" }),
    );
  });

  it("raises ApiError with a readable detail when the body is not JSON", async () => {
    // uvicorn's own 502/503 pages are HTML. A client that assumed JSON here
    // would throw a SyntaxError, and the screen would report a parse failure
    // instead of the server being down.
    server.use(
      http.get("/api/runs", () =>
        HttpResponse.text("<html>Bad Gateway</html>", { status: 502 }),
      ),
    );

    await expect(apiGet("/api/runs")).rejects.toThrowError(
      // eslint-disable-next-line @typescript-eslint/no-unsafe-argument -- see above
      expect.objectContaining({ status: 502, detail: "Request failed (502)" }),
    );
  });

  it("is an Error, so an untyped boundary still reports something useful", () => {
    expect(new ApiError(404, "gone")).toBeInstanceOf(Error);
    expect(new ApiError(404, "gone").message).toBe("gone");
  });
});

describe("imageUrl", () => {
  it("addresses the full-size PNG", () => {
    expect(imageUrl("r1", "full")).toBe("/api/renders/r1/image?size=full");
  });

  it("addresses the 96px thumbnail", () => {
    expect(imageUrl("r1", "thumb")).toBe("/api/renders/r1/image?size=thumb");
  });
});
