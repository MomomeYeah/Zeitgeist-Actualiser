import { describe, expect, it } from "vitest";

import {
  formatBytes,
  formatClock,
  formatDuration,
  formatRelative,
  formatScore,
  shortRunId,
} from "@/format";

describe("formatBytes", () => {
  it("renders a stage payload the way the stage card does", () => {
    // 1_363_148 / 1_000_000 = 1.363148, which toFixed(1) rounds to 1.4.
    expect(formatBytes(1_363_148)).toBe("1.4 MB");
  });

  it("keeps small payloads in kB rather than showing 0.0 MB", () => {
    expect(formatBytes(4096)).toBe("4.1 kB");
  });

  it("renders bytes without a decimal point", () => {
    expect(formatBytes(812)).toBe("812 B");
  });

  it("says nothing for a stage that wrote no checkpoint", () => {
    // A queued, failed or skipped stage has payload_bytes = null. "0 B" would
    // claim it wrote an empty checkpoint, which is a different fact.
    expect(formatBytes(null)).toBe("—");
  });
});

describe("formatDuration", () => {
  it("renders minutes and seconds", () => {
    expect(formatDuration("2026-08-29T09:00:00Z", "2026-08-29T09:06:41Z")).toBe("6m 41s");
  });

  it("renders a sub-minute stage in seconds alone", () => {
    expect(formatDuration("2026-08-29T09:00:00Z", "2026-08-29T09:00:09Z")).toBe("9s");
  });

  it("renders hours when a run took them", () => {
    expect(formatDuration("2026-08-29T09:00:00Z", "2026-08-29T11:04:00Z")).toBe(
      "2h 4m",
    );
  });

  it("says nothing when the run has not finished", () => {
    expect(formatDuration("2026-08-29T09:00:00Z", null)).toBe("—");
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-08-29T12:00:00Z");

  it("renders minutes for something within the hour", () => {
    expect(formatRelative("2026-08-29T11:38:00Z", now)).toBe("22m ago");
  });

  it("renders hours within the day", () => {
    expect(formatRelative("2026-08-29T04:00:00Z", now)).toBe("8h ago");
  });

  it("renders days beyond that", () => {
    expect(formatRelative("2026-08-26T12:00:00Z", now)).toBe("3d ago");
  });

  it("renders the most recent minute as just now rather than 0m ago", () => {
    expect(formatRelative("2026-08-29T11:59:31Z", now)).toBe("just now");
  });
});

describe("formatScore", () => {
  it("renders two decimals, which is what the ranking columns show", () => {
    expect(formatScore(0.9)).toBe("0.90");
  });

  it("renders three where the design does, for the final score", () => {
    expect(formatScore(0.8954, 3)).toBe("0.895");
  });

  it("renders an em dash for a topic the model gave no meme potential", () => {
    // Dossier.meme_potential is null when the model returned no usable
    // number. "0.00" would read as "this is a terrible meme", which is a
    // claim the pipeline never made.
    expect(formatScore(null)).toBe("—");
  });
});

describe("shortRunId", () => {
  it("truncates to the tail the runs list shows", () => {
    expect(shortRunId("20260829T090000Z")).toBe("…829T090000Z");
  });

  it("leaves an id that is already short alone", () => {
    expect(shortRunId("090000Z")).toBe("090000Z");
  });
});

describe("formatClock", () => {
  it("renders the wall clock the Topics header ends with", () => {
    expect(formatClock("2026-08-29T14:02:00Z", "UTC")).toBe("14:02");
  });
});
