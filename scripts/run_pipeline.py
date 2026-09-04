"""Run the pipeline once, for development.

Not a CLI. A CLI is a product surface — installed, documented, tested as a
contract — and the web UI is that now. This is fifteen lines that call
`run_pipeline` so a run can be produced before the API can start one, and it
stays afterwards because scripted and repeated runs during development are
useful.

    uv run python scripts/run_pipeline.py
"""

import logging
import sys

from zeitgeist.config import Settings
from zeitgeist.llm.factory import build_provider
from zeitgeist.pipeline import new_run_id, run_pipeline
from zeitgeist.sources import build_trend_source
from zeitgeist.store import Store


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    settings = Settings()
    store = Store(settings.db_path)
    try:
        store.init_schema()
        run_id = run_pipeline(
            settings=settings,
            source=build_trend_source(settings),
            provider=build_provider(settings),
            store=store,
            run_id=new_run_id(),
        )
        record = store.get_run(run_id)
    finally:
        store.close()
    print(f"Run complete: {run_id} ({record.item_count if record else 0} items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
