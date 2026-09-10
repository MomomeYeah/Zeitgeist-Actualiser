import { describe, expect, it } from "vitest";

import { byRank, moodLine, moodSegments } from "@/features/topics/ordering";
import { makeIndexedTopic } from "@/test/factories";

describe("byRank", () => {
  it("orders by final score, highest first", () => {
    // The API returns recency order — newest run first, deduplicated on
    // label_slug — because that is what `topics_for_runs` produces. The
    // hero says "TOP RIGHT NOW", so the client sorts.
    const ordered = byRank([
      makeIndexedTopic({ topicId: "b", finalScore: 0.4 }),
      makeIndexedTopic({ topicId: "a", finalScore: 0.9 }),
      makeIndexedTopic({ topicId: "c", finalScore: 0.6 }),
    ]);

    expect(ordered.map((entry) => entry.topic.topic_id)).toEqual(["a", "c", "b"]);
  });

  it("breaks a tie on topic id so the order is total", () => {
    // Two topics can genuinely share a score. Without a tiebreak the order
    // depends on the input's order, and a test asserting on the first card
    // would pass or fail on nothing.
    const ordered = byRank([
      makeIndexedTopic({ topicId: "z", finalScore: 0.5 }),
      makeIndexedTopic({ topicId: "a", finalScore: 0.5 }),
    ]);

    expect(ordered.map((entry) => entry.topic.topic_id)).toEqual(["a", "z"]);
  });

  it("does not mutate what it was given", () => {
    const input = [
      makeIndexedTopic({ topicId: "b", finalScore: 0.4 }),
      makeIndexedTopic({ topicId: "a", finalScore: 0.9 }),
    ];

    byRank(input);

    expect(input.map((entry) => entry.topic.topic_id)).toEqual(["b", "a"]);
  });
});

describe("moodSegments", () => {
  it("sizes each segment by its share of the window", () => {
    const segments = moodSegments({ funny: 6, cute: 2, mundane: 2 });

    expect(segments.map((segment) => segment.sentiment)).toEqual([
      "funny",
      "cute",
      "mundane",
    ]);
    expect(segments[0]?.share).toBeCloseTo(0.6);
  });

  it("gives the top sentiment the accent and the second half of it", () => {
    const segments = moodSegments({ funny: 6, cute: 3 });

    expect(segments[0]?.tone).toBe("top");
    expect(segments[1]?.tone).toBe("second");
  });

  it("always draws schadenfreude in contrast, wherever it ranks", () => {
    // The handoff singles it out by name rather than by position.
    const segments = moodSegments({ funny: 9, cute: 5, schadenfreude: 1 });

    expect(segments.find((s) => s.sentiment === "schadenfreude")?.tone).toBe(
      "schadenfreude",
    );
  });

  it("returns nothing for a window with no distilled topics", () => {
    // Every topic on the dormant path has a null sentiment, so the totals
    // can legitimately be empty. Dividing by zero would give NaN widths.
    expect(moodSegments({})).toEqual([]);
  });
});

describe("moodLine", () => {
  it("names the leader, its share and its change on the previous run", () => {
    // 9/16 = 56%; the previous run's funny share was 7/13 = 54%. Both
    // denominators are that window's own total, which is the whole point:
    // comparing raw counts across windows of different sizes would report
    // a move that is only a change in how many topics were distilled.
    expect(moodLine({ funny: 9, cute: 5, mundane: 2 }, { funny: 7, cute: 6 })).toBe(
      "funny leads at 56% of the window · up 2 points on the previous run",
    );
  });

  it("says down when the leader lost ground", () => {
    expect(moodLine({ funny: 5, cute: 5 }, { funny: 8, cute: 2 })).toBe(
      "funny leads at 50% of the window · down 30 points on the previous run",
    );
  });

  it("drops the comparison when there is no previous run", () => {
    // "no previous run" and "no change" are different facts, and rendering
    // the second for the first would be a claim nothing supports.
    expect(moodLine({ funny: 9, cute: 5 }, {})).toBe(
      "funny leads at 64% of the window",
    );
  });

  it("says nothing at all for an empty window", () => {
    expect(moodLine({}, {})).toBe("");
  });
});
