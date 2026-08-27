"""Recurring-phrase mining across a trend's replies.

Pure Python for the reason already recorded in scorers/bluesky.py:
reproducible and unit-testable, which a model's judgement is not. That
matters more here than elsewhere. A phrase one person wrote is that person's
joke; a phrase fifty people converged on independently is the zeitgeist, and
only a real count can tell those apart. Asked to do this itself, a model
would return plausible-sounding phrases with invented frequencies, and the
caption stage would quote them as though they were evidence.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Sequence

from zeitgeist.models import Phrase, Reply, TrendInfo

MIN_N = 2
MAX_N = 6
TOP_PHRASES = 15

# Drop the shorter phrase when the longer one retains at least this share of
# its distinct authors. If almost everyone who said the short form said the
# long form, the long form is the phrase; if most did not, the short form is
# genuinely more widely used and the longer is one sub-community's variant.
COLLAPSE_RATIO = 0.8

STOPWORDS = frozenset(
    """
    a about all also am an and any are as at be because been but by can could
    did do does doing don for from get got had has have he her hers him his
    how i if in into is it its just like me more most my no not now of off on
    once only or other our out over own re same she should so some such than
    that the their them then there these they this those through to too up us
    very was we were what when where which while who whom why will with would
    you your
    """.split()  # noqa: SIM905 -- a list literal here would be an unreadable
    # wall of quoted single words; the wrapped prose form stays legible.
)

_URL = re.compile(r"https?://\S+|\bwww\.\S+")
_MENTION = re.compile(r"@[\w.\-]+")
_NON_WORD = re.compile(r"[^a-z0-9' ]+")
_SPACE = re.compile(r"\s+")

# iOS and macOS auto-substitute the straight apostrophe for this typographic
# one; Android and most web clients emit the straight form. Left alone, one
# catchphrase produces two disjoint token sets and either half can fall
# under phrase_min_authors on its own.
_SMART_APOSTROPHE = "’"


def normalise(text: str) -> list[str]:
    """Lowercase, strip URLs, mentions and punctuation, split to tokens."""
    lowered = text.lower()
    lowered = lowered.replace(_SMART_APOSTROPHE, "'")
    lowered = _URL.sub(" ", lowered)
    lowered = _MENTION.sub(" ", lowered)
    lowered = _NON_WORD.sub(" ", lowered)
    tokens = _SPACE.sub(" ", lowered).strip().split()
    # Strip leading/trailing apostrophes so a quoted word ('finally') matches
    # the bare word elsewhere, but keep internal ones: don't must stay one
    # token, not split into don and t.
    return [token.strip("'") for token in tokens if token.strip("'")]


def mine_phrases(
    replies: list[Reply],
    trend: TrendInfo,
    *,
    min_authors: int,
    top: int = TOP_PHRASES,
) -> list[Phrase]:
    """Rank the phrases a trend's repliers actually converged on."""
    occurrences: Counter[tuple[str, ...]] = Counter()
    authors: defaultdict[tuple[str, ...], set[str]] = defaultdict(set)

    for reply in replies:
        # Deduplicated within a reply, so one person repeating a phrase four
        # times contributes one occurrence rather than four.
        for gram in _grams(normalise(reply.text)):
            occurrences[gram] += 1
            authors[gram].add(reply.author_key)

    subject = normalise(f"{trend.display_name} {trend.description}")

    candidates = [
        Phrase(
            text=" ".join(gram),
            occurrences=count,
            distinct_authors=len(authors[gram]),
        )
        for gram, count in occurrences.items()
        if len(authors[gram]) >= min_authors
        and not _contains(subject, gram)
        and not all(token in STOPWORDS for token in gram)
    ]

    kept = _collapse_substrings(candidates)
    kept.sort(key=lambda phrase: (-phrase.distinct_authors, -len(phrase.text)))
    return kept[:top]


def _grams(tokens: list[str]) -> set[tuple[str, ...]]:
    return {
        tuple(tokens[start : start + size])
        for size in range(MIN_N, MAX_N + 1)
        for start in range(len(tokens) - size + 1)
    }


def _contains(haystack: Sequence[str], needle: tuple[str, ...]) -> bool:
    """True when `needle` appears as a contiguous run inside `haystack`."""
    size = len(needle)
    return any(
        tuple(haystack[start : start + size]) == needle
        for start in range(len(haystack) - size + 1)
    )


def _collapse_substrings(phrases: list[Phrase]) -> list[Phrase]:
    """Drop a phrase wholly contained in a longer one that most of its
    authors also used. Without this, "imagination library" and "the
    imagination library" both surface and dilute the list.
    """
    tokens = {phrase.text: tuple(phrase.text.split()) for phrase in phrases}
    dropped: set[str] = set()

    for short in phrases:
        for long in phrases:
            if long.text == short.text:
                continue
            if len(tokens[long.text]) <= len(tokens[short.text]):
                continue
            if not _contains(tokens[long.text], tokens[short.text]):
                continue
            if long.distinct_authors >= COLLAPSE_RATIO * short.distinct_authors:
                dropped.add(short.text)
                break

    return [phrase for phrase in phrases if phrase.text not in dropped]
