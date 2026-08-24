from datetime import UTC, date, datetime
from typing import Literal

import pytest

from zeitgeist.analysis.score import score_topics
from zeitgeist.analysis.scorers.base import ScoreWeights
from zeitgeist.models import BlueskyMetrics, Item, LemmyMetrics, Topic, WikipediaMetrics

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
DAY = date(2026, 8, 20)

# Aliased because `status: str` does not type-check against BlueskyMetrics'
# Literal field, and ty covers tests/ as part of the definition of done.
Status = Literal["trending", "cooling", "stale"]


def _lemmy(source_id: str, score: int, channel: str, age_hours: float) -> Item:
    return Item(
        source_id=source_id,
        title=f"Post {source_id}",
        permalink=f"https://lemmy.world/post/{source_id}",
        fetched_at=NOW,
        metrics=LemmyMetrics(
            score=score,
            comment_count=score // 10,
            channel=channel,
            created_at=datetime.fromtimestamp(
                NOW.timestamp() - age_hours * 3600, tz=UTC
            ),
        ),
    )


def _wiki(source_id: str, rank: int) -> Item:
    return Item(
        source_id=source_id,
        title=f"Article {source_id}",
        permalink=f"https://en.wikipedia.org/wiki/{source_id}",
        fetched_at=NOW,
        metrics=WikipediaMetrics(views=100_000 - rank, rank=rank, measured_on=DAY),
    )


def _bluesky(
    source_id: str,
    likes: int,
    trend: str,
    age_hours: float,
    status: Status = "trending",
) -> Item:
    return Item(
        source_id=source_id,
        title=f"Post {source_id}",
        permalink=f"https://bsky.app/profile/did:plc:x/post/{source_id}",
        fetched_at=NOW,
        metrics=BlueskyMetrics(
            like_count=likes,
            reply_count=likes // 10,
            repost_count=likes // 20,
            trend=trend,
            status=status,
            created_at=datetime.fromtimestamp(
                NOW.timestamp() - age_hours * 3600, tz=UTC
            ),
        ),
    )


def _topic(topic_id: str, item_ids: list[str]) -> Topic:
    return Topic(id=topic_id, label=topic_id.title(), summary="", item_ids=item_ids)


def _two_topics_one_corroborated() -> tuple[list[Topic], list[Item]]:
    """Hand-derived so the corroboration bonus is load-bearing.

    Lemmy velocities normalise to [1.0, 0.9, 0.0] and the two leading topics
    each span two channels, so bases are [1.0, 0.93, 0.0] and — with no
    history, so the delta term contributes nothing — the lemmy sub-scores
    are 0.75 * base:
        solo          0.75
        corroborated  0.6975
    Wikipedia ranks 3 and 800 normalise to [1.0, 0.0], so corroborated's
    wikipedia sub-score is 0.75 and its mean is 0.72375 — BELOW solo's 0.75.
    Only the x1.25 bonus (0.9046875) puts it ahead, which is what makes a
    zeroed bonus fail rather than merely shrink the gap.
    """
    items = [
        _lemmy("s1", score=1000, channel="a@h", age_hours=2),
        _lemmy("s2", score=1000, channel="b@h", age_hours=2),
        _lemmy("c1", score=910, channel="c@h", age_hours=2),
        _lemmy("c2", score=910, channel="d@h", age_hours=2),
        _lemmy("f1", score=100, channel="e@h", age_hours=2),
        _wiki("w1", rank=3),
        _wiki("w2", rank=800),
    ]
    topics = [
        _topic("solo", ["s1", "s2"]),
        _topic("corroborated", ["c1", "c2", "w1"]),
        _topic("filler", ["f1", "w2"]),
    ]
    return topics, items


def _history_case() -> tuple[list[Topic], list[Item]]:
    """Three Lemmy-only topics whose velocities normalise to [1.0, 0.9, 0.0],
    so bases are [0.7, 0.63, 0.0]. Labels are two words on purpose: the
    lookup key slugify("Rising Star") == "rising-star" differs from both the
    raw label and the topic id, so a lookup on either finds nothing.
    """
    items = [
        _lemmy("a", score=1000, channel="a@h", age_hours=2),
        _lemmy("b", score=910, channel="b@h", age_hours=2),
        _lemmy("c", score=100, channel="c@h", age_hours=2),
    ]
    topics = [
        Topic(id="steady", label="Steady Eddie", summary="", item_ids=["a"]),
        Topic(id="rising", label="Rising Star", summary="", item_ids=["b"]),
        Topic(id="quiet", label="Quiet One", summary="", item_ids=["c"]),
    ]
    return topics, items


