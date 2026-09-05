"""`zeitgeist.serve.main` never starts a real server here — `uvicorn.run` is
monkeypatched in every test, and each test asserts what `main` handed it.
"""

from fastapi import FastAPI

import zeitgeist.serve as serve


def _capture_run(monkeypatch):
    """Patch `uvicorn.run` and return the list its call is recorded into."""
    calls: list[dict[str, object]] = []

    def fake_run(target, **kwargs) -> None:
        calls.append({"target": target, **kwargs})

    monkeypatch.setattr(serve.uvicorn, "run", fake_run)
    return calls


def test_without_reload_uvicorn_is_given_a_live_app(monkeypatch, tmp_path):
    """Passing an app instance is correct only when reload is off. Passing
    the import string here instead would still run, but --reload's absence
    would then buy nothing on the next edit -- this pins the instance path
    stays an instance."""
    monkeypatch.chdir(tmp_path)
    calls = _capture_run(monkeypatch)

    assert serve.main([]) == 0

    assert len(calls) == 1
    assert isinstance(calls[0]["target"], FastAPI)
    assert calls[0].get("reload") is not True


def test_reload_is_passed_as_an_import_string_with_factory(monkeypatch):
    """This is the bug the review found: uvicorn requires an import string
    plus factory=True to enable --reload. Passing a live app instance here
    (the old code's shape) makes uvicorn print a warning and exit 3, serving
    nothing."""
    calls = _capture_run(monkeypatch)

    assert serve.main(["--reload"]) == 0

    assert len(calls) == 1
    assert calls[0]["target"] == "zeitgeist.serve:_app"
    assert calls[0]["factory"] is True
    assert calls[0]["reload"] is True


def test_the_reload_factory_builds_a_real_app(monkeypatch, tmp_path):
    """`_app` is what uvicorn's reloader actually imports and calls; a typo
    in its dotted path or a factory that returned the wrong thing would only
    surface once reload was exercised for real."""
    monkeypatch.chdir(tmp_path)

    app = serve._app()

    assert isinstance(app, FastAPI)


def test_default_host_and_port(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = _capture_run(monkeypatch)

    serve.main([])

    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 8000


def test_host_and_port_flags_override_the_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = _capture_run(monkeypatch)

    serve.main(["--host", "0.0.0.0", "--port", "9000"])

    assert calls[0]["host"] == "0.0.0.0"
    assert calls[0]["port"] == 9000


def test_host_and_port_flags_also_apply_on_the_reload_path(monkeypatch):
    calls = _capture_run(monkeypatch)

    serve.main(["--reload", "--host", "0.0.0.0", "--port", "9000"])

    assert calls[0]["host"] == "0.0.0.0"
    assert calls[0]["port"] == 9000
