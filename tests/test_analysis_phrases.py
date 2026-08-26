"""Recurring-phrase mining.

Deterministic on purpose. A model asked for catchphrases invents plausible
ones; the counts here are what license quoting a phrase in a caption, so
they have to be measured.
"""

from datetime import UTC, datetime

from zeitgeist.analysis.phrases import mine_phrases
from zeitgeist.models import Reply, TrendInfo

TREND = TrendInfo(
    topic_id="t1",
    display_name="Canada announces retaliatory tariffs",
    description="Canada hits back after trade talks collapsed.",
    category="business",
    post_count=4298,
    started_at=datetime(2026, 8, 26, tzinfo=UTC),
    status="stale",
)


def _replies(*pairs: tuple[str, str]) -> list[Reply]:
    """Each pair is (author_key, text)."""
    return [
        Reply(
            text=text,
            like_count=0,
            created_at=datetime(2026, 8, 26, tzinfo=UTC),
            author_key=author,
        )
        for author, text in pairs
    ]


def _texts(phrases) -> list[str]:
    return [phrase.text for phrase in phrases]


def test_a_phrase_many_people_use_is_mined():
    replies = _replies(
        ("a", "elbows up everyone"),
        ("b", "elbows up"),
        ("c", "time for elbows up"),
        ("d", "elbows up finally"),
    )
    result = mine_phrases(replies, TREND, min_authors=3)
    assert "elbows up" in _texts(result)


def test_counts_report_occurrences_and_distinct_authors_separately():
    """The two numbers must differ here, or reporting one in place of the
    other passes. One account uses the phrase in two separate replies, so
    four uses come from three people.
    """
    replies = _replies(
        ("a", "elbows up"),
        ("a", "elbows up again"),
        ("b", "elbows up"),
        ("c", "elbows up"),
    )
    [phrase] = [
        p for p in mine_phrases(replies, TREND, min_authors=3) if p.text == "elbows up"
    ]
    assert phrase.occurrences == 4
    assert phrase.distinct_authors == 3


def test_a_phrase_repeated_by_few_accounts_is_excluded():
    """Forty uses from three accounts is a dogpile, not a zeitgeist. This is
    the test the whole distinct-author count exists for.
    """
    replies = _replies(*[(f"a{i % 3}", "buy my coin now") for i in range(40)])
    result = mine_phrases(replies, TREND, min_authors=4)
    assert "buy my coin" not in _texts(result)


def test_one_person_repeating_a_phrase_counts_once():
    replies = _replies(
        ("a", "elbows up elbows up elbows up elbows up"),
        ("b", "elbows up"),
        ("c", "elbows up"),
    )
    [phrase] = [
        p for p in mine_phrases(replies, TREND, min_authors=3) if p.text == "elbows up"
    ]
    assert phrase.occurrences == 3
    assert phrase.distinct_authors == 3


def test_substring_collapse_keeps_the_longer_phrase():
    """Almost everyone who said the short form said the long form, so the
    long form is the phrase.
    """
    replies = _replies(
        ("a", "support the imagination library"),
        ("b", "the imagination library forever"),
        ("c", "donate to the imagination library"),
        ("d", "the imagination library is her legacy"),
    )
    result = _texts(mine_phrases(replies, TREND, min_authors=3))
    assert "the imagination library" in result
    assert "imagination library" not in result


def test_substring_collapse_keeps_the_shorter_when_the_longer_is_a_variant():
    """Only a minority attached the longer form, so the short phrase is the
    widely-used one and the long form is one sub-community's variant.

    Both must survive. Five accounts said "elbows up"; three of those added
    "canada". 3 < 0.8 * 5, so the short form is not absorbed.
    """
    replies = _replies(
        ("a", "elbows up canada"),
        ("b", "elbows up canada"),
        ("c", "elbows up canada"),
        ("d", "elbows up"),
        ("e", "elbows up"),
    )
    result = _texts(mine_phrases(replies, TREND, min_authors=3))
    assert "elbows up" in result
    assert "elbows up canada" in result


def test_the_subject_of_the_trend_is_not_a_catchphrase():
    """ "retaliatory tariffs" in two hundred replies is what the trend is
    about, not something people coined.
    """
    replies = _replies(
        ("a", "retaliatory tariffs at last"),
        ("b", "retaliatory tariffs were overdue"),
        ("c", "about time for retaliatory tariffs"),
    )
    assert "retaliatory tariffs" not in _texts(
        mine_phrases(replies, TREND, min_authors=3)
    )


def test_phrases_from_the_trend_description_are_also_excluded():
    replies = _replies(
        ("a", "trade talks collapsed again"),
        ("b", "trade talks collapsed"),
        ("c", "so the trade talks collapsed"),
    )
    assert "trade talks collapsed" not in _texts(
        mine_phrases(replies, TREND, min_authors=3)
    )


def test_all_stopword_phrases_are_excluded():
    replies = _replies(
        ("a", "this is the one"),
        ("b", "this is the one"),
        ("c", "this is the one"),
    )
    assert "is the" not in _texts(mine_phrases(replies, TREND, min_authors=3))


def test_urls_and_mentions_are_stripped_before_mining():
    """All three authors carry both, so the noise grams clear min_authors if
    they survive. Punctuation removal alone does not catch them: it turns a
    URL into ordinary words rather than dropping it — which is why asserting
    on the absence of "@" or "http" proves nothing.
    """
    replies = _replies(
        ("a", "@someone.bsky.social elbows up https://example.com/one"),
        ("b", "@someone.bsky.social elbows up https://example.com/two"),
        ("c", "@someone.bsky.social elbows up https://example.com/three"),
    )
    result = _texts(mine_phrases(replies, TREND, min_authors=3))
    assert "elbows up" in result
    assert "https example com" not in result
    assert "someone bsky social" not in result


def test_no_replies_yields_no_phrases():
    assert mine_phrases([], TREND, min_authors=3) == []


def test_results_are_ranked_by_distinct_authors():
    """Literal, not `sorted(result)`: comparing the output against itself is
    also true of a one-element or empty list, so a collapse regression that
    swallowed the second phrase would pass.
    """
    replies = _replies(
        ("a", "elbows up"),
        ("b", "elbows up"),
        ("c", "elbows up"),
        ("d", "elbows up"),
        ("a", "maple syrup diplomacy"),
        ("b", "maple syrup diplomacy"),
        ("c", "maple syrup diplomacy"),
    )
    result = mine_phrases(replies, TREND, min_authors=3)
    assert _texts(result) == ["elbows up", "maple syrup diplomacy"]
    assert [p.distinct_authors for p in result] == [4, 3]


def test_top_limits_the_result_size():
    replies = _replies(
        *[
            (author, f"phrase number {index} here")
            for index in range(20)
            for author in ("a", "b", "c")
        ]
    )
    assert len(mine_phrases(replies, TREND, min_authors=3, top=5)) == 5
