import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from zeitgeist.analysis.distil import DossierDraft
from zeitgeist.config import Settings
from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.media.brief import BriefChoice
from zeitgeist.media.templates import TemplateError
from zeitgeist.models import (
    BlueskyMetrics,
    Item,
    PostEvidence,
    Register,
    Reply,
    Sentiment,
    TrendEvidence,
    TrendInfo,
)
from zeitgeist.pipeline import Stage, run_pipeline
from zeitgeist.store import Store

NOW = datetime(2026, 8, 26, tzinfo=UTC)

TEMPLATE_A = "shape_alpha"
TEMPLATE_B = "shape_beta"


class _FakeTrendSource:
    name = "bluesky"

    def __init__(self, evidence: list[TrendEvidence]) -> None:
        self._evidence = evidence
        self.calls = 0

    def fetch_evidence(self, settings: Settings) -> list[TrendEvidence]:
        self.calls += 1
        return list(self._evidence)


def _template_library(tmp_path) -> Path:
    """Two synthetic templates the tests own outright.

    The pipeline never reads the shipped library here, so templates can be
    added or retired without breaking these tests. What ships is covered by
    validate_templates in test_media_templates.py.
    """
    directory = tmp_path / "templates"
    directory.mkdir(parents=True, exist_ok=True)
    for tid in (TEMPLATE_A, TEMPLATE_B):
        Image.new("RGB", (200, 200), "white").save(directory / f"{tid}.png")
        (directory / f"{tid}.json").write_text(
            json.dumps(
                {
                    "id": tid,
                    "image": f"{tid}.png",
                    "shape": f"the {tid} shape",
                    "slots": [
                        {
                            "name": "rejected",
                            "box": [10, 10, 190, 90],
                            "max_chars": 40,
                        },
                        {
                            "name": "preferred",
                            "box": [10, 110, 190, 190],
                            "max_chars": 40,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
    return directory


def _settings(tmp_path, **overrides: Any) -> Settings:
    base: dict[str, Any] = dict(
        sources=["bluesky"],
        distil_concurrency=1,
        topic_count=1,
        output_dir=tmp_path / "output",
        db_path=tmp_path / "data" / "z.db",
        templates_dir=_template_library(tmp_path),
    )
    return Settings(**(base | overrides))


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "data" / "z.db")
    store.init_schema()
    return store


def _item(source_id: str, text: str = "something happened") -> Item:
    return Item(
        source_id=source_id,
        title=text,
        permalink=f"https://bsky.app/profile/x/post/{source_id}",
        fetched_at=NOW,
        metrics=BlueskyMetrics(
            like_count=10,
            reply_count=2,
            repost_count=1,
            trend="A trend",
            status="trending",
            created_at=NOW,
        ),
    )


def _reply(text: str, author: str = "a", likes: int = 1) -> Reply:
    return Reply(text=text, like_count=likes, created_at=NOW, author_key=author)


def _evidence(
    name: str = "A trend",
    *,
    replies: list[Reply] | None = None,
    posts: int = 1,
) -> TrendEvidence:
    return TrendEvidence(
        trend=TrendInfo(
            topic_id=f"id-{name}",
            display_name=name,
            description="Something happened.",
            category="business",
            post_count=4298,
            started_at=NOW,
            status="stale",
        ),
        posts=[
            PostEvidence(
                item=_item(f"p{i}"),
                replies=replies if replies is not None else [_reply("what a mess")],
            )
            for i in range(posts)
        ],
    )


def _draft(**overrides: Any) -> DossierDraft:
    base: dict[str, Any] = {
        "what_happened": "Canada imposed tariffs on $30B of US goods.",
        "key_entities": ["Canada"],
        "conversation_summary": "People treat it as overdue.",
        "conversation_register": Register.DUNKING,
        "secondary_registers": [],
        "event_sentiment": Sentiment.SCHADENFREUDE,
        "meme_potential": 0.8,
    }
    return DossierDraft(**(base | overrides))


def _choice(**overrides: Any) -> BriefChoice:
    base: dict[str, Any] = dict(
        template_id=TEMPLATE_A,
        caption_slots={"rejected": "Dogs", "preferred": "Cats"},
        rationale="Fits.",
    )
    return BriefChoice(**(base | overrides))


def test_ingest_writes_evidence_and_analyse_reads_it(tmp_path):
    """The checkpoint boundary the whole design turns on: everything
    expensive lands before topics.json, so brief tuning re-runs in seconds.
    """
    settings = _settings(tmp_path)
    run_dir = run_pipeline(
        settings=settings,
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=_store(tmp_path),
        run_id="r1",
    )
    payload = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
    assert payload[0]["trend"]["display_name"] == "A trend"
    assert payload[0]["posts"][0]["replies"][0]["text"] == "what a mess"


def test_topics_json_carries_the_dossier(tmp_path):
    run_dir = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=_store(tmp_path),
        run_id="r1",
    )
    [topic] = json.loads((run_dir / "topics.json").read_text(encoding="utf-8"))
    assert topic["dossier"]["conversation_register"] == "dunking"
    assert topic["summary"] == "Canada imposed tariffs on $30B of US goods."


def test_ranked_json_carries_the_selected_topic_and_its_dossier(tmp_path):
    """ranked.json is what --resume-from generate reads back, so a break in
    its serialisation (the wrong field written, final_rank mis-numbered)
    would only surface as a confusing failure two stages later. Parsed as
    raw JSON rather than through ScoredTopic.model_validate, so a
    serialisation-level break is visible here rather than papered over by
    the schema filling in a default.
    """
    run_dir = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=_store(tmp_path),
        run_id="r1",
    )
    [topic] = json.loads((run_dir / "ranked.json").read_text(encoding="utf-8"))
    assert topic["final_rank"] == 1
    assert topic["dossier"]["conversation_register"] == "dunking"


def test_resuming_from_analyse_does_not_refetch(tmp_path):
    settings = _settings(tmp_path)
    source = _FakeTrendSource([_evidence()])
    run_pipeline(
        settings=settings,
        source=source,
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=_store(tmp_path),
        run_id="r1",
    )
    assert source.calls == 1

    run_pipeline(
        settings=settings,
        source=source,
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=_store(tmp_path),
        run_id="r1",
        start_at=Stage.ANALYSE,
    )
    assert source.calls == 1


def test_item_count_reflects_the_posts_under_every_trend(tmp_path):
    store = _store(tmp_path)
    run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence(posts=3)]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )
    assert (store.run_summary("r1") or {})["item_count"] == 3


