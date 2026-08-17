import pytest

from zeitgeist.cli import build_parser, main


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
