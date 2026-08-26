"""Label-to-identifier helpers.

Lives in its own module because both the live distillation path and the
dormant consolidation path need it, and the live path must not import from
a module that no longer runs.
"""

import re


def slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return slug or "topic"


def unique_slug(label: str, used: set[str]) -> str:
    """Slugify `label`, suffixing until unique. Records the result in `used`."""
    base = slugify(label)
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate
