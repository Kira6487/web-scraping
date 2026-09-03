#!/usr/bin/env python3
"""Small web layer for the existing FORM4TH prospect engine.

The API key is read only by the backend process. The browser receives job
status and a safe run id, never the key or an arbitrary filesystem path.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import extract_leads as engine


ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
OUTPUT_DIR = ROOT / "output"
LOCATIONS = json.loads((ROOT / "config" / "locations.json").read_text(encoding="utf-8"))
CATEGORIES = json.loads((ROOT / "config" / "business_categories.json").read_text(encoding="utf-8"))
CATEGORY_BY_ID = {item["id"]: item for item in CATEGORIES if item.get("enabled", True)}
RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
SEARCH_LOCK = threading.Lock()


def json_response(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def load_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length > 64 * 1024:
        raise ValueError("Request is too large.")
    raw = handler.rfile.read(length)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Request body must be an object.")
    return payload


def validate_search(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    country = str(payload.get("country", "")).upper()
    state = str(payload.get("state", ""))
    city = str(payload.get("city", "")).strip()
    categories = payload.get("categories", [])
    try:
        max_results = int(payload.get("max_results", 50))
    except (ValueError, TypeError):
        return None, "Maximum Results must be a number."
    if country not in LOCATIONS:
        return None, "Please select a supported country."
    if not isinstance(categories, list) or not categories:
        return None, "Select at least one business category."
    if any(category not in CATEGORY_BY_ID for category in categories):
        return None, "One or more business categories are invalid."
    if not 1 <= max_results <= 500:
        return None, "Maximum Results must be between 1 and 500."
    regions = LOCATIONS[country]["regions"]
    if state not in regions:
        return None, "Please select a valid state or region."
    custom_city = str(payload.get("custom_city", "")).strip()
    if custom_city:
        city = custom_city
    elif city not in regions[state]["cities"]:
        return None, "Please select a valid city or provide Custom city."
    return {
        "country": country,
        "state": regions[state]["label"],
        "city": city,
        "categories": categories,
        "max_results": max_results,
    }, None


def update_job(run_id: str, **updates: Any) -> None:
    with JOBS_LOCK:
        if run_id in JOBS:
            JOBS[run_id].update(updates)


def run_job(run_id: str, request: dict[str, Any]) -> None:
    try:
        api_key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("Google API key is not configured.")
        categories = [CATEGORY_BY_ID[item]["label"] for item in request["categories"]]
        plan = engine.build_selected_query_plan(categories, request["city"], request["state"], request["country"])
        config = engine.Config(
            max_results=request["max_results"],
            page_size=min(20, request["max_results"]),
            output_dir=OUTPUT_DIR,
        )

        def progress(stage: str, current: int, total: int) -> None:
            update_job(run_id, stage=stage, analyzed=current, total=total)

        prospects, issues, summary = engine.execute_search(plan, api_key, config, progress=progress)
        update_job(run_id, stage="Generating Excel report...", analyzed=len(prospects), total=len(prospects))
        start = engine.datetime.now().astimezone()
        output_path = engine.unique_output_path(OUTPUT_DIR, start)
        run_summary = {
            "run_id": run_id,
            "start_timestamp": JOBS[run_id]["started_at"],
            "finish_timestamp": engine.now_iso(),
            "search_queries": " | ".join(query for values in plan.values() for query in values),
            "categories": "; ".join(categories),
            **summary,
            "generated_file_path": str(output_path),
        }
        engine.export_workbook(prospects, issues, run_summary, output_path)
        update_job(run_id, status="completed", stage="Completed.", summary=summary, file_path=str(output_path), analyzed=len(prospects), total=len(prospects))
    except Exception as exc:
        # Technical details stay in the server log; clients receive a safe message.
        print(f"[WEB] job {run_id} failed: {type(exc).__name__}: {exc}")
        message = "Google API key is not configured." if "API key" in str(exc) else "The search could not be completed. Check the server log."
        update_job(run_id, status="error", stage="Search failed.", error=message)
    finally:
        SEARCH_LOCK.release()


class AppHandler(BaseHTTPRequestHandler):
    server_version = "FORM4THProspectUI/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[WEB] {self.address_string()} - {format % args}")

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            return self.serve_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
        if self.path == "/app.js":
            return self.serve_file(WEB_DIR / "app.js", "text/javascript; charset=utf-8")
        if self.path == "/styles.css":
            return self.serve_file(WEB_DIR / "styles.css", "text/css; charset=utf-8")
        if self.path == "/api/options":
            return json_response(self, {"countries": LOCATIONS, "categories": CATEGORIES})
        if self.path == "/api/health":
            return json_response(self, {"ok": True})
        if self.path.startswith("/api/search/"):
            run_id = self.path.rsplit("/", 1)[-1]
            if not RUN_ID_RE.fullmatch(run_id):
                return json_response(self, {"error": "Invalid run id."}, HTTPStatus.BAD_REQUEST)
            with JOBS_LOCK:
                job = JOBS.get(run_id)
            if not job:
                return json_response(self, {"error": "Search not found."}, HTTPStatus.NOT_FOUND)
            return json_response(self, {key: value for key, value in job.items() if key != "file_path"})
        if self.path.startswith("/api/results/") and self.path.endswith("/download"):
            return self.download_result(self.path.split("/")[3])
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/search":
            return json_response(self, {"error": "Not found."}, HTTPStatus.NOT_FOUND)
        if not SEARCH_LOCK.acquire(blocking=False):
            return json_response(self, {"error": "A search is already running."}, HTTPStatus.CONFLICT)
        try:
            payload = load_json_body(self)
            request, error = validate_search(payload)
            if error:
                SEARCH_LOCK.release()
                return json_response(self, {"error": error}, HTTPStatus.BAD_REQUEST)
            run_id = uuid.uuid4().hex
            with JOBS_LOCK:
                JOBS[run_id] = {
                    "run_id": run_id, "status": "running", "stage": "Preparing search...",
                    "analyzed": 0, "total": 0, "started_at": engine.now_iso(),
                }
            threading.Thread(target=run_job, args=(run_id, request), daemon=True).start()
            return json_response(self, {
                "success": True, "run_id": run_id,
                "status_url": f"/api/search/{run_id}",
                "download_url": f"/api/results/{run_id}/download",
            }, HTTPStatus.ACCEPTED)
        except (ValueError, json.JSONDecodeError) as exc:
            SEARCH_LOCK.release()
            return json_response(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            SEARCH_LOCK.release()
            return json_response(self, {"error": "Invalid search request."}, HTTPStatus.BAD_REQUEST)

    def serve_file(self, path: Path, content_type: str) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            return self.send_error(HTTPStatus.NOT_FOUND)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def download_result(self, run_id: str) -> None:
        if not RUN_ID_RE.fullmatch(run_id):
            return json_response(self, {"error": "Invalid run id."}, HTTPStatus.BAD_REQUEST)
        with JOBS_LOCK:
            job = JOBS.get(run_id, {}).copy()
        raw_path = job.get("file_path", "")
        if job.get("status") != "completed" or not raw_path:
            return json_response(self, {"error": "The report is not ready."}, HTTPStatus.NOT_FOUND)
        path = Path(raw_path).resolve()
        output_root = OUTPUT_DIR.resolve()
        if output_root not in path.parents or path.suffix.lower() != ".xlsx":
            return json_response(self, {"error": "Invalid report path."}, HTTPStatus.FORBIDDEN)
        try:
            body = path.read_bytes()
        except OSError:
            return json_response(self, {"error": "Report not found."}, HTTPStatus.NOT_FOUND)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="FORM4TH Prospect Engine web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"[WEB] FORM4TH Prospect Engine at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[WEB] Server stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
