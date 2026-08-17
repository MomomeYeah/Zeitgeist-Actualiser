import json

import pytest

from zeitgeist.analysis.consolidate import ConsolidatedTopic, Consolidation
from zeitgeist.analysis.extract import PostTags, TagExtraction
from zeitgeist.analysis.sentiment import SentimentJudgement
from zeitgeist.config import Settings
from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.media.brief import BriefChoice
from zeitgeist.models import Sentiment
from zeitgeist.pipeline import Stage, run_pipeline
from zeitgeist.store import Store


class StubSource:
    name = "stub"

    def __init__(self, posts):
        self._posts = posts
        self.fetch_calls = 0

    def fetch(self, limit):
        self.fetch_calls += 1
        return self._posts[:limit]


@pytest.fixture
def settings(tmp_path):
    return Settings(
        reddit_client_id="id",
        reddit_client_secret="secret",
        anthropic_api_key="key",
        topic_count=1,
        output_dir=tmp_path / "output",
        db_path=tmp_path / "data" / "z.db",
    )


def _provider(posts):
    return FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    PostTags(post_id=post.source_id, tags=["cats"]) for post in posts
                ]
            ),
            Consolidation(
                topics=[
                    ConsolidatedTopic(
                        label="Cats", summary="Cat things.", tags=["cats"]
                    )
                ]
            ),
            SentimentJudgement(
                primary_sentiment=Sentiment.CUTE,
                secondary_sentiments=[],
                valence=0.8,
                meme_potential=0.9,
            ),
            BriefChoice(
                template_id="drake",
                caption_slots={"rejected": "Dogs", "preferred": "Cats"},
                rationale="Fits.",
            ),
        ]
    )


def _store(settings):
    store = Store(settings.db_path)
    store.init_schema()
    return store


def test_writes_every_checkpoint(settings, sample_posts):
    posts = sample_posts[:3]
    run_dir = run_pipeline(
        settings, StubSource(posts), _provider(posts), _store(settings), "run1"
    )
    for name in ("posts.json", "topics.json", "ranked.json", "briefs.json"):
        assert (run_dir / name).is_file()


def test_produces_a_png(settings, sample_posts):
    posts = sample_posts[:3]
    run_dir = run_pipeline(
        settings, StubSource(posts), _provider(posts), _store(settings), "run1"
    )
    assert list(run_dir.glob("*.png"))


def test_records_the_run_in_the_store(settings, sample_posts):
    posts = sample_posts[:3]
    store = _store(settings)
    run_pipeline(settings, StubSource(posts), _provider(posts), store, "run1")
    assert store.previous_scores(exclude_run_id="run2") != {}


def test_resume_from_generate_skips_scraping(settings, sample_posts):
    posts = sample_posts[:3]
    source = StubSource(posts)
    run_pipeline(settings, source, _provider(posts), _store(settings), "run1")
    assert source.fetch_calls == 1

    provider = FakeLLMProvider(
        [
            BriefChoice(
                template_id="drake",
                caption_slots={"rejected": "Cats", "preferred": "Dogs"},
                rationale="Retuned.",
            )
        ]
    )
    run_pipeline(
        settings,
        source,
        provider,
        _store(settings),
        "run1",
        start_at=Stage.GENERATE,
    )
    assert source.fetch_calls == 1


def test_resume_without_checkpoint_raises(settings, sample_posts):
    with pytest.raises(FileNotFoundError):
        run_pipeline(
            settings,
            StubSource(sample_posts),
            FakeLLMProvider(),
            _store(settings),
            "never-ran",
            start_at=Stage.GENERATE,
        )


def test_a_failing_stage_degrades_rather_than_killing_the_run(settings, sample_posts):
    """The spec's central error rule: fewer memes is a success, no output is
    a failure. One topic's sentiment call fails; the other must still reach
    a rendered PNG.
    """
    posts = sample_posts[:3]
    provider = FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    PostTags(post_id=post.source_id, tags=["cats"]) for post in posts
                ]
            ),
            Consolidation(
                topics=[
                    ConsolidatedTopic(
                        label="Cats", summary="Cat things.", tags=["cats"]
                    ),
                    ConsolidatedTopic(
                        label="Dogs", summary="Dog things.", tags=["cats"]
                    ),
                ]
            ),
            LLMError("sentiment call failed"),
            SentimentJudgement(
                primary_sentiment=Sentiment.CUTE,
                secondary_sentiments=[],
                valence=0.8,
                meme_potential=0.9,
            ),
            BriefChoice(
                template_id="drake",
                caption_slots={"rejected": "Dogs", "preferred": "Cats"},
                rationale="Fits.",
            ),
        ]
    )
    run_dir = run_pipeline(
        settings.model_copy(update={"topic_count": 2}),
        StubSource(posts),
        provider,
        _store(settings),
        "run1",
    )

    ranked = json.loads((run_dir / "ranked.json").read_text(encoding="utf-8"))
    assert [entry["label"] for entry in ranked] == ["Dogs"]
    assert len(list(run_dir.glob("*.png"))) == 1


def test_checkpoints_are_valid_json(settings, sample_posts):
    posts = sample_posts[:3]
    run_dir = run_pipeline(
        settings, StubSource(posts), _provider(posts), _store(settings), "run1"
    )
    ranked = json.loads((run_dir / "ranked.json").read_text(encoding="utf-8"))
    assert ranked[0]["primary_sentiment"] == "cute"
    assert ranked[0]["final_rank"] == 1
