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


def run_pipeline(
    settings: Settings,
    source: TrendSource,
    provider: LLMProvider,
    store: Store,
    run_id: str,
    start_at: Stage = Stage.INGEST,
    template_ids: list[str] | None = None,
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
    if resuming <= ORDER.index(Stage.INGEST):
        started = datetime.now(UTC)
        evidence = source.fetch_evidence(settings)
        log.info("Fetched %d trends", len(evidence))
        size = store.write_checkpoint(run_id, Stage.INGEST, evidence)
        items = [post.item for entry in evidence for post in entry.posts]
        _stage(
            store,
            run_id,
            Stage.INGEST,
            started,
            f"{_count(len(evidence), 'trend')}, {_count(len(items), 'post')}",
            size,
        )
    else:
        evidence = store.read_checkpoint(run_id, Stage.INGEST, TrendEvidence)
        items = [post.item for entry in evidence for post in entry.posts]
        _skip(store, run_id, Stage.INGEST)

    if resuming <= ORDER.index(Stage.ANALYSE):
        started = datetime.now(UTC)
        topics = distil_topics(evidence, provider, settings)
        topics = score_topics(
            topics, items, datetime.now(UTC), store.previous_sub_scores(run_id)
        )
        log.info("Distilled %d topics", len(topics))
        store.record_topics(run_id, topics)
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
    else:
        _skip(store, run_id, Stage.ANALYSE)

    if resuming <= ORDER.index(Stage.EVALUATE):
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
    else:
        _skip(store, run_id, Stage.EVALUATE)

    ranked = store.read_checkpoint(run_id, Stage.EVALUATE, ScoredTopic)
    started = datetime.now(UTC)
    briefs = generate_briefs(ranked, templates, provider)
    size = store.write_checkpoint(run_id, Stage.GENERATE, briefs)

    run_dir = Path(settings.output_dir) / run_id
    rendered = _render_all(briefs, templates, settings, run_dir, run_id, store)
    log.info("Rendered %d memes into %s", rendered, run_dir)
    _stage(
        store,
        run_id,
        Stage.GENERATE,
        started,
        f"{rendered} of {len(briefs)} rendered",
        size,
    )

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
) -> int:
    """Render every brief, recording each outcome.

    A brief that cannot be drawn keeps a row carrying its error rather than
    vanishing: the renderer fails per meme, so three of five is a real
    outcome the UI has to be able to show.
    """
    renders_dir = run_dir / "renders"
    count = 0
    for brief in briefs:
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

        store.add_render(
            RenderRecord(
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
        )
    return count
