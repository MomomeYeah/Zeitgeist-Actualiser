"""Slug helpers, shared by the live distillation path and dormant consolidation."""

from zeitgeist.analysis.slug import slugify, unique_slug


def test_slugify_lowercases_and_hyphenates():
    assert slugify("Canada Announces Retaliatory Tariffs") == (
        "canada-announces-retaliatory-tariffs"
    )


def test_slugify_collapses_runs_of_punctuation_to_one_hyphen():
    assert slugify("Trump: 'renaming' Lake Ontario!!") == (
        "trump-renaming-lake-ontario"
    )


def test_slugify_falls_back_when_nothing_survives():
    assert slugify("!!! ???") == "topic"


def test_unique_slug_suffixes_collisions_and_records_them():
    used: set[str] = set()
    assert unique_slug("A Trend", used) == "a-trend"
    assert unique_slug("A Trend", used) == "a-trend-2"
    assert unique_slug("A Trend", used) == "a-trend-3"
    assert used == {"a-trend", "a-trend-2", "a-trend-3"}
