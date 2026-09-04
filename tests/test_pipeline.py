from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.template_factory import make_manifest, make_slot, write_library
from zeitgeist.analysis.distil import DossierDraft
from zeitgeist.config import Settings
from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.media.brief import BriefChoice
from zeitgeist.media.templates import TemplateError
from zeitgeist.models import (
    BlueskyMetrics,
    Item,
    MediaBrief,
    PostEvidence,
    Register,
    Reply,
    ScoredTopic,
    Sentiment,
    Topic,
    TrendEvidence,
    TrendInfo,
)
from zeitgeist.pipeline import Stage, run_pipeline
from zeitgeist.records import AutoOrigin
from zeitgeist.store import MissingCheckpoint, Store

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
    return write_library(
        tmp_path / "templates",
        *(
            make_manifest(
                tid,
                slots=[
                    make_slot("rejected", box=(10, 10, 190, 90)),
                    make_slot("preferred", box=(10, 110, 190, 190)),
                ],
            )
            for tid in (TEMPLATE_A, TEMPLATE_B)
        ),
    )


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
    """The expensive fetch lands before the analyse checkpoint, so brief
    tuning re-runs in seconds."""
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    evidence = store.read_checkpoint(run_id, Stage.INGEST, TrendEvidence)

    assert evidence[0].trend.display_name == "A trend"
    assert evidence[0].posts[0].replies[0].text == "what a mess"


def test_the_analyse_checkpoint_carries_the_dossier(tmp_path):
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    [topic] = store.read_checkpoint(run_id, Stage.ANALYSE, Topic)

    assert topic.dossier is not None
    assert topic.dossier.event_sentiment is Sentiment.SCHADENFREUDE


def test_the_evaluate_checkpoint_is_what_resume_reads_back(tmp_path):
    """A break in this round trip breaks resuming silently."""
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    [topic] = store.read_checkpoint(run_id, Stage.EVALUATE, ScoredTopic)

    assert topic.dossier is not None
    assert topic.final_rank == 1


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

    record = store.get_run("r1")
    assert record is not None
    assert record.item_count == 3


def test_produces_a_png(tmp_path):
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    assert list((tmp_path / "output" / run_id / "renders").glob("*.png"))


def test_a_render_lands_in_the_renders_subdirectory_with_a_thumbnail(tmp_path):
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    [record] = store.renders_for_run(run_id)
    renders = tmp_path / "output" / run_id / "renders"

    assert (renders / f"{record.id}.png").is_file()
    assert (renders / f"{record.id}.thumb.png").is_file()


def test_a_render_record_carries_the_brief_that_produced_it(tmp_path):
    """The full-size view shows the slot text and the rationale, so they have
    to be on the record rather than only in the generate checkpoint."""
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    [record] = store.renders_for_run(run_id)

    assert record.template_id == TEMPLATE_A
    assert record.caption_slots == {"rejected": "Dogs", "preferred": "Cats"}
    assert isinstance(record.origin, AutoOrigin)
    assert record.origin.rationale == "Fits."


def test_a_render_that_fails_keeps_a_row_with_its_error(tmp_path):
    """The renderer fails per meme, so three of five is a real outcome. A
    failure that left no row would show as a meme that never existed."""
    store = _store(tmp_path)
    # 400 characters cannot fit a 180x80 box even at the 12px floor, which is
    # the one RenderError the renderer raises for a caption rather than a
    # missing file.
    unrenderable = _choice(caption_slots={"rejected": "x" * 400, "preferred": "y"})
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), unrenderable]),
        store=store,
        run_id="r1",
    )

    [record] = store.renders_for_run(run_id)

    assert record.status == "failed"
    assert record.error is not None
    assert not (tmp_path / "output" / run_id / "renders" / f"{record.id}.png").exists()


def test_records_the_run_and_its_topics_in_the_store(tmp_path):
    """Guards both that the run row is recorded and that the pipeline's
    topics are persisted. A single topic cannot be min-max normalised
    (score.py's MIN_TOPICS_TO_RANK), so it earns no topic_scores row --
    run_topics is the one to check.
    """
    store = _store(tmp_path)
    run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    record = store.get_run("r1")
    assert record is not None
    assert record.status == "ok"
    assert [row.label_slug for row in store.run_topics("r1")] == ["a-trend"]


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