def _one_survivor_among_six() -> tuple[list[Topic], list[Item]]:
    """One content-bearing topic that Wikipedia also saw, plus five
    Wikipedia-only topics that the filter drops. The survivor's Wikipedia
    sub-score must be computed against all six.
    """
    items = [_lemmy("L", score=500, channel="a@h", age_hours=2), _wiki("w0", rank=2)]
    topics = [_topic("survivor", ["L", "w0"])]
    for n in range(1, 6):
        items.append(_wiki(f"w{n}", rank=100 * n))
        topics.append(_topic(f"dropped-{n}", [f"w{n}"]))
    return topics, items


def _wikipedia_only_topic() -> tuple[list[Topic], list[Item]]:
    items = [_wiki("w1", rank=1), _wiki("w2", rank=2)]
    return [_topic("wiki-a", ["w1"]), _topic("wiki-b", ["w2"])], items


def _single_contribution_case() -> tuple[list[Topic], list[Item]]:
    """Wikipedia appears in exactly one topic, so it cannot be min-max
    normalised — but its presence must still earn the corroboration bonus.
    """
    items = [
        _lemmy("l1", score=700, channel="a@h", age_hours=2),
        _lemmy("l2", score=300, channel="b@h", age_hours=2),
        _wiki("w1", rank=5),
    ]
    topics = [
        _topic("solo-corroborated", ["l1", "w1"]),
        _topic("plain", ["l2"]),
    ]
    return topics, items


def _lemmy_and_bluesky_corroborated() -> tuple[list[Topic], list[Item]]:
    """Mirrors `_two_topics_one_corroborated` with Bluesky standing in for
    Wikipedia, so the coordinator is exercised with all three platforms in
    play rather than Bluesky running alone. Two Bluesky items land in
    different topics so Bluesky clears MIN_TOPICS_TO_RANK and actually
    contributes a sub-score rather than only counting toward corroboration.
    """
    items = [
        _lemmy("s1", score=1000, channel="a@h", age_hours=2),
        _lemmy("s2", score=1000, channel="b@h", age_hours=2),
        _lemmy("c1", score=910, channel="c@h", age_hours=2),
        _lemmy("c2", score=910, channel="d@h", age_hours=2),
        _lemmy("f1", score=100, channel="e@h", age_hours=2),
        _bluesky("b1", likes=1000, trend="Trend A", age_hours=2),
        _bluesky("b2", likes=10, trend="Trend B", age_hours=2),
    ]
    topics = [
        _topic("solo", ["s1", "s2"]),
        _topic("corroborated", ["c1", "c2", "b1"]),
        _topic("filler", ["f1", "b2"]),
    ]
    return topics, items


def _bluesky_only_topics() -> tuple[list[Topic], list[Item]]:
    items = [
        _bluesky("b1", likes=1000, trend="A", age_hours=2),
        _bluesky("b2", likes=10, trend="B", age_hours=2),
    ]
    return [_topic("bsky-a", ["b1"]), _topic("bsky-b", ["b2"])], items


def _lemmy_only_run() -> tuple[list[Topic], list[Item]]:
    items = [
        _lemmy("fast", score=1000, channel="a@h", age_hours=1),
        _lemmy("medium", score=300, channel="b@h", age_hours=3),
        _lemmy("slow", score=20, channel="c@h", age_hours=20),
    ]
    topics = [
        _topic("fast", ["fast"]),
        _topic("medium", ["medium"]),
        _topic("slow", ["slow"]),
    ]
    return topics, items


def test_corroboration_makes_two_platforms_beat_one_stronger_platform():
    """`solo` outscores `corroborated` on the mean of their sub-scores
    (0.75 vs 0.72375); only the two-platform multiplier reverses that. Both
    values are hand-derived in the builder's docstring, so zeroing the bonus
    or dropping the `* bonus` from trend_score fails here.
    """
    topics, items = _two_topics_one_corroborated()

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    by_id = {t.id: t for t in scored}
    assert by_id["solo"].trend_score == pytest.approx(0.75)
    assert by_id["corroborated"].trend_score == pytest.approx(0.9046875)
    assert by_id["corroborated"].trend_score > by_id["solo"].trend_score


