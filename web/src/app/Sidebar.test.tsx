import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { Sidebar } from "@/app/Sidebar";
import {
  makeActiveRuns,
  makeRunDetail,
  makeStageRecord,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

describe("Sidebar", () => {
  it("offers Topics, Runs and Settings, in that order", async () => {
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );

    renderWithProviders(<Sidebar />);

    const links = await screen.findAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Topics",
      "Runs",
      "Settings",
    ]);
  });

  it("shows no in-flight card while nothing is running", async () => {
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: null })),
      ),
    );

    renderWithProviders(<Sidebar />);
    await screen.findByRole("link", { name: "Runs" });

    expect(screen.queryByText("IN FLIGHT")).not.toBeInTheDocument();
  });

  it("names the running stage while one is", async () => {
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: "20260829T140200Z" })),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({
            runId: "20260829T140200Z",
            status: "running",
            stages: [
              makeStageRecord({ stage: "ingest" }),
              makeStageRecord({
                stage: "analyse",
                status: "running",
                finishedAt: null,
              }),
            ],
          }),
        ),
      ),
    );

    renderWithProviders(<Sidebar />);

    expect(await screen.findByText("IN FLIGHT")).toBeInTheDocument();
    expect(screen.getByText(/analyse/)).toBeInTheDocument();
  });

  it("links the card to the run it is about", async () => {
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: "20260829T140200Z" })),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({ runId: "20260829T140200Z", status: "running" }),
        ),
      ),
    );

    renderWithProviders(<Sidebar />);

    const card = await screen.findByRole("link", { name: /IN FLIGHT/ });
    expect(card).toHaveAttribute("href", "/runs/20260829T140200Z");
  });
});
