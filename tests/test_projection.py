from tests.run_factory import make_dossier, make_topic
from zeitgeist.models import Register, Sentiment
from zeitgeist.projection import flatten


def test_every_topic_is_ranked_not_just_the_kept_ones():
    """The ranking screen draws below-the-cut rows with ranks and scores
    before dimming them, and the evaluate checkpoint holds only the top N."""
    topics = [
        make_topic("low", trend_score=0.1),
        make_topic("high", trend_score=0.9),
        make_topic("mid", trend_score=0.5),
    ]

    rows = flatten("r1", topics, meme_potential_weight=0.0)

    assert [row.topic_id for row in rows] == ["high", "mid", "low"]
    assert [row.final_rank for row in rows] == [1, 2, 3]


def test_ranking_uses_the_same_blend_the_pipeline_selects_with():
    """A second implementation of trend-versus-meme would drift silently, so
    the first top_count rows must agree with what select() chose."""
    dull_but_loud = make_topic(
        "loud", trend_score=1.0, dossier=make_dossier(meme_potential=0.0)
    )
    funny_but_quiet = make_topic(
        "funny", trend_score=0.0, dossier=make_dossier(meme_potential=1.0)
    )

    rows = flatten("r1", [dull_but_loud, funny_but_quiet], meme_potential_weight=0.9)

    assert rows[0].topic_id == "funny"


def test_a_topic_with_no_dossier_flattens_without_one():
    """dossier is None on the dormant path and on a stale checkpoint. The row
    still has to exist - the topic was ranked."""
    rows = flatten("r1", [make_topic("bare", dossier=None)], meme_potential_weight=0.3)

    [row] = rows
    assert row.event_sentiment is None
    assert row.meme_potential is None
    assert row.top_phrase is None


def test_the_top_phrase_is_the_one_with_the_most_distinct_authors():
    """Forty uses from three accounts is a dogpile; the ranking subline shows
    the phrase the most separate people reached for."""
    from zeitgeist.models import Phrase

    dossier = make_dossier(
        phrases=[
            Phrase(text="rare", occurrences=99, distinct_authors=2),
            Phrase(text="common", occurrences=10, distinct_authors=31),
        ]
    )

    [row] = flatten("r1", [make_topic(dossier=dossier)], meme_potential_weight=0.3)

    assert row.top_phrase == "common"
    assert row.top_phrase_authors == 31


def test_the_dossier_fields_land_in_their_matching_columns():
    """event_sentiment, conversation_register and meme_potential come from
    three different Dossier fields through the same
    `None if dossier is None else dossier.X` shape. Swapping two of those
    assignments would still read plausibly, so all three are pinned.

    Also covers the enum flattening: SQLite has no enum type and the API
    serialises these as strings.
    """
    dossier = make_dossier(
        event_sentiment=Sentiment.SCHADENFREUDE,
        conversation_register=Register.DUNKING,
        meme_potential=0.42,
    )

    [row] = flatten("r1", [make_topic(dossier=dossier)], meme_potential_weight=0.3)

    assert row.event_sentiment == "schadenfreude"
    assert row.conversation_register == "dunking"
    assert row.meme_potential == 0.42


def test_post_count_is_the_number_of_items_behind_the_topic():
    [row] = flatten(
        "r1",
        [make_topic(item_ids=["a", "b", "c"])],
        meme_potential_weight=0.3,
    )

    assert row.post_count == 3
