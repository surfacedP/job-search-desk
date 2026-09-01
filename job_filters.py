from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class Job:
    job_id: str
    title: str
    company: str
    location: str
    url: str
    easy_apply: bool = True
    description: str = ""


def normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def contains_any(value: str, needles: Iterable[str]) -> bool:
    haystack = normalise(value)
    return any(normalise(needle) in haystack for needle in needles if needle.strip())


def matches(job: Job, filters: dict[str, Any]) -> bool:
    checks = (
        ("include_titles", job.title, True),
        ("exclude_titles", job.title, False),
        ("include_locations", job.location, True),
        ("exclude_locations", job.location, False),
        ("include_companies", job.company, True),
        ("exclude_companies", job.company, False),
    )
    for key, value, inclusive in checks:
        terms = filters.get(key) or []
        if terms and contains_any(value, terms) != inclusive:
            return False

    description = normalise(job.description)
    any_terms = filters.get("description_keywords_any") or []
    all_terms = filters.get("description_keywords_all") or []
    if any_terms and not any(normalise(term) in description for term in any_terms):
        return False
    if all_terms and not all(normalise(term) in description for term in all_terms):
        return False
    return True

