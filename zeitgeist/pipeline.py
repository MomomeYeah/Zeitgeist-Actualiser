"""Stage orchestration and checkpointing.

Each stage writes its output before the next begins, so stage D can be re-run
against a frozen ranked.json while tuning prompts, and a crash always leaves
partial artifacts to inspect.
"""

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from zeitgeist.analysis.consolidate import consolidate
from zeitgeist.analysis.extract import extract_tags
from zeitgeist.analysis.score import score_topics
from zeitgeist.analysis.sentiment import judge_topics, select
from zeitgeist.config import Settings
from zeitgeist.llm.base import LLMProvider
from zeitgeist.media.brief import generate_briefs
from zeitgeist.media.render import RenderError, render_meme
from zeitgeist.media.templates import TemplateManifest, load_templates
from zeitgeist.models import MediaBrief, Post, ScoredTopic, Topic
from zeitgeist.sources.base import Source
from zeitgeist.store import Store

log = logging.getLogger(__name__)


class Stage(StrEnum):
    INGEST = "ingest"
    ANALYSE = "analyse"
    EVALUATE = "evaluate"
    GENERATE = "generate"


ORDER = [Stage.INGEST, Stage.ANALYSE, Stage.EVALUATE, Stage.GENERATE]


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def run_pipeline(
    settings: Settings,
    source: Source,
    provider: LLMProvider,
    store: Store,
    run_id: str,
    start_at: Stage = Stage.INGEST,
) -> Path:
    run_dir = Path(settings.output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    resuming = ORDER.index(start_at)

    store.start_run(run_id)
    posts: list[Post] = []

    # Stage A — fatal on failure: with no posts there is nothing to analyse.
    if resuming <= ORDER.index(Stage.INGEST):
        posts = source.fetch(limit=settings.post_limit)
        log.info("Fetched %d posts", len(posts))
        _write(run_dir / "posts.json", posts)
    else:
        posts = _read(run_dir / "posts.json", Post)

    if resuming <= ORDER.index(Stage.ANALYSE):
        tags = extract_tags(posts, provider)
        topics = consolidate(tags, provider)
        topics = score_topics(
            topics, posts, datetime.now(UTC), store.previous_scores(run_id)
        )
        log.info("Identified %d topics", len(topics))
        store.record_topics(run_id, topics)
        _write(run_dir / "topics.json", topics)

    if resuming <= ORDER.index(Stage.EVALUATE):
        topics = _read(run_dir / "topics.json", Topic)
        ranked = select(
            judge_topics(topics, provider),
            settings.sentiment_weights,
            settings.topic_count,
        )
        log.info("Selected %d topics", len(ranked))
        _write(run_dir / "ranked.json", ranked)

    ranked = _read(run_dir / "ranked.json", ScoredTopic)
    templates = load_templates(settings.templates_dir)
    briefs = generate_briefs(ranked, templates, provider)
    _write(run_dir / "briefs.json", briefs)

    rendered = _render_all(briefs, templates, settings, run_dir)
    log.info("Rendered %d memes into %s", rendered, run_dir)

    store.finish_run(run_id, status="ok", post_count=len(posts))
    return run_dir


def _render_all(
    briefs: list[MediaBrief],
    templates: dict[str, TemplateManifest],
    settings: Settings,
    run_dir: Path,
) -> int:
    count = 0
    for position, brief in enumerate(briefs, start=1):
        try:
            render_meme(
                brief,
                templates[brief.template_id],
                settings.templates_dir,
                run_dir / f"{position:02d}-{brief.topic_id}.png",
                settings.font_path,
            )
            count += 1
        except RenderError as exc:
            log.warning("Could not render %r: %s", brief.topic_id, exc)
    return count


def _write(path: Path, models: list[BaseModel]) -> None:
    payload = [model.model_dump(mode="json") for model in models]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read(path: Path, schema: type) -> list:
    if not path.is_file():
        raise FileNotFoundError(f"Missing checkpoint: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [schema.model_validate(entry) for entry in raw]
