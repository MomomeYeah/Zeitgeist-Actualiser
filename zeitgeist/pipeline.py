"""Stage orchestration and checkpointing.

Each stage writes its output before the next begins, so stage D can be re-run
against a frozen checkpoint while tuning prompts, and a crash always leaves
partial checkpoints to inspect.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from zeitgeist.analysis.distil import distil_topics
from zeitgeist.analysis.score import score_topics
from zeitgeist.analysis.sentiment import select
from zeitgeist.config import Settings
from zeitgeist.llm.base import LLMProvider
from zeitgeist.media.brief import generate_briefs
from zeitgeist.media.render import RenderError, render_meme, write_thumbnail
from zeitgeist.media.templates import TemplateManifest, load_templates, select_templates
from zeitgeist.models import Item, MediaBrief, ScoredTopic, Topic, TrendEvidence
from zeitgeist.progress import CancelToken, NullObserver, RunObserver
from zeitgeist.records import (
    ORDER,
    AutoOrigin,
    RenderRecord,
    RunConfig,
    Stage,
    StageRecord,
)
from zeitgeist.sources.base import TrendSource
from zeitgeist.store import Store

log = logging.getLogger(__name__)


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _posts(evidence: list[TrendEvidence]) -> list[Item]:
    """Every post under every trend, flattened.

    A function rather than the comprehension written out in both ingest
    branches: the evidence is derived identically whether it was just fetched
    or read back from the checkpoint, and the ingest summary needs the count
    before the branches rejoin, so neither branch can simply fall through to
    a shared line.
    """
    return [post.item for entry in evidence for post in entry.posts]


def _stage(
    store: Store,
    run_id: str,
    stage: Stage,
    started: datetime,
    summary: str,
    size: int | None,
) -> None:
    store.record_stage(
        run_id,
        StageRecord(
            stage=stage,
            status="ok",
            started_at=started,
            finished_at=datetime.now(UTC),
            payload_bytes=size,
            summary=summary,
        ),
    )


def _skip(store: Store, run_id: str, stage: Stage) -> None:
    store.record_stage(
        run_id,
        StageRecord(
            stage=stage,
            status="skipped",
            started_at=None,
            finished_at=None,
            payload_bytes=None,
            summary="skipped",
        ),
    )


def _stopping(token: CancelToken | None) -> bool:
    """Whether to end the run rather than begin another stage.

    Read at stage boundaries only. A stop checked inside a stage would
    abandon it before its checkpoint was written, which is the resumability
    the stop button promises.
    """
    return token is not None and token.stopping


def run_pipeline(
    settings: Settings,
    source: TrendSource,
    provider: LLMProvider,
    store: Store,
    run_id: str,
    start_at: Stage = Stage.INGEST,
    template_ids: list[str] | None = None,
    *,
    observer: RunObserver = NullObserver(),
    token: CancelToken | None = None,
) -> str:
    """Run the pipeline, returning the run id.

    Returns the id rather than the run directory because the directory now
    holds only rendered images; everything else lives in the store, and the
    id is what every caller looks records up by.
    """
    # Before the run row exists and before anything is fetched: a mistyped
    # template id then costs nothing and leaves nothing behind.
    templates = load_templates(settings.templates_dir)
    if template_ids is not None:
        templates = select_templates(templates, template_ids)

    resuming = ORDER.index(start_at)
    store.start_run(run_id, RunConfig.freeze(settings, template_ids))

    items: list[Item]
    if _stopping(token):
        return run_id
    if resuming <= ORDER.index(Stage.INGEST):
        observer.stage_started(Stage.INGEST)
        started = datetime.now(UTC)
        evidence = source.fetch_evidence(settings)
        log.info("Fetched %d trends", len(evidence))
        size = store.write_checkpoint(run_id, Stage.INGEST, evidence)
        items = _posts(evidence)
        _stage(
            store,
            run_id,
            Stage.INGEST,
            started,
            f"{_count(len(evidence), 'trend')}, {_count(len(items), 'post')}",
            size,
        )
        observer.stage_finished(Stage.INGEST, size)
    else:
        evidence = store.read_checkpoint(run_id, Stage.INGEST, TrendEvidence)
        items = _posts(evidence)
        _skip(store, run_id, Stage.INGEST)
        observer.stage_finished(Stage.INGEST, None)

    if _stopping(token):
        return run_id
    if resuming <= ORDER.index(Stage.ANALYSE):
        observer.stage_started(Stage.ANALYSE)
        started = datetime.now(UTC)
        topics = distil_topics(
            evidence,
            provider,
            settings,
            on_topic=observer.topic_distilled,
            token=token,
        )
        topics = score_topics(
            topics, items, datetime.now(UTC), store.previous_sub_scores(run_id)
        )
        log.info("Distilled %d topics", len(topics))
        size = store.write_analyse_checkpoint(
            run_id, topics, settings.meme_potential_weight
        )
        _stage(
            store,
            run_id,
            Stage.ANALYSE,
            started,
            f"{_count(len(topics), 'topic')} distilled",
            size,
        )
        observer.stage_finished(Stage.ANALYSE, size)
    else:
        _skip(store, run_id, Stage.ANALYSE)
        observer.stage_finished(Stage.ANALYSE, None)

    if _stopping(token):
        return run_id
    if resuming <= ORDER.index(Stage.EVALUATE):
        observer.stage_started(Stage.EVALUATE)
        started = datetime.now(UTC)
        topics = store.read_checkpoint(run_id, Stage.ANALYSE, Topic)
        ranked = select(topics, settings.topic_count, settings.meme_potential_weight)
        log.info("Selected %d topics", len(ranked))
        size = store.write_checkpoint(run_id, Stage.EVALUATE, ranked)
        _stage(
            store,
            run_id,
            Stage.EVALUATE,
            started,
            f"{len(ranked)} of {len(topics)} kept",
            size,
        )
        observer.stage_finished(Stage.EVALUATE, size)
    else:
        _skip(store, run_id, Stage.EVALUATE)
        observer.stage_finished(Stage.EVALUATE, None)

    if _stopping(token):
        return run_id
    observer.stage_started(Stage.GENERATE)
    ranked = store.read_checkpoint(run_id, Stage.EVALUATE, ScoredTopic)
    started = datetime.now(UTC)
    briefs = generate_briefs(ranked, templates, provider)
    size = store.write_checkpoint(run_id, Stage.GENERATE, briefs)

    run_dir = Path(settings.output_dir) / run_id
    rendered = _render_all(
        briefs, templates, settings, run_dir, run_id, store, observer, token
    )
    log.info("Rendered %d memes into %s", rendered, run_dir)
    _stage(
        store,
        run_id,
        Stage.GENERATE,
        started,
        f"{rendered} of {len(briefs)} rendered",
        size,
    )
    observer.stage_finished(Stage.GENERATE, size)

    store.finish_run(
        run_id,
        status="ok",
        item_count=len(items),
        trends_found=len(evidence),
        topics_kept=len(ranked),
        phrases_found=sum(
            len(t.dossier.recurring_phrases) if t.dossier else 0 for t in ranked
        ),
    )
    return run_id


def _render_all(
    briefs: list[MediaBrief],
    templates: dict[str, TemplateManifest],
    settings: Settings,
    run_dir: Path,
    run_id: str,
    store: Store,
    observer: RunObserver,
    token: CancelToken | None,
) -> int:
    """Render every brief, recording each outcome.

    A brief that cannot be drawn keeps a row carrying its error rather than
    vanishing: the renderer fails per meme, so three of five is a real
    outcome the UI has to be able to show.
    """
    renders_dir = run_dir / "renders"
    count = 0
    for index, brief in enumerate(briefs):
        if token is not None:
            token.check()
        observer.stage_progress(
            Stage.GENERATE, done=index, total=len(briefs), detail=brief.topic_id
        )
        render_id = uuid4().hex
        out_path = renders_dir / f"{render_id}.png"
        error: str | None = None
        try:
            render_meme(
                brief,
                templates[brief.template_id],
                settings.templates_dir,
                out_path,
                settings.font_path,
            )
            write_thumbnail(out_path, renders_dir / f"{render_id}.thumb.png")
            count += 1
        except RenderError as exc:
            log.warning("Could not render %r: %s", brief.topic_id, exc)
            error = str(exc)

        record = RenderRecord(
            id=render_id,
            run_id=run_id,
            topic_id=brief.topic_id,
            template_id=brief.template_id,
            caption_slots=dict(brief.caption_slots),
            origin=AutoOrigin(rationale=brief.rationale),
            status="failed" if error else "ready",
            error=error,
            created_at=datetime.now(UTC),
        )
        store.add_render(record)
        observer.render_finished(record)
    return count
