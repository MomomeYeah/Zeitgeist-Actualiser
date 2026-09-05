"""Distillation: one LLM call per trend, producing a topic and its dossier."""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel

from zeitgeist.analysis.distil import DistilError, DossierDraft, distil_topics
from zeitgeist.config import Settings
from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.models import (
    REGISTER_DEFINITIONS,
    SENTIMENT_DEFINITIONS,
    BlueskyMetrics,
    Item,
    PostEvidence,
    Register,
    Reply,
    Sentiment,
    Topic,
    TrendEvidence,
    TrendInfo,
    TrendStatus,
)
from zeitgeist.progress import Aborted, CancelToken

NOW = datetime(2026, 8, 26, tzinfo=UTC)

REPLY_TEXT = "UNIQUE-REPLY-BODY-SENTINEL"


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "sources": ["bluesky"],
        "distil_concurrency": 1,
        "phrase_min_authors": 3,
    }
    return Settings(**(base | overrides))


def _item(source_id: str, text: str = "something happened") -> Item:
    return Item(
        source_id=source_id,
        title=text,
        permalink=f"https://bsky.app/profile/x/post/{source_id}",
        fetched_at=NOW,
        metrics=BlueskyMetrics(
            like_count=10,
            reply_count=2,
            repost_count=1,
            trend="A trend",
            status="trending",
            created_at=NOW,
        ),
    )


def _reply(text: str, author: str = "a", likes: int = 1) -> Reply:
    return Reply(text=text, like_count=likes, created_at=NOW, author_key=author)


def _evidence(
    name: str = "Canada announces retaliatory tariffs",
    *,
    replies: list[Reply] | None = None,
    posts: int = 1,
    status: TrendStatus = "stale",
) -> TrendEvidence:
    return TrendEvidence(
        trend=TrendInfo(
            topic_id=f"id-{name}",
            display_name=name,
            description="Canada hits back after trade talks collapsed.",
            category="business",
            post_count=4298,
            started_at=NOW,
            status=status,
        ),
        posts=[
            PostEvidence(item=_item(f"p{i}"), replies=replies or [])
            for i in range(posts)
        ],
    )


def _draft(**overrides: Any) -> DossierDraft:
    base: dict[str, Any] = {
        "what_happened": "Canada imposed tariffs on $30B of US goods.",
        "key_entities": ["Canada"],
        "conversation_summary": "People treat it as overdue.",
        "conversation_register": Register.DUNKING,
        "secondary_registers": [],
        "event_sentiment": Sentiment.SCHADENFREUDE,
        "meme_potential": 0.8,
    }
    return DossierDraft(**(base | overrides))


def test_a_trend_becomes_a_topic_carrying_its_dossier():
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence()], provider, _settings())

    assert topic.label == "Canada announces retaliatory tariffs"
    assert topic.id == "canada-announces-retaliatory-tariffs"
    assert topic.item_ids == ["p0"]
    assert topic.dossier is not None
    assert topic.dossier.conversation_register is Register.DUNKING


def test_the_summary_is_what_happened_not_a_tag_confabulation():
    """The whole point: `summary` used to be written from a bag of tags."""
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence()], provider, _settings())
    assert topic.summary == "Canada imposed tariffs on $30B of US goods."


def test_mined_phrases_are_attached_rather_than_taken_from_the_model():
    replies = [_reply("elbows up", author=a) for a in ("a", "b", "c", "d")]
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence(replies=replies)], provider, _settings())

    assert topic.dossier is not None
    assert [p.text for p in topic.dossier.recurring_phrases] == ["elbows up"]
    assert topic.dossier.recurring_phrases[0].distinct_authors == 4


def test_the_prompt_carries_the_trend_description_and_the_replies():
    replies = [_reply("what a mess", author=a) for a in ("a", "b", "c")]
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics([_evidence(replies=replies)], provider, _settings())

    prompt = provider.calls[0].prompt
    assert "Canada hits back after trade talks collapsed." in prompt
    assert "what a mess" in prompt


def test_the_prompt_carries_each_posts_engagement():
    """The spec asks for posts "with their engagement". The trend name was
    being repeated in a bracket instead — a constant already stated on the
    prompt's first line, carrying no information — so this must assert the
    actual like/repost/reply counts reach the prompt, not merely that the
    post appears at all.
    """
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics([_evidence()], provider, _settings())

    prompt = provider.calls[0].prompt
    assert "10 likes, 1 reposts, 2 replies" in prompt