def test_the_ingest_checkpoint_round_trips_through_trend_evidence(tmp_path):
    """Checkpoint JSON must deserialise back to the concrete metrics class
    with its values intact, or --resume-from silently produces
    differently-shaped evidence than the run that wrote them.
    """
    run_dir = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=_store(tmp_path),
        run_id="r1",
    )

    raw = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
    restored = [TrendEvidence.model_validate(entry) for entry in raw]

    metrics = restored[0].posts[0].item.metrics
    assert isinstance(metrics, BlueskyMetrics)
    assert metrics.trend == "A trend"
    assert metrics.like_count == 10


def test_produces_a_png(tmp_path):
    run_dir = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=_store(tmp_path),
        run_id="r1",
    )
    assert list(run_dir.glob("*.png"))


def test_records_the_run_in_the_store(tmp_path):
    """Guards both that the run row is recorded (start_run/finish_run) and
    that the pipeline's topics are persisted (record_topics). A single topic
    can't be min-max normalised (score.py's MIN_TOPICS_TO_RANK), so it earns
    no topic_scores row -- the topics table is the one to check.
    """
    store = _store(tmp_path)
    run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    summary = store.run_summary("r1")
    assert summary is not None
    assert summary["status"] == "ok"

    rows = store._conn.execute(
        "SELECT label FROM topics WHERE run_id = ?", ("r1",)
    ).fetchall()
    assert rows == [("a-trend",)]


