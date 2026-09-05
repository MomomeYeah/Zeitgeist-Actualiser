"""The seams a run is watched and cancelled through.

Both default to no-ops, so a caller wanting neither — a test, or
`scripts/run_pipeline.py` — constructs neither and the pipeline behaves
exactly as it did before either existed.
"""

from dataclasses import dataclass, field
from typing import Protocol

from zeitgeist.models import Topic
from zeitgeist.records import RenderRecord, Stage


class Aborted(Exception):
    """Raised from `CancelToken.check()` when a run has been aborted.

    Its own type rather than a flag return, because it has to unwind out of
    the distil worker's thread pool and out of the render loop, both of
    which are several frames below the code that can act on it.
    """


class RunObserver(Protocol):
    """What a watcher of a run is told, as it happens.

    Every method returns None and none may raise: an observer is a reporting
    seam, and a run must not fail because something watching it did.
    """

    def stage_started(self, stage: Stage) -> None: ...

    def stage_progress(
        self, stage: Stage, done: int, total: int, detail: str
    ) -> None: ...

    def stage_finished(self, stage: Stage, payload_bytes: int | None) -> None:
        """`payload_bytes` is the checkpoint's size rather than its path,
        because checkpoints are rows now. `None` is a stage that wrote no
        payload, which is a failed or a skipped one.
        """
        ...

    def topic_distilled(self, topic: Topic) -> None: ...

    def render_finished(self, render: RenderRecord) -> None:
        """The whole record rather than a brief and a path: it already holds
        the outcome, including `status="failed"` and its error, which is how
        a per-meme failure reaches the UI as a tile with a message rather
        than vanishing.
        """
        ...


class NullObserver:
    """The default. Every method does nothing."""

    def stage_started(self, stage: Stage) -> None:
        return None

    def stage_progress(self, stage: Stage, done: int, total: int, detail: str) -> None:
        return None

    def stage_finished(self, stage: Stage, payload_bytes: int | None) -> None:
        return None

    def topic_distilled(self, topic: Topic) -> None:
        return None

    def render_finished(self, render: RenderRecord) -> None:
        return None


@dataclass(frozen=True)
class ObservedEvent:
    name: str
    payload: tuple[object, ...]


@dataclass
class RecordingObserver:
    """Test double recording the call sequence.

    Beside the Protocol rather than in `tests/` for the same reason
    `FakeLLMProvider` sits beside `LLMProvider`: a double that drifts from
    the interface it stands in for is worse than no double.
    """

    events: list[ObservedEvent] = field(default_factory=list)

    def stage_started(self, stage: Stage) -> None:
        self.events.append(ObservedEvent("stage_started", (stage,)))

    def stage_progress(self, stage: Stage, done: int, total: int, detail: str) -> None:
        self.events.append(
            ObservedEvent("stage_progress", (stage, done, total, detail))
        )

    def stage_finished(self, stage: Stage, payload_bytes: int | None) -> None:
        self.events.append(ObservedEvent("stage_finished", (stage, payload_bytes)))

    def topic_distilled(self, topic: Topic) -> None:
        self.events.append(ObservedEvent("topic_distilled", (topic,)))

    def render_finished(self, render: RenderRecord) -> None:
        self.events.append(ObservedEvent("render_finished", (render,)))

    def named(self, name: str) -> list[ObservedEvent]:
        """Every event of one kind, in order. The pipeline's tests assert on
        one event type at a time far more often than on the whole stream.
        """
        return [event for event in self.events if event.name == name]


class CancelToken:
    """Two different cancellations, deliberately not one flag.

    *Stop* lets the current stage finish and write its checkpoint, so the run
    stays resumable — which is what the button promises. *Abort* unwinds the
    current work now, and the run is whatever it managed to write.

    So `check()` raises only for abort. A stopping token's `check()` returns
    normally, and `stopping` is read at the stage boundary instead.

    Written by the request thread handling `POST /api/runs/{id}/abort` and
    read by the worker thread. No lock: a `bool` assignment is atomic under
    the GIL, and these flags are set once and never cleared — a token belongs
    to one run and is never reset, so there is no read-modify-write to lose.
    """

    def __init__(self) -> None:
        self._stopping = False
        self._aborted = False

    def stop_after_stage(self) -> None:
        self._stopping = True

    def abort(self) -> None:
        # Order matters for a reader that lands between the two assignments:
        # setting `_stopping` first leaves no window where `aborted` is true
        # but `stopping` is false, which is the window in which a stage
        # boundary would start one more stage.
        self._stopping = True
        self._aborted = True

    def check(self) -> None:
        if self._aborted:
            raise Aborted("run aborted")

    @property
    def stopping(self) -> bool:
        """True after either call: both mean this run is ending, and the
        stage boundary must not begin another stage.
        """
        return self._stopping

    @property
    def aborted(self) -> bool:
        """Which of the two happened, and so which terminal status the run
        gets.
        """
        return self._aborted