def test_history_is_looked_up_by_platform_then_label_slug():
    """Hand-derived: bases are [0.7, 0.63, 0.0]. `steady`'s history equals
    its own base, so it has not risen (raw delta 0.0); `rising` climbed from
    0.0 (raw delta 0.63). Normalised deltas are [0.0, 1.0, 0.0] and the
    scores are 0.525 / 0.7225 / 0.0, so `rising` overtakes `steady`.

    This is the only test joining Store.previous_sub_scores to the scorers'
    `previous` list. A lookup keyed on the raw label, on topic.id, or without
    the platform level finds nothing: every delta is then zero and `steady`
    stays ahead at 0.525 against 0.4725.
    """
    topics, items = _history_case()
    previous = {"lemmy": {"steady-eddie": 0.7, "rising-star": 0.0}}

    scored = {
        t.id: t
        for t in score_topics(topics, items, NOW, previous, weights=ScoreWeights())
    }

    assert scored["rising"].trend_score == pytest.approx(0.7225)
    assert scored["steady"].trend_score == pytest.approx(0.525)
    assert scored["rising"].trend_score > scored["steady"].trend_score


def test_scoring_precedes_the_content_bearing_filter():
    """A corroboration-only platform sees six topics, five of which are
    dropped for having no content-bearing source. The survivor's sub-score
    must be computed against all six, not against itself alone.

    Written to fail against the reversed ordering: filtering first leaves the
    scorer a single value, and min-max over one value is 0.0, so the
    corroborating platform would drag the topic DOWN instead of lifting it.
    """
    topics, items = _one_survivor_among_six()

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    assert len(scored) == 1
    assert scored[0].score_components["wikipedia"] > 0.0


def test_a_topic_referencing_an_unknown_item_is_dropped_not_fatal():
    """Consolidation works from model-supplied tags and can name an id no
    source produced — tests/test_analysis_extract.py proves that happens.
    The lookup must skip it: indexing by_id directly turns one hallucinated
    id into a KeyError that ends the run after the fetch and every LLM call
    have already been paid for.
    """
    items = [_lemmy("a", score=100, channel="a@h", age_hours=2)]
    topics = [_topic("real", ["a"]), _topic("ghost", ["missing"])]

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    assert [t.id for t in scored] == ["real"]


def test_topics_with_no_content_bearing_platform_are_dropped():
    topics, items = _wikipedia_only_topic()

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    assert scored == []


def test_a_platform_seen_in_one_topic_is_excluded_from_the_mean():
    """Its min-max carries no information, so it must not enter the average —
    but it still counts toward the corroboration multiplier."""
    topics, items = _single_contribution_case()

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    target = next(t for t in scored if t.id == "solo-corroborated")
    assert "wikipedia" not in target.score_components
    assert target.score_components["corroboration"] == 1.25


def test_score_components_name_every_contributing_platform():
    """Store.record_topics turns these keys into topic_scores rows, so a
    platform missing here loses its cross-run history and its rank-delta
    goes inert. Exact set, not a superset: dropping the corroborating
    platform is the mutation that matters, and a superset check would let
    it through.
    """
    topics, items = _two_topics_one_corroborated()

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    corroborated = next(t for t in scored if t.id == "corroborated")
    assert set(corroborated.score_components) == {
        "lemmy",
        "wikipedia",
        "corroboration",
    }


def test_single_platform_run_matches_phase_one_ranking():
    """Equivalence gate: with one content-bearing source and no corroboration,
    the coordinator must rank identically to the pre-refactor scorer. Compares
    ORDER, not absolute values, since the bonus multiplies uniformly by 1.0."""
    topics, items = _lemmy_only_run()

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    order = [t.id for t in sorted(scored, key=lambda t: -t.trend_score)]
    assert order == ["fast", "medium", "slow"]


def test_a_topic_corroborated_across_bluesky_and_lemmy_earns_both_sub_scores():
    """Coordinator-level check that the newest platform combines with another
    platform's sub-score rather than only ever being exercised alone —
    mirrors test_score_components_name_every_contributing_platform's
    Wikipedia case with Bluesky instead.
    """
    topics, items = _lemmy_and_bluesky_corroborated()

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    corroborated = next(t for t in scored if t.id == "corroborated")
    assert set(corroborated.score_components) == {"lemmy", "bluesky", "corroboration"}
    assert corroborated.score_components["corroboration"] == 1.25
    assert corroborated.trend_score > 0.0


def test_a_bluesky_only_topic_survives_the_content_bearing_filter():
    """Unlike Wikipedia (test_topics_with_no_content_bearing_platform_are_dropped),
    a Bluesky post carries its own text, so a topic Bluesky is the only
    platform for must survive score_topics's content-bearing filter rather
    than being dropped.
    """
    topics, items = _bluesky_only_topics()

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    assert {t.id for t in scored} == {"bsky-a", "bsky-b"}
