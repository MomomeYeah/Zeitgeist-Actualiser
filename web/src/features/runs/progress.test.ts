import { describe, expect, it } from "vitest";

import { activeStage, stageCounter, stageFill } from "@/features/runs/progress";
import { makeStageRecord } from "@/test/factories";

describe("activeStage", () => {
  it("names the stage whose row says it is running", () => {
    expect(
      activeStage([
        makeStageRecord({ stage: "ingest" }),
        makeStageRecord({ stage: "analyse", status: "running", finishedAt: null }),
      ]),
    ).toBe("analyse");
  });

  it("falls back to the first stage with no row at all", () => {
    // The window between the worker opening the run row and the first
    // stage announcing itself. Reporting nothing there would leave the
    // in-flight screen with no live card for as long as ingest takes to
    // start.
    expect(activeStage([])).toBe("ingest");
    expect(activeStage([makeStageRecord({ stage: "ingest" })])).toBe("analyse");
  });

  it("names nothing once every stage has settled", () => {
    expect(
      activeStage([
        makeStageRecord({ stage: "ingest" }),
        makeStageRecord({ stage: "analyse" }),
        makeStageRecord({ stage: "evaluate" }),
        makeStageRecord({ stage: "generate" }),
      ]),
    ).toBeUndefined();
  });

  it("treats a skipped stage as settled", () => {
    // A resumed run skips everything before its start stage. Those are
    // done, not pending, and pointing the live card at one would show a
    // stage that will never run again.
    expect(
      activeStage([
        makeStageRecord({ stage: "ingest", status: "skipped" }),
        makeStageRecord({ stage: "analyse", status: "skipped" }),
      ]),
    ).toBe("evaluate");
  });
});

describe("stageFill", () => {
  it("fills a completed stage", () => {
    expect(stageFill(makeStageRecord({ stage: "ingest" }))).toBe(1);
  });

  it("fills a running stage by its counters", () => {
    expect(
      stageFill(
        makeStageRecord({ stage: "analyse", status: "running", done: 17, total: 25 }),
      ),
    ).toBeCloseTo(0.68);
  });

  it("leaves a running stage with no counters empty", () => {
    // Ingest and evaluate count nothing. A fabricated half-fill would be a
    // claim about progress nothing measured.
    expect(
      stageFill(makeStageRecord({ stage: "ingest", status: "running" })),
    ).toBe(0);
  });

  it("leaves an absent stage empty", () => {
    expect(stageFill(undefined)).toBe(0);
  });

  it("does not divide by a zero total", () => {
    // A run whose ingest returned nothing reaches analyse with zero trends.
    expect(
      stageFill(
        makeStageRecord({ stage: "analyse", status: "running", done: 0, total: 0 }),
      ),
    ).toBe(0);
  });
});

describe("stageCounter", () => {
  it("reads a running stage's counters", () => {
    expect(
      stageCounter(
        makeStageRecord({ stage: "analyse", status: "running", done: 17, total: 25 }),
      ),
    ).toBe("17 / 25");
  });

  it("says nothing for a stage that has finished", () => {
    // The finished card shows a duration in this slot. A counter there
    // would claim work is still going.
    expect(
      stageCounter(makeStageRecord({ stage: "analyse", done: 25, total: 25 })),
    ).toBeNull();
  });

  it("says nothing for a running stage that counts nothing", () => {
    expect(
      stageCounter(makeStageRecord({ stage: "ingest", status: "running" })),
    ).toBeNull();
  });
});
