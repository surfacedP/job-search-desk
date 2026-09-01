from __future__ import annotations

import argparse
import csv
import random
import re
import sys
import time
from dataclasses import asdict, fields
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

import yaml
from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from job_filters import Job, matches, normalise
from job_store import initialise as initialise_database, upsert_jobs


SEARCH_URL = "https://www.linkedin.com/jobs/search/?{}"


def text_from(parent: Locator, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            target = parent.locator(selector).first
            if target.count():
                text = target.inner_text(timeout=1_500).strip()
                if text:
                    return re.sub(r"\s+", " ", text)
        except PlaywrightTimeoutError:
            pass
    return ""


def extract_cards(page: Page, easy_apply_only: bool) -> list[Job]:
    cards = page.locator("li.jobs-search-results__list-item, li[data-occludable-job-id]")
    jobs: list[Job] = []
    for index in range(cards.count()):
        card = cards.nth(index)
        easy_apply_text = text_from(card, [".job-card-container__apply-method", ".job-card-list__footer-wrapper"])
        is_easy_apply = "easy apply" in normalise(easy_apply_text)
        if is_easy_apply != easy_apply_only:
            continue
        link = card.locator("a[href*='/jobs/view/']").first
        if not link.count():
            continue
        href = (link.get_attribute("href") or "").split("?")[0]
        match = re.search(r"/jobs/view/(\d+)", href)
        if not match:
            continue
        jobs.append(Job(
            job_id=match.group(1),
            title=text_from(card, [".job-card-list__title--link", ".job-card-container__link", "a[href*='/jobs/view/']"]),
            company=text_from(card, [".artdeco-entity-lockup__subtitle", ".job-card-container__primary-description"]),
            location=text_from(card, [".artdeco-entity-lockup__caption", ".job-card-container__metadata-wrapper"]),
            url=f"https://www.linkedin.com/jobs/view/{match.group(1)}/",
            easy_apply=is_easy_apply,
        ))
    return jobs


def fetch_description(page: Page, job: Job) -> Job:
    page.goto(job.url, wait_until="domcontentloaded", timeout=30_000)
    text = text_from(page, [".jobs-description__content", ".jobs-box__html-content", "#job-details"])
    return Job(**{**asdict(job), "description": text})


def search_url(keywords: str, location: str, start: int, easy_apply_only: bool) -> str:
    params = {
        "keywords": keywords,
        "location": location,
        "start": start,
    }
    if easy_apply_only:
        # f_AL=true is LinkedIn's Easy Apply search facet.
        params["f_AL"] = "true"
    return SEARCH_URL.format(urlencode(params))


def sleep_politely(seconds: float) -> None:
    time.sleep(max(0.0, seconds + random.uniform(0.0, seconds * 0.35)))


def save_csv(path: Path, jobs: Iterable[Job]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(jobs)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=[field.name for field in fields(Job)])
        writer.writeheader()
        writer.writerows(asdict(job) for job in rows)


def load_jobs_csv(path: Path) -> dict[str, Job]:
    if not path.exists():
        return {}
    jobs: dict[str, Job] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            job_id = row.get("job_id", "").strip()
            if not job_id:
                continue
            jobs[job_id] = Job(
                job_id=job_id,
                title=row.get("title", ""),
                company=row.get("company", ""),
                location=row.get("location", ""),
                url=row.get("url", ""),
                easy_apply=normalise(row.get("easy_apply", "true")) in {"true", "1", "yes"},
                description=row.get("description", ""),
            )
    return jobs


def update_master_csv(path: Path, recovered_jobs: Iterable[Job], current_jobs: Iterable[Job]) -> int:
    """Merge jobs into the user-editable CSV while preserving notes and custom columns."""
    job_fields = [field.name for field in fields(Job)]
    standard_fields = job_fields + ["status", "notes", "first_seen", "last_seen"]
    fieldnames: list[str] = []
    rows: dict[str, dict[str, str]] = {}

    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            for row in reader:
                job_id = row.get("job_id", "").strip()
                if job_id:
                    rows[job_id] = dict(row)

    for name in standard_fields:
        if name not in fieldnames:
            fieldnames.append(name)

    today = date.today().isoformat()

    def merge(job: Job, seen_now: bool) -> None:
        row = rows.setdefault(job.job_id, {name: "" for name in fieldnames})
        # Update scraper-managed fields only. User-added fields, status, and notes
        # remain untouched on later runs.
        for name, value in asdict(job).items():
            row[name] = str(value)
        if not row.get("first_seen"):
            row["first_seen"] = today
        if seen_now:
            row["last_seen"] = today
        row.setdefault("status", "")
        row.setdefault("notes", "")

    # Recover rows retained by the old history file, then merge this run.
    for job in recovered_jobs:
        if job.job_id not in rows:
            merge(job, seen_now=False)
    for job in current_jobs:
        merge(job, seen_now=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows.values())
    temporary.replace(path)
    return len(rows)


def ask_easy_apply() -> bool:
    while True:
        answer = input("Search Easy Apply jobs only? [Y/n]: ").strip().casefold()
        if answer in {"", "y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please enter Y for Easy Apply jobs or N for external-application jobs.")


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if not config.get("searches"):
        raise ValueError("config must contain at least one item under 'searches'")
    return config


def run(config_path: Path, mode: str | None = None, dashboard: bool = False) -> int:
    config = load_config(config_path)
    settings = config.get("settings") or {}
    filters = config.get("filters") or {}
    base_dir = config_path.parent
    profile = (base_dir / settings.get("browser_profile", ".browser-profile")).resolve()
    output = (base_dir / settings.get("output_csv", "jobs.csv")).resolve()
    history_path = (base_dir / settings.get("history_csv", "job_history.csv")).resolve()
    database_path = (base_dir / settings.get("database", "jobs.db")).resolve()
    max_pages = int(settings.get("max_pages_per_search", 3))
    delay = float(settings.get("delay_seconds", 3.0))
    fetch_descriptions = bool(settings.get("fetch_descriptions", False))
    if mode is None:
        mode = "easy" if ask_easy_apply() else "external"
    modes = [True, False] if mode == "both" else [mode == "easy"]
    mode_name = {
        "easy": "Easy Apply",
        "external": "external application",
        "both": "Easy Apply and external application",
    }[mode]
    print(f"Mode: {mode_name} jobs")

    # Seed history from the previous output when upgrading from versions that
    # did not yet maintain job_history.csv.
    history = load_jobs_csv(history_path)
    history.update(load_jobs_csv(output))
    found: dict[str, Job] = {}

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile), headless=bool(settings.get("headless", False)), viewport={"width": 1440, "height": 1000}
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.linkedin.com/jobs/", wait_until="domcontentloaded")
        if "/login" in page.url or page.locator("input[name='session_key']").count():
            if dashboard:
                print("Log in to LinkedIn in the opened browser. Waiting for login…")
                deadline = time.monotonic() + 300
                while time.monotonic() < deadline:
                    page.wait_for_timeout(1_000)
                    if "/login" not in page.url and not page.locator("input[name='session_key']").count():
                        break
                else:
                    raise RuntimeError("LinkedIn login was not completed within five minutes")
            else:
                print("Log in to LinkedIn in the opened browser, then press Enter here.")
                input()

        total_searches = len(config["searches"]) * len(modes)
        completed_searches = 0
        for easy_apply_only in modes:
            current_mode_name = "Easy Apply" if easy_apply_only else "external application"
            for search in config["searches"]:
                keywords = str(search.get("keywords", ""))
                location = str(search.get("location", ""))
                completed_searches += 1
                for page_number in range(max_pages):
                    print(
                        f"[{completed_searches}/{total_searches}] Searching {current_mode_name}: "
                        f"{keywords!r} in {location!r}, page {page_number + 1}"
                    )
                    url = search_url(keywords, location, page_number * 25, easy_apply_only)
                    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    page.wait_for_timeout(2_000)
                    page.locator("main").press("End")
                    page.wait_for_timeout(1_000)
                    cards = extract_cards(page, easy_apply_only)
                    if not cards:
                        print(f"No {current_mode_name} cards found; stopping this search.")
                        break
                    for job in cards:
                        if matches(job, filters):
                            found[job.job_id] = job
                    sleep_politely(delay)

        if fetch_descriptions:
            candidates: dict[str, Job] = {}
            for job_id, job in found.items():
                detailed = fetch_description(page, job)
                if matches(detailed, filters):
                    candidates[job_id] = detailed
                sleep_politely(delay)
            found = candidates
        context.close()

    new_jobs = {job_id: job for job_id, job in found.items() if job_id not in history}
    duplicate_count = len(found) - len(new_jobs)
    history.update(found)
    master_count = update_master_csv(output, history.values(), found.values())
    save_csv(history_path, history.values())
    initialise_database(database_path)
    upsert_jobs(database_path, found.values())
    print(f"Added {len(new_jobs)} new matching jobs to {output}")
    print(f"Skipped {duplicate_count} previously seen jobs")
    print(f"Master CSV now contains {master_count} jobs; existing notes were preserved")
    print(f"Deduplication history contains {len(history)} jobs at {history_path}")
    print("Open the dashboard to review and annotate your results")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Find matching LinkedIn jobs and update the local dashboard.")
    parser.add_argument("--config", type=Path, default=Path("config.yml"))
    parser.add_argument("--mode", choices=("easy", "external", "both"))
    parser.add_argument("--dashboard", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        return run(args.config.resolve(), args.mode, args.dashboard)
    except (OSError, RuntimeError, ValueError, yaml.YAMLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
