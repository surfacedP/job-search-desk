# Job Search Desk

A private, local dashboard for finding and reviewing LinkedIn jobs. It supports Easy Apply searches, external-application searches, persistent notes and application statuses, and duplicate-safe storage in SQLite.

The project currently focuses on making UK IT-support job hunting faster and easier to review. Search criteria remain fully configurable.

It does **not** submit applications, bypass authentication or CAPTCHAs, or attempt to evade access controls. LinkedIn can change its interface and terms; use the tool conservatively and stop if LinkedIn asks you to slow down or verify your identity.

## Requirements

- Windows 10 or 11
- Python 3.10 or newer
- A LinkedIn account

## Install

Open PowerShell in the project folder and run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
Copy-Item config.example.yml config.yml
```

Edit `config.yml` with your searches and filters before searching.

## Start the dashboard

Double-click `Start Job Dashboard.bat`, or run:

```powershell
.\.venv\Scripts\python.exe app.py
```

The dashboard opens at `http://127.0.0.1:8765` and is available only on the local computer.

Use **Find new jobs** to choose:

- Easy Apply only
- External applications only
- Both

A Chromium window opens while LinkedIn is searched. Log in manually if prompted and leave that window open until the search completes. The dashboard refreshes its results automatically.

## Review jobs

The dashboard lets you:

- Search by title, company, location, or notes
- Filter by application type and review status
- Mark jobs as unreviewed, applied, maybe, not applying, or hidden
- Keep persistent notes
- Open the original LinkedIn listing

Jobs are identified by LinkedIn job ID. Existing notes and statuses are preserved when the same job is found again.

## Command-line search

The scraper can also run directly:

```powershell
.\.venv\Scripts\python.exe scrape.py --config config.yml --mode easy
```

Valid modes are `easy`, `external`, and `both`. If `--mode` is omitted, the script asks which type to search.

## Local and private files

The following remain only on your computer and are excluded from Git:

- `.browser-profile/` — LinkedIn browser session
- `config.yml` — personal search configuration
- `jobs.db` — job decisions and notes
- `jobs.csv` and `job_history.csv` — secondary records
- `.venv/` — local Python environment

Do not share the browser profile or personal data files.

## Run tests

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

## Current scope

This is an early local MVP. LinkedIn page markup may change and require selector maintenance. Review every result yourself before applying.

