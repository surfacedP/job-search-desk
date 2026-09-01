from __future__ import annotations

import argparse
import json
import mimetypes
import subprocess
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from job_store import get_counts, import_csv, initialise, list_jobs, update_job


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
DB_PATH = BASE_DIR / "jobs.db"


class SearchController:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state: dict[str, object] = {
            "running": False,
            "mode": None,
            "message": "Ready to search",
            "output": [],
            "return_code": None,
        }

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return dict(self.state)

    def start(self, mode: str) -> bool:
        if mode not in {"easy", "external", "both"}:
            raise ValueError("Unknown search mode")
        with self.lock:
            if self.state["running"]:
                return False
            self.state = {
                "running": True,
                "mode": mode,
                "message": "Opening LinkedIn…",
                "output": [],
                "return_code": None,
            }
        threading.Thread(target=self._run, args=(mode,), daemon=True).start()
        return True

    def _run(self, mode: str) -> None:
        command = [
            sys.executable, "-u", str(BASE_DIR / "scrape.py"),
            "--config", str(BASE_DIR / "config.yml"),
            "--mode", mode, "--dashboard",
        ]
        lines: list[str] = []
        try:
            process = subprocess.Popen(
                command,
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                lines.append(line)
                lines = lines[-40:]
                with self.lock:
                    self.state["message"] = line
                    self.state["output"] = list(lines)
            return_code = process.wait()
            with self.lock:
                self.state["running"] = False
                self.state["return_code"] = return_code
                self.state["message"] = "Search complete" if return_code == 0 else "Search stopped with an error"
                self.state["output"] = list(lines)
        except Exception as exc:
            with self.lock:
                self.state["running"] = False
                self.state["return_code"] = -1
                self.state["message"] = f"Could not start search: {exc}"
                self.state["output"] = list(lines)


SEARCH = SearchController()


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "JobDashboard/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def serve_file(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            resolved.relative_to(WEB_DIR.resolve())
            payload = resolved.read_bytes()
        except (OSError, ValueError):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/jobs":
            query = parse_qs(parsed.query)
            jobs = list_jobs(
                DB_PATH,
                query.get("q", [""])[0].strip(),
                query.get("status", ["all"])[0],
                query.get("mode", ["all"])[0],
            )
            self.send_json({"jobs": jobs, "counts": get_counts(DB_PATH)})
            return
        if parsed.path == "/api/health":
            self.send_json({"ok": True})
            return
        if parsed.path == "/api/search":
            self.send_json(SEARCH.snapshot())
            return
        if parsed.path == "/":
            self.serve_file(WEB_DIR / "index.html")
            return
        if parsed.path.startswith("/static/"):
            self.serve_file(WEB_DIR / parsed.path.lstrip("/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/search":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size))
            started = SEARCH.start(str(body.get("mode", "")))
            if not started:
                self.send_json({"error": "A search is already running"}, HTTPStatus.CONFLICT)
                return
            self.send_json(SEARCH.snapshot(), HTTPStatus.ACCEPTED)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/jobs/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size))
            job_id = parsed.path.rsplit("/", 1)[-1]
            updated = update_job(DB_PATH, job_id, str(body.get("status", "unreviewed")), str(body.get("notes", "")))
            self.send_json({"ok": updated}, HTTPStatus.OK if updated else HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def prepare_database() -> None:
    initialise(DB_PATH)
    # Both imports are idempotent. The master CSV is imported last so its notes
    # and status take precedence when the database is first created.
    import_csv(DB_PATH, BASE_DIR / "job_history.csv")
    import_csv(DB_PATH, BASE_DIR / "jobs.csv")


def main() -> int:
    parser = argparse.ArgumentParser(description="Open the local job-search dashboard.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    prepare_database()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Job dashboard is running at {url}")
    print("Press Ctrl+C to stop it.")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