def test_the_prompt_states_how_many_people_used_each_phrase():
    """The counts are what license quoting, so they must reach the model with
    their meanings intact. The two numbers differ here — five uses from four
    accounts — so rendering one in place of the other fails. Equal counts
    would make the swap invisible, and a bare "4" also matches the post count.
    """
    replies = [_reply("elbows up", author=a) for a in ("a", "b", "c", "d")]
    replies.append(_reply("elbows up again", author="a"))
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics([_evidence(replies=replies)], provider, _settings())

    assert "4 distinct accounts, 5 uses" in provider.calls[0].prompt


def test_replies_are_truncated_to_the_character_budget():
    """Exactly two 500-character replies fit in a 1000-character budget. An
    upper bound alone would pass even if no replies were included at all.
    """
    replies = [_reply("x" * 500, author=f"a{i}") for i in range(50)]
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics(
        [_evidence(replies=replies)], provider, _settings(distil_char_budget=1000)
    )
    assert provider.calls[0].prompt.count("x" * 500) == 2


def test_the_most_liked_replies_are_the_ones_kept():
    replies = [
        _reply("unpopular take", author="a", likes=1),
        _reply("the one everyone saw", author="b", likes=900),
    ]
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics(
        [_evidence(replies=replies)], provider, _settings(distil_char_budget=30)
    )
    prompt = provider.calls[0].prompt
    assert "the one everyone saw" in prompt
    assert "unpopular take" not in prompt


def test_break_not_continue_stops_sampling_at_the_first_overflow():
    """`_sample` stops at the first reply that would overflow the budget
    (`break`), rather than skipping it and packing smaller replies from
    further down the list (`continue`). Both are defensible policies, but
    only `break` matches "take the top contiguous slice by likes" -- the
    intended one.

    Budget is 100. The most-liked reply is 40 chars and fits (spent -> 40).
    The second-most-liked is 80 chars, which would bring spent to 120 and
    overflow; under `break` sampling stops there. The third-most-liked is
    20 chars -- small enough that 40 + 20 = 60 <= 100, so it WOULD fit if
    scanning continued past the oversized second reply. Its absence from
    the prompt is what distinguishes the two policies; the first reply's
    presence rules out sampling returning nothing at all.
    """
    replies = [
        _reply("a" * 40, author="a", likes=100),
        _reply("b" * 80, author="b", likes=50),
        _reply("c" * 20, author="c", likes=10),
    ]
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics(
        [_evidence(replies=replies)], provider, _settings(distil_char_budget=100)
    )
    prompt = provider.calls[0].prompt
    assert "a" * 40 in prompt
    assert "c" * 20 not in prompt


def test_a_failing_trend_is_dropped_and_the_rest_survive():
    provider = FakeLLMProvider(responses=[LLMError("boom"), _draft()])
    topics = distil_topics(
        [_evidence("First"), _evidence("Second")], provider, _settings()
    )
    assert [topic.label for topic in topics] == ["Second"]


def test_every_trend_failing_raises_distil_error():
    """The design spec: "A run in which every trend fails raises, as an
    empty run is a failure rather than a result." Returning `[]` here would
    write empty topics.json/ranked.json/briefs.json and let the CLI print a
    green "Run complete" with 0 memes and no diagnostic — this is the
    realistic failure mode for a local model that cannot hold the response
    schema, since it fails every trend identically.
    """
    provider = FakeLLMProvider(responses=[LLMError("boom"), LLMError("boom")])
    with pytest.raises(DistilError):
        distil_topics([_evidence("First"), _evidence("Second")], provider, _settings())


def test_topic_ids_are_unique_when_two_trends_share_a_label():
    provider = FakeLLMProvider(responses=[_draft(), _draft()])
    topics = distil_topics(
        [_evidence("A trend"), _evidence("A trend")], provider, _settings()
    )
    assert {topic.id for topic in topics} == {"a-trend", "a-trend-2"}


def test_a_trend_with_no_replies_still_produces_a_topic():
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence(replies=[])], provider, _settings())
    assert topic.dossier is not None
    assert topic.dossier.recurring_phrases == []


def test_item_ids_cover_every_post_under_the_trend():
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence(posts=3)], provider, _settings())
    assert topic.item_ids == ["p0", "p1", "p2"]


