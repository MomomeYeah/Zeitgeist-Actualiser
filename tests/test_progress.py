import inspect
import threading

import pytest

from tests.run_factory import make_topic
from zeitgeist.progress import (
    Aborted,
    CancelToken,
    NullObserver,
    RecordingObserver,
    RunObserver,
)
from zeitgeist.records import Stage


def test_the_null_observer_matches_the_protocol_method_for_method():
    """The whole point of a null implementation is that it can stand in
    everywhere the Protocol is accepted. `ty` checks assignability at the
    call sites that exist, but nothing checks that someone adding a sixth
    method to the Protocol remembers to add it here — and a `NullObserver`
    missing a method fails at call time, deep inside a run, rather than at
    startup.
    """
    protocol_methods = {
        name: inspect.signature(member)
        for name, member in vars(RunObserver).items()
        if callable(member) and not name.startswith("_")
    }
    assert protocol_methods, "no methods found on RunObserver; the scan is wrong"

    for name, signature in protocol_methods.items():
        assert hasattr(NullObserver, name), f"NullObserver is missing {name}"
        assert inspect.signature(getattr(NullObserver, name)) == signature, name


def test_the_recording_observer_keeps_events_in_call_order():
    """Order is the assertion these exist to enable: the pipeline's tests
    check that `topic_distilled` fires per topic *between* `stage_started`
    and `stage_finished`, which a set or a counter could not express.
    """
    observer = RecordingObserver()

    observer.stage_started(Stage.ANALYSE)
    observer.topic_distilled(make_topic("cats"))
    observer.topic_distilled(make_topic("dogs"))
    observer.stage_finished(Stage.ANALYSE, 99)

    assert [event.name for event in observer.events] == [
        "stage_started",
        "topic_distilled",
        "topic_distilled",
        "stage_finished",
    ]


def test_the_recording_observer_keeps_each_events_arguments():
    """A recorder that kept only names would let a test pass while the
    pipeline reported the wrong stage, the wrong topic, or a payload size of
    zero for a stage that wrote 1.3MB.
    """
    topic = make_topic("cats")
    observer = RecordingObserver()

    observer.stage_finished(Stage.INGEST, 2048)
    observer.topic_distilled(topic)

    assert observer.events[0].payload == (Stage.INGEST, 2048)
    assert observer.events[1].payload == (topic,)


def test_named_selects_one_kind_without_disturbing_the_stream():
    """`named` is a convenience the pipeline tests lean on heavily. If it
    filtered the stored list rather than returning a new one, the second
    assertion in any test using it would see a truncated history.
    """
    observer = RecordingObserver()
    observer.stage_started(Stage.INGEST)
    observer.topic_distilled(make_topic("cats"))

    distilled = observer.named("topic_distilled")

    assert [event.name for event in distilled] == ["topic_distilled"]
    assert len(observer.events) == 2


def test_a_fresh_token_stops_nothing():
    """The default path. Every run that is never cancelled calls `check()`
    once per model call and once per brief, and every one of them must
    return."""
    token = CancelToken()

    token.check()

    assert token.stopping is False
    assert token.aborted is False


def test_stopping_does_not_raise_from_check():
    """Stop-after-stage promises the current stage completes and writes its
    checkpoint. A `check()` that raised for a stopping token would abandon
    the stage mid-flight and lose exactly the resumability the button
    promises — and no other test would notice, because the stage boundary
    reads `stopping` on a different code path.
    """
    token = CancelToken()

    token.stop_after_stage()

    token.check()
    assert token.stopping is True
    assert token.aborted is False


def test_aborting_raises_from_check():
    token = CancelToken()

    token.abort()

    with pytest.raises(Aborted):
        token.check()


def test_an_aborted_token_is_also_stopping():
    """The stage boundary reads `stopping` to decide whether to begin the
    next stage. An aborted token reporting `stopping is False` would start
    one more stage in the window between the abort and the next `check()`.
    """
    token = CancelToken()

    token.abort()

    assert token.stopping is True
    assert token.aborted is True


def test_a_flag_set_on_one_thread_is_seen_on_another():
    """This is the token's entire job: `POST /api/runs/{id}/abort` runs on a
    request thread and the pipeline reads it on the worker. A token that
    held state per thread — a thread-local, or a copy taken at
    construction — would pass every other test here and never cancel a real
    run.
    """
    token = CancelToken()
    seen = threading.Event()
    released = threading.Event()

    def watcher() -> None:
        assert released.wait(timeout=5), "released was never set"
        if token.aborted:
            seen.set()

    thread = threading.Thread(target=watcher)
    thread.start()
    token.abort()
    released.set()
    thread.join(timeout=5)

    assert seen.is_set()
