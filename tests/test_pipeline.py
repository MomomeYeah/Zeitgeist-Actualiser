import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from tests.template_factory import make_manifest, make_slot, write_library
from zeitgeist.analysis.distil import DossierDraft
from zeitgeist.config import Settings
from zeitgeist.llm.base import FakeLLMProvider, LLMError, LLMProvider
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
from zeitgeist.pipeline import Stage, new_run_id, run_pipeline
from zeitgeist.progress import Aborted, CancelToken, RecordingObserver
from zeitgeist.records import ORDER, AutoOrigin, RenderRecord
from zeitgeist.sources.base import TrendSource
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


def _full_run_args(
    tmp_path, **overrides: Any
) -> tuple[Settings, TrendSource, LLMProvider, Store, str]:
    """The five positional arguments `run_pipeline` takes, for a run that
    goes the distance: one trend, one topic, one rendered meme.

    Every existing test in this module builds these by hand; the new tests
    below only ever need `run_id` and `store` overridden, so those are
    accepted by name rather than duplicating the construction again.
    """
    base: dict[str, Any] = dict(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=_store(tmp_path),
        run_id="r1",
    )
    args = base | overrides
    return (
        args["settings"],
        args["source"],
        args["provider"],
        args["store"],
        args["run_id"],
    )


def _failing_render_args(
    tmp_path,
) -> tuple[Settings, TrendSource, LLMProvider, Store, str]:
    """Same shape as `_full_run_args`, but the chosen template's image is
    missing, so `render_meme` raises `RenderError` (see
    `test_missing_image_raises` in test_media_render.py) and the render is
    recorded as failed rather than ready.
    """
    settings = _settings(tmp_path)
    (settings.templates_dir / f"{TEMPLATE_A}.png").unlink()
    return (
        settings,
        _FakeTrendSource([_evidence()]),
        FakeLLMProvider(responses=[_draft(), _choice()]),
        _store(tmp_path),
        "r1",
    )


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


def test_every_stage_reports_started_and_finished(tmp_path):
    """The in-flight screen draws one card per stage and fills it from these
    two events. A stage that reported neither would render as pending for the
    whole run and then jump to done.
    """
    observer = RecordingObserver()

    run_pipeline(*_full_run_args(tmp_path), observer=observer)

    started = [event.payload[0] for event in observer.named("stage_started")]
    finished = [event.payload[0] for event in observer.named("stage_finished")]
    assert started == list(ORDER)
    assert finished == list(ORDER)


def test_every_stage_reports_the_size_of_the_checkpoint_it_wrote(tmp_path):
    """`stage_finished` carries payload bytes rather than a path because
    checkpoints are rows. `is not None and > 0` would pass for a hardcoded 1
    on every stage — which is exactly the "every stage card claims the same
    size" bug — so each reported number is checked against the row it
    describes, read out of the checkpoints table rather than back through the
    pipeline that reported it.
    """
    observer = RecordingObserver()
    run_id = "20260905T150000Z"

    run_pipeline(*_full_run_args(tmp_path, run_id=run_id), observer=observer)

    reported = {
        event.payload[0]: event.payload[1] for event in observer.named("stage_finished")
    }
    conn = sqlite3.connect(tmp_path / "data" / "z.db")
    try:
        written = {
            Stage(stage): len(payload.encode("utf-8"))
            for stage, payload in conn.execute(
                "SELECT stage, payload FROM checkpoints WHERE run_id = ?",
                (run_id,),
            )
        }
    finally:
        conn.close()

    assert set(written) == set(ORDER), "a stage wrote no checkpoint"
    assert {stage: reported[stage] for stage in written} == written


def test_a_skipped_stage_reports_no_payload(tmp_path):
    """`None` is the documented meaning of "wrote no payload". A resumed run
    skips the stages before its start point, and a skipped stage reporting a
    stale size would show the resumed run re-writing checkpoints it did not
    touch.
    """
    run_id = "20260905T120000Z"
    run_pipeline(*_full_run_args(tmp_path, run_id=run_id))
    observer = RecordingObserver()

    run_pipeline(
        *_full_run_args(tmp_path, run_id=run_id),
        start_at=Stage.GENERATE,
        observer=observer,
    )

    sizes = {
        event.payload[0]: event.payload[1] for event in observer.named("stage_finished")
    }
    assert sizes[Stage.INGEST] is None
    assert sizes[Stage.ANALYSE] is None


def test_topics_are_reported_during_analyse_not_after_it(tmp_path):
    """The mid-analyse screen appends ranking rows as they arrive. Reporting
    them after `stage_finished(ANALYSE)` — which a batch at the end of the
    stage would do — puts every row on screen at the moment the stage
    completes, which is the behaviour this event exists to avoid.
    """
    observer = RecordingObserver()

    run_pipeline(*_full_run_args(tmp_path), observer=observer)

    names = [event.name for event in observer.events]
    analyse_finished = [
        index
        for index, event in enumerate(observer.events)
        if event.name == "stage_finished" and event.payload[0] is Stage.ANALYSE
    ][0]
    first_topic = names.index("topic_distilled")
    assert first_topic < analyse_finished


