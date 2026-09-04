"""Stage orchestration and checkpointing.

Each stage writes its output before the next begins, so stage D can be re-run
against a frozen ranked.json while tuning prompts, and a crash always leaves
partial artifacts to inspect.
"""

import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from zeitgeist.analysis.distil import distil_topics
from zeitgeist.analysis.score import score_topics
from zeitgeist.analysis.sentiment import select
from zeitgeist.config import Settings
from zeitgeist.llm.base import LLMProvider
from zeitgeist.media.brief import generate_briefs
from zeitgeist.media.render import RenderError, render_meme
from zeitgeist.media.templates import TemplateManifest, load_templates, select_templates
from zeitgeist.models import Item, MediaBrief, ScoredTopic, Topic, TrendEvidence
from zeitgeist.records import ORDER, Stage
from zeitgeist.sources.base import TrendSource
from zeitgeist.store import Store

log = logging.getLogger(__name__)


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def run_pipeline(
    settings: Settings,
    source: TrendSource,
    provider: LLMProvider,
    store: Store,
    run_id: str,
    start_at: Stage = Stage.INGEST,
    template_ids: list[str] | None = None,
) -> Path:
    # Before the run directory exists and before anything is fetched: a
    # mistyped template id then costs nothing and leaves nothing behind.
    templates = load_templates(settings.templates_dir)
    if template_ids is not None:
        templates = select_templates(templates, template_ids)

    run_dir = Path(settings.output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    resuming = ORDER.index(start_at)

    store.start_run(run_id)

    # Stage A — fatal on failure: with no evidence there is nothing to
    # analyse. Everything expensive happens here and in ANALYSE, so a brief
    # or template change re-runs from GENERATE against frozen dossiers.
    if resuming <= ORDER.index(Stage.INGEST):
        evidence = source.fetch_evidence(settings)
        log.info("Fetched %d trends", len(evidence))
        _write(run_dir / "evidence.json", evidence)
    else:
        evidence = _read(run_dir / "evidence.json", TrendEvidence)

    items: list[Item] = [post.item for entry in evidence for post in entry.posts]

    if resuming <= ORDER.index(Stage.ANALYSE):
        topics = distil_topics(evidence, provider, settings)
        topics = score_topics(
            topics, items, datetime.now(UTC), store.previous_sub_scores(run_id)
        )
        log.info("Distilled %d topics", len(topics))
        store.record_topics(run_id, topics)
        _write(run_dir / "topics.json", topics)

    if resuming <= ORDER.index(Stage.EVALUATE):
        topics = _read(run_dir / "topics.json", Topic)
        ranked = select(topics, settings.topic_count, settings.meme_potential_weight)
        log.info("Selected %d topics", len(ranked))
        _write(run_dir / "ranked.json", ranked)

    ranked = _read(run_dir / "ranked.json", ScoredTopic)
    briefs = generate_briefs(ranked, templates, provider)
    _write(run_dir / "briefs.json", briefs)

    rendered = _render_all(briefs, templates, settings, run_dir)
    log.info("Rendered %d memes into %s", rendered, run_dir)

    store.finish_run(run_id, status="ok", item_count=len(items))
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


# Sequence rather than list: list is invariant, so a list[Item] is not a
# list[BaseModel] and every call site was rejected. _write only iterates.
def _write(path: Path, models: Sequence[BaseModel]) -> None:
    payload = [model.model_dump(mode="json") for model in models]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read[T: BaseModel](path: Path, schema: type[T]) -> list[T]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing checkpoint: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [schema.model_validate(entry) for entry in raw]
