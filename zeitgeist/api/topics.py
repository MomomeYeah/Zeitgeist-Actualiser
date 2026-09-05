"""The cross-run topics index.

Deduplicated on `label_slug`, which is the only cross-run identity the store
has: labels are model-generated every run, and the slug fixes case and
punctuation drift but not wording drift. A relabelled topic reads as new, so
`run_count` is a floor rather than a total — the UI says "seen in" rather
than claiming a count.
"""

from collections import Counter

from fastapi import APIRouter, Depends, Query

from zeitgeist.api.app import get_store
from zeitgeist.api.schemas import IndexedTopic, TopicIndex
from zeitgeist.models import TrendStatus
from zeitgeist.projection import TopicRow
from zeitgeist.store import Store

router = APIRouter(prefix="/api/topics", tags=["topics"])

# The design's header reads "across the last 6 runs".
DEFAULT_WINDOW = 6


def _sentiments(rows: list[TopicRow]) -> dict[str, int]:
    return dict(Counter(row.event_sentiment for row in rows if row.event_sentiment))


@router.get("", response_model=TopicIndex)
def read_index(
    window: int = Query(default=DEFAULT_WINDOW, ge=1, le=50),
    status: TrendStatus | None = None,
    store: Store = Depends(get_store),
) -> TopicIndex:
    run_ids = store.recent_run_ids(window + 1)
    in_window, previous = run_ids[:window], run_ids[window : window + 1]

    rows = store.topics_for_runs(in_window)
    # topics_for_runs is newest-run-first, so the first row for a slug is
    # its most recent occurrence — a deduplicated card shows current scores
    # rather than the first sighting's.
    newest: dict[str, TopicRow] = {}
    counts: Counter[str] = Counter()
    for row in rows:
        counts[row.label_slug] += 1
        newest.setdefault(row.label_slug, row)

    render_counts: dict[str, int] = {}
    for run_id in in_window:
        render_counts |= {
            f"{run_id}:{topic_id}": count
            for topic_id, count in store.render_counts(run_id).items()
        }

    selected = [
        row for row in newest.values() if status is None or row.trend_status == status
    ]
    return TopicIndex(
        topics=[
            IndexedTopic(
                topic=row,
                run_count=counts[row.label_slug],
                render_count=render_counts.get(f"{row.run_id}:{row.topic_id}", 0),
            )
            for row in selected
        ],
        # The whole window, not the filtered list: the chips show every
        # bucket's total while one of them is active.
        status_totals=dict(Counter(row.trend_status for row in newest.values())),
        sentiment_totals=_sentiments(list(newest.values())),
        previous_sentiment_totals=_sentiments(store.topics_for_runs(previous)),
    )