def test_every_render_is_reported_including_one_that_failed(tmp_path):
    """`render_finished` carries the whole record so a failed render reaches
    the UI as a tile with a message. Reporting only successes is how a
    per-meme failure vanishes — the exact outcome the record's `status` and
    `error` fields exist to prevent.
    """
    observer = RecordingObserver()

    run_pipeline(*_failing_render_args(tmp_path), observer=observer)

    # `payload` is `tuple[object, ...]` because ObservedEvent carries every
    # event kind; `named("render_finished")` is what actually guarantees
    # `payload[0]` is a RenderRecord.
    statuses = [
        cast(RenderRecord, event.payload[0]).status
        for event in observer.named("render_finished")
    ]
    assert "failed" in statuses


def test_stopping_after_a_stage_leaves_that_stages_checkpoint_written(tmp_path):
    """The promise of the stop button: the current stage finishes and the run
    stays resumable. A stop honoured *inside* a stage would leave no
    checkpoint for it, and resume would have to redo work the user already
    paid for.
    """
    token = CancelToken()
    store = _store(tmp_path)

    # Subclassed rather than proxied through `__getattr__`: `ty` cannot see
    # that a proxy satisfies `RunObserver`, and the gate covers tests.
    class _StopAfterIngest(RecordingObserver):
        def stage_finished(self, stage: Stage, payload_bytes: int | None) -> None:
            if stage is Stage.INGEST:
                token.stop_after_stage()
            super().stage_finished(stage, payload_bytes)

    run_pipeline(
        *_full_run_args(tmp_path, store=store, run_id="20260905T130000Z"),
        observer=_StopAfterIngest(),
        token=token,
    )

    assert Stage.INGEST in store.written_stages("20260905T130000Z")
    assert Stage.ANALYSE not in store.written_stages("20260905T130000Z")


def test_a_stopped_run_is_not_marked_finished(tmp_path):
    """The worker decides the terminal status, because only it can tell stop
    from abort. If `run_pipeline` called `finish_run(status="ok")` on the way
    out of a stop, a half-finished run would show as a successful one and its
    counts would be wrong.
    """
    token = CancelToken()
    token.stop_after_stage()
    store = _store(tmp_path)
    run_id = "20260905T140000Z"

    run_pipeline(*_full_run_args(tmp_path, store=store, run_id=run_id), token=token)

    record = store.get_run(run_id)
    assert record is not None
    assert record.status == "running"


def test_aborting_during_a_stage_propagates_out_of_the_pipeline(tmp_path):
    """The worker catches `Aborted` to write the terminal status. Swallowed
    inside `run_pipeline`, an aborted run would return normally and be
    recorded as a success.

    The abort is raised from inside the generate stage rather than before the
    run, because `abort()` also sets `stopping` — a token aborted up front is
    consumed by the stage boundary, which *returns* rather than raising, so a
    test written that way would assert on a path abort never takes and could
    never pass.
    """
    token = CancelToken()

    class _AbortOnGenerate(RecordingObserver):
        def stage_started(self, stage: Stage) -> None:
            if stage is Stage.GENERATE:
                token.abort()
            super().stage_started(stage)

    with pytest.raises(Aborted):
        run_pipeline(
            *_full_run_args(tmp_path),
            observer=_AbortOnGenerate(),
            token=token,
        )


def test_generate_reports_progress_before_each_brief(tmp_path):
    """The in-flight screen's generate card counts memes as they render, and
    `stage_progress` is the only event carrying that count. Deleting the call
    — or reporting `done` as one-based, or a constant total — leaves every
    other test in this module green while the card sits still until the stage
    ends.

    `done` is checked against the render events rather than a literal, because
    the number of briefs is a property of the fixture rather than of the
    behaviour under test; what matters is that it counts up from zero, once
    per brief, with the total fixed.
    """
    observer = RecordingObserver()

    run_pipeline(*_full_run_args(tmp_path), observer=observer)

    progress = [event.payload for event in observer.named("stage_progress")]
    # See the comment in test_every_render_is_reported_including_one_that_failed
    # about why payload[0] needs a cast here.
    rendered = [
        cast(RenderRecord, event.payload[0])
        for event in observer.named("render_finished")
    ]

    assert rendered, "the fixture rendered nothing; the assertion is vacuous"
    assert [payload[0] for payload in progress] == [Stage.GENERATE] * len(rendered)
    assert [payload[1] for payload in progress] == list(range(len(rendered)))
    assert {payload[2] for payload in progress} == {len(rendered)}
    assert [payload[3] for payload in progress] == [
        record.topic_id for record in rendered
    ]


def test_new_run_id_is_distinct_on_every_call_even_in_a_tight_loop():
    """`Store.start_run` upserts on `run_id`: `INSERT ... ON CONFLICT(run_id)
    DO UPDATE`. Two calls to `new_run_id()` that return the same string
    therefore don't just label two runs alike - the second `start_run` call
    resets the first run's row back to `running`, replaces its frozen
    config, and nulls its outcome columns, while the first run's worker is
    still executing against it. Both runs then write checkpoints, stage
    records, renders and log lines under the one surviving id, and one run's
    result is silently lost.

    The old implementation formatted with whole-second resolution
    (`%Y%m%dT%H%M%SZ`), so any two calls landing in the same wall-clock
    second - trivial in a tight loop - returned the identical string. 10,000
    iterations with no delay would collide many times over under that
    scheme; asserting the results form a set of the same size as the list
    catches that collision even though it may not happen on every call.
    """
    ids = [new_run_id() for _ in range(10_000)]

    assert len(set(ids)) == len(ids)