def test_resume_from_generate_reuses_ranked_topics(tmp_path):
    settings = _settings(tmp_path)
    source = _FakeTrendSource([_evidence()])
    run_pipeline(
        settings=settings,
        source=source,
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=_store(tmp_path),
        run_id="r1",
    )
    assert source.calls == 1

    run_pipeline(
        settings=settings,
        source=source,
        provider=FakeLLMProvider(responses=[_choice(rationale="Retuned.")]),
        store=_store(tmp_path),
        run_id="r1",
        start_at=Stage.GENERATE,
    )
    assert source.calls == 1


def test_resume_without_checkpoint_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_pipeline(
            settings=_settings(tmp_path),
            source=_FakeTrendSource([_evidence()]),
            provider=FakeLLMProvider(),
            store=_store(tmp_path),
            run_id="never-ran",
            start_at=Stage.ANALYSE,
        )


def test_a_failing_stage_degrades_rather_than_killing_the_run(tmp_path):
    """The spec's central error rule: fewer memes is a success, no output is
    a failure. Selection no longer drops topics on an LLM failure -- brief
    generation still can, so that is where this exercises the degrade path.
    One topic's brief call fails; the other must still reach a rendered PNG.
    """
    evidence = [_evidence("First"), _evidence("Second")]
    provider = FakeLLMProvider(
        responses=[_draft(), _draft(), LLMError("brief call failed"), _choice()]
    )
    run_dir = run_pipeline(
        settings=_settings(tmp_path, topic_count=2),
        source=_FakeTrendSource(evidence),
        provider=provider,
        store=_store(tmp_path),
        run_id="r1",
    )

    briefs = json.loads((run_dir / "briefs.json").read_text(encoding="utf-8"))
    assert [entry["topic_id"] for entry in briefs] == ["second"]
    assert len(list(run_dir.glob("*.png"))) == 1


def test_an_unknown_template_id_fails_before_anything_is_fetched(tmp_path):
    """Templates load at the top of the pipeline so a typo'd --templates id
    costs nothing. Loading them at brief time instead would burn a full
    Bluesky fan-out and a round of distillation calls before reporting it,
    which is what this test exists to prevent.
    """
    source = _FakeTrendSource([_evidence()])
    with pytest.raises(TemplateError):
        run_pipeline(
            settings=_settings(tmp_path),
            source=source,
            provider=FakeLLMProvider(responses=[_draft(), _choice()]),
            store=_store(tmp_path),
            run_id="r1",
            template_ids=["no_such_template"],
        )
    assert source.calls == 0


def test_an_unknown_template_id_leaves_no_run_directory_behind(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(TemplateError):
        run_pipeline(
            settings=settings,
            source=_FakeTrendSource([_evidence()]),
            provider=FakeLLMProvider(responses=[_draft(), _choice()]),
            store=_store(tmp_path),
            run_id="r1",
            template_ids=["no_such_template"],
        )
    assert not (settings.output_dir / "r1").exists()


def test_filtering_confines_the_brief_to_the_named_templates(tmp_path):
    """The model is only ever shown the filtered library, so a brief naming
    an excluded template is rejected by the existing validator and the run
    ends with no meme rather than silently rendering the wrong template.
    """
    run_dir = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        # Two choices queued: both name the excluded template, so both
        # attempts are rejected by the validator rather than by an
        # exhausted queue.
        provider=FakeLLMProvider(responses=[_draft(), _choice(), _choice()]),
        store=_store(tmp_path),
        run_id="r1",
        template_ids=[TEMPLATE_B],
    )
    assert json.loads((run_dir / "briefs.json").read_text(encoding="utf-8")) == []


def test_the_prompt_lists_only_the_named_templates(tmp_path):
    provider = FakeLLMProvider(responses=[_draft(), _choice(template_id=TEMPLATE_B)])
    run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=provider,
        store=_store(tmp_path),
        run_id="r1",
        template_ids=[TEMPLATE_B],
    )
    brief_prompt = next(
        call.prompt for call in provider.calls if call.schema is BriefChoice
    )
    assert f"id={TEMPLATE_B}" in brief_prompt
    assert f"id={TEMPLATE_A}" not in brief_prompt
