import pytest

import zeitgeist.cli as cli_module
from zeitgeist.cli import build_parser, main
from zeitgeist.media.templates import TemplateError
from zeitgeist.sources.base import SourceError


def test_run_is_the_default_command():
    args = build_parser().parse_args([])
    assert args.command == "run"


def test_bare_invocation_carries_every_run_attribute():
    args = build_parser().parse_args([])
    assert args.run_id is None
    assert args.resume_from == "ingest"
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
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "z.db"))


def test_source_error_from_the_pipeline_prints_a_message_and_exits_nonzero(
    monkeypatch, tmp_path, capsys
):
    """A raw PRAW traceback on the most likely first-run failure (a typo'd
    subreddit taking down Stage A entirely) is exactly what this guards
    against — the CLI must report it cleanly instead.
    """
    _set_minimal_settings_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_module,
        "run_pipeline",
        lambda **kwargs: (_ for _ in ()).throw(SourceError("Reddit returned no posts")),
    )

    assert main(["run"]) != 0
    assert "Reddit returned no posts" in capsys.readouterr().out


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
