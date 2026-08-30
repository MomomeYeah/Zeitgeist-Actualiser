import sqlite3

import pytest

import zeitgeist.cli as cli_module
from tests.template_factory import make_manifest, write_library
from zeitgeist.analysis.distil import DistilError
from zeitgeist.cli import build_parser, main
from zeitgeist.media.templates import TemplateError
from zeitgeist.sources.base import SourceError

TEMPLATE_ID = "shape_alpha"


def test_run_is_the_default_command():
    args = build_parser().parse_args([])
    assert args.command == "run"


def test_bare_invocation_carries_every_run_attribute():
    args = build_parser().parse_args([])
    assert args.run_id is None
    assert args.resume_from == "ingest"
    assert args.templates is None
    assert args.verbose is False


def test_resume_from_is_parsed():
    args = build_parser().parse_args(
        ["run", "--run-id", "abc", "--resume-from", "generate"]
    )
    assert args.run_id == "abc"
    assert args.resume_from == "generate"


def test_resume_from_requires_a_run_id(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["run", "--resume-from", "generate"])
    assert exit_info.value.code == 2
    assert "--run-id" in capsys.readouterr().err


def test_validate_templates_reports_success(capsys):
    assert main(["validate-templates"]) == 0
    assert "valid" in capsys.readouterr().out


def test_validate_templates_reports_problems(tmp_path, capsys):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert main(["validate-templates", "--dir", str(tmp_path)]) == 1
    assert "parse" in capsys.readouterr().out


def _set_minimal_settings_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SOURCES", "bluesky")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "z.db"))


def _use_synthetic_templates(monkeypatch, tmp_path, tid=TEMPLATE_ID):
    """Point Settings at a one-template library owned by the test, so the
    shipped library can gain and lose templates freely.
    """
    directory = write_library(tmp_path / "templates", make_manifest(tid))
    monkeypatch.setenv("TEMPLATES_DIR", str(directory))
    return directory


def test_source_error_from_the_pipeline_prints_a_message_and_exits_nonzero(
    monkeypatch, tmp_path, capsys
):
    """A raw traceback on the most likely first-run failure (an unreachable
    Bluesky endpoint taking down Stage A entirely) is exactly what this
    guards against — the CLI must report it cleanly instead.
    """
    _set_minimal_settings_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_module,
        "run_pipeline",
        lambda **kwargs: (_ for _ in ()).throw(
            SourceError("Bluesky returned no items")
        ),
    )

    assert main(["run"]) != 0
    assert "Bluesky returned no items" in capsys.readouterr().out


def test_distil_error_from_the_pipeline_prints_a_message_and_exits_nonzero(
    monkeypatch, tmp_path, capsys
):
    """A run where every trend fails distillation must exit 1 with a
    readable message, not a raw traceback and not a silent, green
    "Run complete" over an empty output directory.
    """
    _set_minimal_settings_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_module,
        "run_pipeline",
        lambda **kwargs: (_ for _ in ()).throw(
            DistilError("All 3 trend(s) failed distillation")
        ),
    )

    assert main(["run"]) != 0
    assert "All 3 trend(s) failed distillation" in capsys.readouterr().out


def test_template_error_from_the_pipeline_prints_a_message_and_exits_nonzero(
    monkeypatch, tmp_path, capsys
):
    _set_minimal_settings_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_module,
        "run_pipeline",
        lambda **kwargs: (_ for _ in ()).throw(TemplateError("No template manifests")),
    )

    assert main(["run"]) != 0
    assert "No template manifests" in capsys.readouterr().out


def test_stale_schema_prints_a_message_and_exits_nonzero_instead_of_a_traceback(
    monkeypatch, tmp_path, capsys
):
    """A pre-branch database has PRAGMA user_version == 0, which is != the
    current SCHEMA_VERSION, so init_schema() raises StoreSchemaError. Every
    existing user hits this on their first run of this branch — the CLI must
    report it cleanly instead of letting the traceback escape.
    """
    _set_minimal_settings_env(monkeypatch, tmp_path)
    db_path = tmp_path / "data" / "z.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY)")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    assert main(["run"]) != 0
    assert str(db_path) in capsys.readouterr().out


def test_template_ids_reach_the_pipeline(monkeypatch, tmp_path):
    _set_minimal_settings_env(monkeypatch, tmp_path)
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        cli_module, "run_pipeline", lambda **kwargs: seen.update(kwargs) or tmp_path
    )

    main(["run", "--templates", "alpha, beta "])
    assert seen["template_ids"] == ["alpha", "beta"]


def test_omitting_the_flag_passes_no_template_filter(monkeypatch, tmp_path):
    _set_minimal_settings_env(monkeypatch, tmp_path)
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        cli_module, "run_pipeline", lambda **kwargs: seen.update(kwargs) or tmp_path
    )

    main(["run"])
    assert seen["template_ids"] is None


def test_an_empty_templates_flag_is_rejected(capsys):
    """Falling back to the full library here would answer a request to
    narrow the run with an unnarrowed one.
    """
    with pytest.raises(SystemExit) as exit_info:
        main(["run", "--templates", " , "])
    assert exit_info.value.code == 2
    assert "at least one template id" in capsys.readouterr().err


def test_an_unknown_template_id_is_reported_and_exits_nonzero(
    monkeypatch, tmp_path, capsys
):
    """The message must name both the id that was rejected and what was
    available, or a typo reads as the library being broken.
    """
    _set_minimal_settings_env(monkeypatch, tmp_path)
    _use_synthetic_templates(monkeypatch, tmp_path)
    # Not a prefix of TEMPLATE_ID: a substring typo would make the first
    # assertion pass on the suggestion alone.
    assert main(["run", "--templates", "shape_alfa"]) != 0
    output = capsys.readouterr().out
    assert "shape_alfa" in output
    assert TEMPLATE_ID in output
