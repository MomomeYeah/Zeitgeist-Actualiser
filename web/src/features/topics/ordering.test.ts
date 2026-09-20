import { describe, expect, it } from "vitest";

import {
  byRank,
  foldNarrowSegments,
  moodLine,
  moodSegments,
} from "@/features/topics/ordering";
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

  it("tones every sentiment by rank, schadenfreude included", () => {
    // Schadenfreude used to take `contrast` wherever it ranked, which made
    // it the one segment whose colour did not mean a position. It is a
    // sentiment like any other now, so third place takes the third tone.
    const segments = moodSegments({ funny: 9, cute: 5, schadenfreude: 1 });

    expect(segments.map((segment) => segment.tone)).toEqual([
      "top",
      "second",
      "tail",
    ]);
  });

  it("returns nothing for a window with no distilled topics", () => {
    // Every topic on the dormant path has a null sentiment, so the totals
    // can legitimately be empty. Dividing by zero would give NaN widths.
    expect(moodSegments({})).toEqual([]);
  });
});

describe("foldNarrowSegments", () => {
  it("keeps every segment when each label fits its own width", () => {
    // 53%, 29% and 18% of a 662px column: 350px, 195px and 117px against
    // labels needing 58px, 46px and 63px.
    const folded = foldNarrowSegments(moodSegments({ funny: 9, cute: 5, mundane: 3 }));

    expect(folded.map((segment) => segment.label)).toEqual([
      "funny 9",
      "cute 5",
      "mundane 3",
    ]);
  });

  it("folds the sentiments too narrow for their labels into one others segment", () => {
    // The first three hold 51%, 12% and 10%, clearing the 10%, 8% and 10%
    // their labels need. `cringe 5` is the first to fail: 7% against 9%.
    const folded = foldNarrowSegments(
      moodSegments({
        outrage: 35,
        scary: 8,
        mundane: 7,
        cringe: 5,
        funny: 4,
        sad: 3,
        cute: 3,
        awe: 2,
        gross: 2,
      }),
    );

    expect(folded.map((segment) => segment.label)).toEqual([
      "outrage 35",
      "scary 8",
      "mundane 7",
      "+6 others",
    ]);
  });

  it("shows a lone narrow sentiment rather than folding it by itself", () => {
    // `awe 3` is 3% and does not fit. Folding it would replace a name and a
    // count with `+1 others`, which is wider and says less.
    const folded = foldNarrowSegments(moodSegments({ funny: 50, cute: 40, awe: 3 }));

    expect(folded.map((segment) => segment.label)).toEqual([
      "funny 50",
      "cute 40",
      "awe 3",
    ]);
  });

  it("folds a fitting segment in when the others label needs its width", () => {
    // cute and awe hold 8% between them, short of the 10% `+2 others`
    // needs, so `mundane 20` joins them despite fitting on its own.
    const folded = foldNarrowSegments(
      moodSegments({ outrage: 50, scary: 22, mundane: 20, cute: 4, awe: 4 }),
    );

    expect(folded.map((segment) => segment.label)).toEqual([
      "outrage 50",
      "scary 22",
      "+3 others",
    ]);
  });

  it("keeps the leader even when its own label does not fit", () => {
    // An eleven-way tie gives every sentiment 9%, and `heartwarming 3`
    // needs 14%. Folding every segment that fails would leave the bar a
    // single `+11 others`, which names nothing at all.
    //
    // Sorting equal counts is stable, so the leader is whichever sentiment
    // is listed first here.
    const tied = Object.fromEntries(
      [
        "heartwarming",
        "schadenfreude",
        "cute",
        "awe",
        "sad",
        "funny",
        "scary",
        "gross",
        "cringe",
        "mundane",
        "outrage",
      ].map((sentiment) => [sentiment, 3]),
    );

    const folded = foldNarrowSegments(moodSegments(tied));

    expect(folded.map((segment) => segment.label)).toEqual([
      "heartwarming 3",
      "+10 others",
    ]);
  });

  it("names the folded sentiments and counts in the others tooltip", () => {
    // The fold drops names off the bar, so the segment that replaces them
    // has to carry what it swallowed.
    const folded = foldNarrowSegments(moodSegments({ funny: 50, cute: 3, awe: 2 }));

    expect(folded.at(-1)?.title).toBe("cute 3, awe 2");
  });

  it("draws the others segment in the tail colour", () => {
    const folded = foldNarrowSegments(moodSegments({ funny: 50, cute: 3, awe: 2 }));

    expect(folded.at(-1)?.tone).toBe("rest");
  });

  it("returns nothing for a window with no distilled topics", () => {
    expect(foldNarrowSegments(moodSegments({}))).toEqual([]);
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
