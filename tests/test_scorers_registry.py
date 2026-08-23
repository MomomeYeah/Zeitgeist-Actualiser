"""Two registries can fall out of step. This is the guard, mirroring the
existing BUILDERS/KNOWN_SOURCES check in tests/test_sources_composite.py.
"""

from typing import get_args

from zeitgeist.analysis.scorers import SCORERS
from zeitgeist.models import Metrics
from zeitgeist.sources import BUILDERS

# BUILDERS vs KNOWN_SOURCES is already guarded by
# tests/test_sources_composite.py::test_every_known_source_has_a_builder,
# so it is deliberately not repeated here.


def _union_platforms() -> set[str]:
    """Every `platform` literal in the Metrics discriminated union."""
    # Metrics is Annotated[A | B | ..., Field(...)]; get_args()[0] is the union.
    union = get_args(Metrics)[0]
    return {
        get_args(member.model_fields["platform"].annotation)[0]
        for member in get_args(union)
    }


def test_every_metrics_platform_has_a_scorer():
    """The union and SCORERS must stay in step: a platform that can appear
    in an Item but has no scorer is a KeyError from build_scorer partway
    through a run, after the fetch has already been paid for.
    """
    assert _union_platforms() == set(SCORERS)


def test_every_source_has_a_scorer():
    """Subset, not equality: a metrics type may exist before its source
    does, which is how WikipediaMetrics lands in Task 1 while
    WikipediaSource arrives in Task 9. The reverse — a source whose items
    nothing can score — is the failure this catches.
    """
    assert set(BUILDERS) <= set(SCORERS)