def test_resuming_without_a_checkpoint_raises(tmp_path):
    """Resuming from a stage whose predecessor never ran must say so, not
    behave like a run with no topics."""
    store = _store(tmp_path)

    with pytest.raises(MissingCheckpoint):
        run_pipeline(
            settings=_settings(tmp_path),
            source=_FakeTrendSource([]),
            provider=FakeLLMProvider(responses=[]),
            store=store,
            run_id="never-ran",
            start_at=Stage.GENERATE,
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
    settings = _settings(tmp_path, topic_count=2)
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=settings,
        source=_FakeTrendSource(evidence),
        provider=provider,
        store=store,
        run_id="r1",
    )

    briefs = store.read_checkpoint(run_id, Stage.GENERATE, MediaBrief)
    assert [brief.topic_id for brief in briefs] == ["second"]
    [record] = store.renders_for_run(run_id)
    assert record.status == "ready"
    assert (settings.output_dir / run_id / "renders" / f"{record.id}.png").is_file()


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


def test_an_unknown_template_id_writes_no_run_record(tmp_path):
    """Template ids are validated before the run row is inserted, so a typo
    leaves nothing behind rather than a run stuck in 'running'."""
    store = _store(tmp_path)

    with pytest.raises(TemplateError):
        run_pipeline(
            settings=_settings(tmp_path),
            source=_FakeTrendSource([_evidence()]),
            provider=FakeLLMProvider(responses=[]),
            store=store,
            run_id="r1",
            template_ids=["nope"],
        )

    assert store.get_run("r1") is None


def test_filtering_confines_the_brief_to_the_named_templates(tmp_path):
    """The model is only ever shown the filtered library, so a brief naming
    an excluded template is rejected by the existing validator and the run
    ends with no meme rather than silently rendering the wrong template.
    """
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        # Two choices queued: both name the excluded template, so both
        # attempts are rejected by the validator rather than by an
        # exhausted queue.
        provider=FakeLLMProvider(responses=[_draft(), _choice(), _choice()]),
        store=store,
        run_id="r1",
        template_ids=[TEMPLATE_B],
    )
    assert store.read_checkpoint(run_id, Stage.GENERATE, MediaBrief) == []


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


def test_every_stage_is_recorded_with_a_duration(tmp_path):
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    stages = store.stages_for_run(run_id)

    assert [s.stage for s in stages] == [
        Stage.INGEST,
        Stage.ANALYSE,
        Stage.EVALUATE,
        Stage.GENERATE,
    ]
    assert all(s.status == "ok" for s in stages)
    assert all(s.started_at is not None and s.finished_at is not None for s in stages)


def test_a_skipped_stage_is_recorded_as_skipped(tmp_path):
    """Resuming from generate leaves three stages that did not run this time.
    The cards show them as skipped, not as never having existed."""
    store = _store(tmp_path)
    settings = _settings(tmp_path)
    run_id = run_pipeline(
        settings=settings,
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    run_pipeline(
        settings=settings,
        source=_FakeTrendSource([]),
        provider=FakeLLMProvider(responses=[_choice()]),
        store=store,
        run_id=run_id,
        start_at=Stage.GENERATE,
    )

    stages = {s.stage: s.status for s in store.stages_for_run(run_id)}

    assert stages[Stage.INGEST] == "skipped"
    assert stages[Stage.GENERATE] == "ok"


def test_stage_summaries_report_what_each_stage_did(tmp_path):
    """The stage cards render this line verbatim, and nothing else asserts
    it - a stage handed another stage's summary, or a miscounted one, would
    show as plausible-looking noise on every run."""
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    summaries = {s.stage: s.summary for s in store.stages_for_run(run_id)}

    assert summaries[Stage.INGEST] == "1 trend, 1 post"
    assert summaries[Stage.ANALYSE] == "1 topic distilled"
    assert summaries[Stage.EVALUATE] == "1 of 1 kept"
    assert summaries[Stage.GENERATE] == "1 of 1 rendered"


def test_run_topics_covers_every_topic_not_just_the_kept_ones(tmp_path):
    """The ranking screen draws below-the-cut rows, so they need rows."""
    store = _store(tmp_path)
    # _settings defaults to topic_count=1, so the second topic falls below the
    # cut and appears in run_topics but not in the evaluate checkpoint.
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence("A trend"), _evidence("B trend")]),
        provider=FakeLLMProvider(responses=[_draft(), _draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    assert len(store.read_checkpoint(run_id, Stage.EVALUATE, ScoredTopic)) == 1
    assert len(store.run_topics(run_id)) == 2
    # Two trends, so this run is also the plural branch of _count.
    summaries = {s.stage: s.summary for s in store.stages_for_run(run_id)}
    assert summaries[Stage.INGEST] == "2 trends, 2 posts"
