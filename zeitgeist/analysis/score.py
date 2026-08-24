"""Trend scoring coordinator.

Each platform scores its own contribution to a topic, normalised within that
platform; this module dispatches to those scorers and combines what they
return. Keeping the arithmetic here pure — no I/O, no LLM — is deliberate:
it is reproducible and unit-testable, which an LLM's numeric judgment is not.
"""

from datetime import datetime

from zeitgeist.analysis.consolidate import slugify
from zeitgeist.analysis.scorers import build_scorer
from zeitgeist.analysis.scorers.base import ScoreWeights
from zeitgeist.models import Item, Topic

__all__ = ["ScoreWeights", "score_topics"]

# A platform contributing to fewer topics than this cannot be min-max
# normalised: the range is degenerate. Its presence still counts toward
# corroboration, but it contributes no number to the mean.
MIN_TOPICS_TO_RANK = 2


def score_topics(
    topics: list[Topic],
    items: list[Item],
    now: datetime,
    previous: dict[str, dict[str, float]],
    weights: ScoreWeights | None = None,
) -> list[Topic]:
    """Attach a trend score and its component breakdown to each topic.

    `previous` is keyed platform -> slugify(label) -> sub-score (see
    ``Store.previous_sub_scores``), not the raw label, so a topic relabelled
    with different case or punctuation across runs still finds its history.
    """
    weights = weights or ScoreWeights()
    by_id = {item.source_id: item for item in items}

    live: list[tuple[Topic, list[Item]]] = []
    for topic in topics:
        matched = [by_id[iid] for iid in topic.item_ids if iid in by_id]
        if matched:
            live.append((topic, matched))

    if not live:
        return []

    platforms = sorted({item.platform for _, group in live for item in group})

    # Step 2 of the spec's ordering: score across ALL live topics, before the
    # content-bearing filter runs. Filtering first would hand a scorer a single
    # value, and min-max over one value is 0.0 — so a corroborating platform
    # would penalise the topic it is meant to lift.
    presence: dict[str, list[bool]] = {}
    scores: dict[str, list[float | None]] = {}

    for platform in platforms:
        groups = [
            [item.metrics for item in group if item.platform == platform]
            for _, group in live
        ]
        presence[platform] = [bool(g) for g in groups]
        scores[platform] = [None] * len(live)

        present = [i for i, g in enumerate(groups) if g]
        if len(present) < MIN_TOPICS_TO_RANK:
            continue

        scorer = build_scorer(platform, weights, now)
        values = scorer.score(
            per_topic=[groups[i] for i in present],
            previous=[
                previous.get(platform, {}).get(slugify(live[i][0].label))
                for i in present
            ],
        )
        for position, index in enumerate(present):
            scores[platform][index] = values[position]

    scored: list[Topic] = []
    for index, (topic, group) in enumerate(live):
        if not any(item.content_bearing for item in group):
            continue

        contributing = [p for p in platforms if presence[p][index]]
        # Built with an explicit loop rather than a comprehension: ty does not
        # narrow `float | None` away across a repeated subscript expression,
        # so binding the value to a local is what makes `ranked` a
        # dict[str, float] and keeps `sum` well-typed.
        ranked: dict[str, float] = {}
        for platform in contributing:
            value = scores[platform][index]
            if value is not None:
                ranked[platform] = value

        # Averaging sub-scores across platforms assumes they share a scale.
        # That holds for every platform whose movement term is min-max
        # normalised — normalisation is relative, so it forces some topic to
        # 0.0 and some to 1.0 and cannot lift a whole platform.
        #
        # Bluesky is the deliberate exception. It reports movement itself
        # (`trending`/`saturating`/`cooling`/`stale`) and BlueskyScorer uses
        # that raw, because min-max over a status every trend shares would
        # collapse to zeros and silence the axis exactly when the platform is
        # most confident. The cost is that Bluesky's sub-scores are shifted up
        # by `rank_delta * status` when its topics all share a status: a
        # uniformly `trending` run floors them at 0.25 where Lemmy's floor is
        # 0.0. Bounded by rank_delta, and absent as soon as statuses vary,
        # which live data says is the normal case — but it is a real thumb on
        # the scale here, in the one place platforms are compared.
        mean = sum(ranked.values()) / len(ranked) if ranked else 0.0
        bonus = 1.0 + weights.corroboration_bonus * (len(contributing) - 1)

        components: dict[str, float] = dict(ranked)
        components["corroboration"] = bonus

        scored.append(
            topic.model_copy(
                update={"trend_score": mean * bonus, "score_components": components}
            )
        )

    return scored