def test_no_evidence_means_no_calls():
    provider = FakeLLMProvider(responses=[])
    assert distil_topics([], provider, _settings()) == []
    assert provider.calls == []


def test_the_prompt_lists_every_taxonomy_member_with_its_definition():
    """The model never sees a JSON-schema enum as readable text.

    Ollama compiles `format` into a grammar: the enum values constrain which
    strings are emittable, but the member list and any `description` are not
    shown to the model to reason about. A taxonomy that lives only in the
    schema is therefore invisible, and the model picks a member that
    satisfies the grammar without meaning it.

    Measured against qwen3.5 with the production schema: with the members in
    the schema alone, "Death of artist Yayoi Kusama" came back `gross` and
    "Flash floods hit Nepal-Tibet border" came back `gross`/`gallows`. With
    the same members rendered into the prompt, `sad`/`tribute` and
    `sad`/`mourning`.
    """
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics([_evidence()], provider, _settings())
    prompt = provider.calls[0].prompt

    for member in Sentiment:
        assert member.value in prompt, f"sentiment {member.value} missing"
        assert SENTIMENT_DEFINITIONS[member] in prompt
    for member in Register:
        assert member.value in prompt, f"register {member.value} missing"
        assert REGISTER_DEFINITIONS[member] in prompt


def test_the_prompt_states_the_numeric_ranges():
    """`minimum`/`maximum` in the schema are advisory: a grammar can enforce
    which strings are legal but not arithmetic, so the model is free to emit
    4.2 for a 0-1 field. Saying the range in the prompt is the only place it
    is actually read.
    """
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics([_evidence()], provider, _settings())
    prompt = provider.calls[0].prompt
    assert "0.0 and 1.0" in prompt


@pytest.mark.parametrize(
    "field,value",
    [
        ("meme_potential", 4.2),
        ("meme_potential", -0.5),
    ],
)
def test_an_unusable_scalar_becomes_none_rather_than_losing_the_dossier(field, value):
    """Both observed live. A grammar cannot enforce a numeric range, so the
    model can always emit one of these — and nothing downstream reads either
    field. Rejecting the whole draft would discard what_happened, the
    conversation summary, the register and the mined phrases over a scalar
    no consumer touches. None records "the model gave no usable number",
    which is true, rather than clamping to a bound, which would not be.
    """
    draft = DossierDraft.model_validate(_draft().model_dump() | {field: value})
    assert getattr(draft, field) is None


def test_a_trend_with_an_unusable_scalar_still_produces_a_topic():
    provider = FakeLLMProvider(
        responses=[
            DossierDraft.model_validate(_draft().model_dump() | {"meme_potential": 4.2})
        ]
    )
    [topic] = distil_topics([_evidence()], provider, _settings())
    assert topic.dossier is not None
    assert topic.dossier.meme_potential is None
    assert topic.dossier.what_happened == "Canada imposed tariffs on $30B of US goods."


@pytest.mark.parametrize("value", [0.0, 1.0, 0.5])
def test_an_in_range_scalar_is_preserved_exactly(value):
    """The coercion must not swallow good values along with bad ones."""
    draft = DossierDraft.model_validate(
        _draft().model_dump() | {"meme_potential": value}
    )
    assert draft.meme_potential == value


@pytest.mark.parametrize("field", ["meme_potential"])
def test_the_scalars_stay_required_in_the_schema(field):
    """Nullable, but not optional. A default takes the field out of the
    schema's `required` list and the model then omits it outright — measured
    against qwen3.5, meme_potential went missing on 1 run in 3 once it had a
    default. Nullable absorbs the out-of-range value a grammar cannot
    prevent; required keeps the model from skipping the question.
    """
    assert field in DossierDraft.model_json_schema()["required"]


@pytest.mark.parametrize("field", ["meme_potential"])
def test_an_explicit_null_is_accepted(field):
    """The model may answer null now that the schema permits it, and that is
    a better outcome than an invented number.
    """
    draft = DossierDraft.model_validate(_draft().model_dump() | {field: None})
    assert getattr(draft, field) is None


def test_distil_carries_the_trend_status_onto_the_topic():
    """The status is Bluesky's own read on the trend's movement. It reaches
    the topic here or not at all — no later stage sees the evidence."""
    evidence = _evidence(status="cooling")
    provider = FakeLLMProvider(responses=[_draft()])

    [topic] = distil_topics([evidence], provider, Settings(_env_file=None))

    assert topic.trend_status == "cooling"


