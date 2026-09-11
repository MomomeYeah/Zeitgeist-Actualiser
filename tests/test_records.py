from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tests.run_factory import make_run_config
from zeitgeist.config import Settings
from zeitgeist.records import (
    AutoOrigin,
    ManualOrigin,
    RenderRecord,
    RunConfig,
    Stage,
    StageRecord,
)
from zeitgeist.runner import RUN_OVERRIDE_KEYS, resolve_settings


def test_freeze_copies_the_settings_a_run_detail_config_line_shows():
    settings = Settings(_env_file=None, llm_model="claude-sonnet-5", topic_count=5)

    frozen = RunConfig.freeze(settings, template_ids=None)

    assert frozen.top_count == 5
    assert frozen.llm_model == "claude-sonnet-5"
    assert frozen.trend_limit == settings.bluesky_trend_limit
    assert frozen.template_ids is None


def test_freeze_is_a_copy_not_a_view():
    """The config line must show what the run used, not what .env says now."""
    settings = Settings(_env_file=None, topic_count=5)
    frozen = RunConfig.freeze(settings, template_ids=None)

    settings.topic_count = 9

    assert frozen.top_count == 5


def test_as_overrides_round_trips_through_freeze_and_resolve_settings():
    """The inverse of `freeze`, pinned against the real `resolve_settings`
    and the real `Settings` validator rather than against a hand-written
    expectation of the mapping. Every value here is deliberately different
    from its `Settings` default, so a wrong key name in the mapping table
    would leave that field at its default in `resolved` and this would
    catch it as a mismatch against `cfg`.
    """
    cfg = make_run_config(
        sources=["bluesky"],
        trend_limit=7,
        posts_per_trend=3,
        top_count=2,
        meme_potential_weight=0.75,
        phrase_min_authors=9,
        distil_char_budget=5000,
        distil_concurrency=2,
        llm_provider="ollama",
        llm_model="qwen3.5",
        template_ids=["drake", "distracted-boyfriend"],
    )

    overrides = cfg.as_overrides()
    resolved = resolve_settings(Settings(_env_file=None), overrides)

    assert RunConfig.freeze(resolved, cfg.template_ids) == cfg
    assert set(overrides) <= RUN_OVERRIDE_KEYS


def test_a_manual_render_has_no_rationale_field_at_all():
    """Not an empty string - a hand-written render has no template choice to
    justify, so the field should not be reachable."""
    origin = ManualOrigin()

    assert not hasattr(origin, "rationale")


def test_a_render_deserialises_back_to_its_concrete_origin_class():
    """Discriminated on provenance, so a row round-trips to the right class
    rather than to whichever union member happens to validate."""
    record = RenderRecord(
        id="abc",
        run_id="r1",
        topic_id="t1",
        template_id="drake",
        caption_slots={"rejected": "a", "preferred": "b"},
        origin=AutoOrigin(rationale="it fits"),
        status="ready",
        error=None,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    restored = RenderRecord.model_validate_json(record.model_dump_json())

    assert isinstance(restored.origin, AutoOrigin)
    assert restored.origin.rationale == "it fits"


def test_a_manual_render_round_trips_without_gaining_a_rationale():
    record = RenderRecord(
        id="abc",
        run_id="r1",
        topic_id="t1",
        template_id="drake",
        caption_slots={"rejected": "a", "preferred": "b"},
        origin=ManualOrigin(),
        status="ready",
        error=None,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    restored = RenderRecord.model_validate_json(record.model_dump_json())

    assert isinstance(restored.origin, ManualOrigin)


def test_a_queued_stage_has_no_timings():
    """Optionality here describes a real state, not a missing migration."""
    record = StageRecord(
        stage=Stage.INGEST,
        status="queued",
        started_at=None,
        finished_at=None,
        payload_bytes=None,
        summary="queued",
    )

    assert record.started_at is None


def test_records_reject_unknown_fields():
    with pytest.raises(ValidationError):
        StageRecord(
            stage=Stage.INGEST,
            status="queued",
            started_at=None,
            finished_at=None,
            payload_bytes=None,
            summary="queued",
            duration=3,
        )
