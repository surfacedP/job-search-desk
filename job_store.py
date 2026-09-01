from __future__ import annotations

import csv
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator

from job_filters import Job


VALID_STATUSES = {"unreviewed", "applied", "maybe", "not_applying", "hidden"}


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialise(path: Path) -> None:
    with connect(path) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                company TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                easy_apply INTEGER NOT NULL DEFAULT 0 CHECK (easy_apply IN (0, 1)),
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'unreviewed',
                notes TEXT NOT NULL DEFAULT '',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen DESC)")
        db.execute("PRAGMA optimize")


def upsert_jobs(path: Path, jobs: Iterable[Job], seen_on: str | None = None) -> int:
    today = seen_on or date.today().isoformat()
    rows = list(jobs)
    with connect(path) as db:
        db.executemany(
            """
            INSERT INTO jobs (
                job_id, title, company, location, url, easy_apply, description,
                status, notes, first_seen, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'unreviewed', '', ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                location = excluded.location,
                url = excluded.url,
                easy_apply = excluded.easy_apply,
                description = CASE
                    WHEN excluded.description != '' THEN excluded.description
                    ELSE jobs.description
                END,
                last_seen = excluded.last_seen
            """,
            [
                (
                    job.job_id, job.title, job.company, job.location, job.url,
                    int(job.easy_apply), job.description, today, today,
                )
                for job in rows
            ],
        )
    return len(rows)


def import_csv(path: Path, csv_path: Path) -> int:
    if not csv_path.exists():
        return 0
    imported = 0
    today = date.today().isoformat()
    with csv_path.open(newline="", encoding="utf-8-sig") as handle, connect(path) as db:
        for row in csv.DictReader(handle):
            job_id = (row.get("job_id") or "").strip()
            if not job_id:
                continue
            status = (row.get("status") or "unreviewed").strip()
            if status not in VALID_STATUSES:
                status = "unreviewed"
            easy_apply = (row.get("easy_apply") or "true").strip().casefold() in {"true", "1", "yes"}
            db.execute(
                """
                INSERT INTO jobs (
                    job_id, title, company, location, url, easy_apply, description,
                    status, notes, first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    title = excluded.title,
                    company = excluded.company,
                    location = excluded.location,
                    url = excluded.url,
                    easy_apply = excluded.easy_apply,
                    description = CASE WHEN excluded.description != '' THEN excluded.description ELSE jobs.description END,
                    status = CASE WHEN jobs.status = 'unreviewed' THEN excluded.status ELSE jobs.status END,
                    notes = CASE WHEN jobs.notes = '' THEN excluded.notes ELSE jobs.notes END
                """,
                (
                    job_id, row.get("title", ""), row.get("company", ""),
                    row.get("location", ""), row.get("url", ""), int(easy_apply),
                    row.get("description", ""), status, row.get("notes", ""),
                    row.get("first_seen") or today, row.get("last_seen") or today,
                ),
            )
            imported += 1
    return imported


def list_jobs(path: Path, query: str = "", status: str = "all", mode: str = "all") -> list[dict]:
    clauses: list[str] = []
    parameters: list[object] = []
    if query:
        clauses.append("(title LIKE ? OR company LIKE ? OR location LIKE ? OR notes LIKE ?)")
        term = f"%{query}%"
        parameters.extend([term, term, term, term])
    if status != "all":
        clauses.append("status = ?")
        parameters.append(status)
    if mode in {"easy", "external"}:
        clauses.append("easy_apply = ?")
        parameters.append(1 if mode == "easy" else 0)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with connect(path) as db:
        rows = db.execute(
            "SELECT * FROM jobs" + where +
            " ORDER BY CASE status WHEN 'unreviewed' THEN 0 WHEN 'maybe' THEN 1 WHEN 'applied' THEN 2 ELSE 3 END, first_seen DESC, title",
            parameters,
        ).fetchall()
    return [dict(row) for row in rows]


def get_counts(path: Path) -> dict[str, int]:
    with connect(path) as db:
        rows = db.execute("SELECT status, COUNT(*) AS count FROM jobs GROUP BY status").fetchall()
        total = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    counts = {name: 0 for name in VALID_STATUSES}
    counts.update({row["status"]: row["count"] for row in rows})
    counts["all"] = total
    return counts


def update_job(path: Path, job_id: str, status: str, notes: str) -> bool:
    if status not in VALID_STATUSES:
        raise ValueError("Unknown status")
    with connect(path) as db:
        cursor = db.execute(
            "UPDATE jobs SET status = ?, notes = ? WHERE job_id = ?",
            (status, notes[:10_000], job_id),
        )
    return cursor.rowcount == 1
