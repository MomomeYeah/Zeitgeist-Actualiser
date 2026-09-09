import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { useRun } from "@/api/queries";
import { QueryBoundary } from "@/components/QueryBoundary";
import { makeRunDetail } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

function Subject({ runId }: { runId: string }) {
  return (
    <QueryBoundary query={useRun(runId)} missing="No such run.">
      {(detail) => <p>{detail.run.run_id}</p>}
    </QueryBoundary>
  );
}

describe("QueryBoundary", () => {
  it("renders its children once the data arrives", async () => {
    server.use(http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())));

    renderWithProviders(<Subject runId="20260829T090000Z" />);

    expect(await screen.findByText("20260829T090000Z")).toBeInTheDocument();
  });

  it("says what is missing on a 404 rather than showing a generic failure", async () => {
    // A mistyped run id and a server that is down are different problems,
    // and the fix for each is different too.
    server.use(
      http.get("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "No such run: nope" }, { status: 404 }),
      ),
    );

    renderWithProviders(<Subject runId="nope" />);

    expect(await screen.findByText("No such run.")).toBeInTheDocument();
  });

  it("surfaces the server's own detail on any other failure", async () => {
    server.use(
      http.get("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "database is locked" }, { status: 500 }),
      ),
    );

    renderWithProviders(<Subject runId="r1" />);

    expect(await screen.findByText(/database is locked/)).toBeInTheDocument();
  });

  it("says it is loading while the request is in flight", async () => {
    server.use(http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())));

    renderWithProviders(<Subject runId="20260829T090000Z" />);

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText("Loading…")).not.toBeInTheDocument(),
    );
  });
});