class _ScriptedProvider:
    """A provider that runs a per-call hook and returns a per-call draft, so
    a test can control both the order two concurrent distillations finish in
    and which draft each one produced.

    `FakeLLMProvider` pops from a shared list with no lock, so it cannot
    script concurrent calls: two workers popping at once is a race, and the
    test would be asserting on whichever ordering it happened to get.

    The unmatched-prompt branch raises rather than returning a default: a
    double that accepts anything would let a mis-scripted test pass while
    verifying nothing.
    """

    name = "scripted"

    def __init__(
        self, script: dict[str, tuple[Callable[[], None] | None, DossierDraft]]
    ) -> None:
        self._script = script

    def complete(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        for marker, (hook, draft) in self._script.items():
            if marker in prompt:
                if hook is not None:
                    hook()
                return draft
        raise AssertionError("no script entry matched this prompt")


def test_a_topic_is_reported_while_later_trends_are_still_running():
    """This is the whole point of the callback: the mid-analyse screen appends
    ranking rows as they arrive. An implementation that collected every result
    and then called `on_topic` in a loop at the end would satisfy every other
    test in this file — same topics, same order, same count — and show the
    user nothing until the stage finished.

    So the assertion is an ordering across threads: the callback for the first
    trend must fire before the second trend's model call returns.
    """
    reported_cats = threading.Event()
    order: list[str] = []

    def dogs_call() -> None:
        order.append("dogs-call-start")
        assert reported_cats.wait(timeout=5), "cats not reported within timeout"
        order.append("dogs-call-end")

    provider = _ScriptedProvider(
        {"Cats": (None, _draft()), "Dogs": (dogs_call, _draft())}
    )

    def on_topic(topic: Topic) -> None:
        order.append(f"reported:{topic.id}")
        if topic.id == "cats":
            reported_cats.set()

    distil_topics(
        [_evidence("Cats"), _evidence("Dogs")],
        provider,
        _settings(distil_concurrency=2),
        on_topic=on_topic,
    )

    assert order.index("reported:cats") < order.index("dogs-call-end")


def test_topic_ids_do_not_depend_on_which_trend_finishes_first():
    """Ids come from `unique_slug`, which suffixes on collision using a set
    that accumulates in iteration order. Reporting as futures *complete*
    rather than in submission order would give this input `a-trend` and
    `a-trend-2` in whichever order the pool happened to finish — so the same
    evidence would produce different ids run to run, and resume, which keys
    on the id, would break.

    Both trends share a label, because that is the only shape in which the
    bug is observable: with distinct display names `unique_slug` never
    collides, the ids are fixed by the names alone, and a half-fix that
    iterated by completion and then sorted the *list* back into evidence
    order would pass while assigning the ids the wrong way round.

    Here the second trend finishes first. The first must still get `a-trend`,
    and the drafts prove which topic is which.
    """
    second_done = threading.Event()
    first = _draft(what_happened="the first one")
    second = _draft(what_happened="the second one")

    def wait_for_second() -> None:
        assert second_done.wait(timeout=5), "second trend did not finish first"

    provider = _ScriptedProvider(
        {
            "marker-first": (wait_for_second, first),
            "marker-second": (second_done.set, second),
        }
    )

    topics = distil_topics(
        [
            _evidence("A trend", replies=[_reply("marker-first")]),
            _evidence("A trend", replies=[_reply("marker-second")]),
        ],
        provider,
        _settings(distil_concurrency=2),
    )

    assert [(topic.id, topic.summary) for topic in topics] == [
        ("a-trend", "the first one"),
        ("a-trend-2", "the second one"),
    ]


def test_a_failed_trend_consumes_no_id():
    """`used_ids` must only record ids that were actually handed out.
    Pre-assigning a slug to every trend before distillation — a tempting way
    to make ids independent of completion order — would let a *failed* trend
    reserve `a-trend`, pushing the trend that succeeded to `a-trend-2` for no
    reason a reader of the output could reconstruct.

    Both trends share a label for the same reason as the test above: with
    distinct names there is no collision, so a pre-assigned id and a lazily
    assigned one are indistinguishable and the bug is invisible.

    `FakeLLMProvider` is safe here because `distil_concurrency=1` means only
    one worker ever pops from its response list; the race its own docstring
    warns about needs two.
    """
    provider = FakeLLMProvider(responses=[LLMError("no"), _draft()])

    topics = distil_topics(
        [_evidence("A trend"), _evidence("A trend")],
        provider,
        _settings(distil_concurrency=1),
    )

    assert [topic.id for topic in topics] == ["a-trend"]


def test_an_aborted_token_stops_the_stage_rather_than_failing_every_trend():
    """`_distil_one` catches bare `Exception` so one bad trend is dropped
    rather than failing the run. `Aborted` must escape that handler: caught,
    every trend would report as failed and the caller would see `DistilError`
    — "all trends failed distillation" — for a run the user deliberately
    cancelled. The two outcomes are indistinguishable to the worker, which
    would then record the wrong terminal status.
    """
    token = CancelToken()
    token.abort()
    provider = _ScriptedProvider({"Cats": (None, _draft())})

    with pytest.raises(Aborted):
        distil_topics(
            [_evidence("Cats")],
            provider,
            _settings(distil_concurrency=1),
            token=token,
        )


def test_a_trend_that_fails_is_not_reported():
    """The callback appends a ranking row. A dropped trend has no topic, so
    reporting one would put a row on the screen for something that does not
    exist in the checkpoint.
    """
    reported: list[str] = []
    provider = FakeLLMProvider(responses=[LLMError("no")])

    with pytest.raises(DistilError):
        distil_topics(
            [_evidence("Cats")],
            provider,
            _settings(distil_concurrency=1),
            on_topic=lambda topic: reported.append(topic.id),
        )

    assert reported == []


def test_each_topic_logs_its_reply_count_and_prompt_size_at_debug(caplog):
    """The verbose toggle's counterpart on the analyse stage: seeing three
    replies distilled into a several-thousand-character prompt is how a
    thin trend is told apart from a broken one.

    Asserted on `record.args`, never on the formatted string. The reply
    count is this fixture's own construction; the prompt-character count is
    taken from the exact prompt the fixture produces (the same string
    `provider.calls[0].prompt` already exposes elsewhere in this file), not
    from the replies' text — the wrong-argument mutation this guards
    against is the two counts swapped, or one logged twice.
    """
    replies = [_reply("what a mess", author=a) for a in ("a", "b", "c")]
    provider = FakeLLMProvider(responses=[_draft()])

    with caplog.at_level(logging.DEBUG, logger="zeitgeist.analysis.distil"):
        distil_topics([_evidence(replies=replies)], provider, _settings())

    prompt = provider.calls[0].prompt
    starting_records = [
        record.args
        for record in caplog.records
        if record.levelno == logging.DEBUG
        and record.name == "zeitgeist.analysis.distil"
        and len(record.args) == 3
    ]
    assert starting_records == [
        ("Canada announces retaliatory tariffs", 3, len(prompt))
    ]


def test_distil_logs_elapsed_time_per_topic_at_debug(caplog):
    """A duration is not hand-derivable, so unlike the line above this only
    pins the trend name and the type of the second argument.
    """
    provider = FakeLLMProvider(responses=[_draft()])

    with caplog.at_level(logging.DEBUG, logger="zeitgeist.analysis.distil"):
        distil_topics([_evidence()], provider, _settings())

    elapsed_records = [
        record.args
        for record in caplog.records
        if record.levelno == logging.DEBUG
        and record.name == "zeitgeist.analysis.distil"
        and len(record.args) == 2
    ]
    [(name, elapsed)] = elapsed_records
    assert name == "Canada announces retaliatory tariffs"
    assert isinstance(elapsed, float)


def test_no_debug_record_carries_reply_text(caplog):
    """distil is the stage that actually reads reply bodies to build the
    prompt, so it is the one most at risk of a debug line that echoes one
    back. This asserts on the rendered message, which only interpolates
    once a handler is attached, so a lazily-formatted line cannot slip text
    through unexamined.
    """
    provider = FakeLLMProvider(responses=[_draft()])

    with caplog.at_level(logging.DEBUG, logger="zeitgeist.analysis.distil"):
        distil_topics([_evidence(replies=[_reply(REPLY_TEXT)])], provider, _settings())

    for record in caplog.records:
        assert REPLY_TEXT not in record.getMessage()
