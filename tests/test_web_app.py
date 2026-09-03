import json
import threading
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import web_app


class WebAppTests(unittest.TestCase):
    def test_location_category_and_max_validation(self):
        valid, error = web_app.validate_search({
            "country": "US", "state": "TX", "city": "Austin",
            "categories": ["roofing", "hvac"], "max_results": 10,
        })
        self.assertIsNone(error)
        self.assertEqual(valid["state"], "Texas")
        self.assertEqual(len(valid["categories"]), 2)
        invalid, error = web_app.validate_search({
            "country": "US", "state": "TX", "city": "Austin",
            "categories": [], "max_results": 501,
        })
        self.assertIsNone(invalid)
        self.assertIn("category", error.lower())

    def test_multiple_categories_create_one_shared_plan_and_global_limit_config(self):
        plan = web_app.engine.build_selected_query_plan(
            ["Roofing", "HVAC"], "Austin", "Texas", "US"
        )
        self.assertEqual(set(plan), {"Roofing", "HVAC"})
        config = web_app.engine.Config(max_results=10)
        self.assertEqual(config.max_results, 10)

    def test_download_endpoint_rejects_unsafe_run_id(self):
        server = web_app.ThreadingHTTPServer(("127.0.0.1", 0), web_app.AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_address[1]}/api/results/not-safe/download"
        try:
            with self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(url)
            self.assertEqual(context.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()

    def test_options_endpoint_uses_central_config(self):
        server = web_app.ThreadingHTTPServer(("127.0.0.1", 0), web_app.AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_address[1]}/api/options"
        try:
            payload = json.loads(urllib.request.urlopen(url).read())
            self.assertIn("US", payload["countries"])
            self.assertIn("PE", payload["countries"])
            self.assertTrue(any(item["id"] == "roofing" for item in payload["categories"]))
        finally:
            server.shutdown()
            server.server_close()

    def test_search_to_analysis_to_xlsx_download_with_mocked_engine(self):
        prospect = web_app.engine.Prospect(
            company_name="Mock Roofing", ai_fit_score=87, opportunity_tier="A+",
            recommended_action="BUILD_DEMO", target_category="Roofing",
        )
        summary = {
            "total_discovered": 1, "total_after_deduplication": 1,
            "total_validated": 1, "total_invalid": 0, "total_errors": 0,
            "A+": 1, "A": 0, "B": 0, "C": 0, "D": 0,
            "demo_candidates": 1, "outreach_candidates": 1,
        }

        def fake_execute(plan, api_key, config, progress=None, discovery=None):
            if progress:
                progress("Analyzing opportunities...", 1, 1)
            return [prospect], [], summary

        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"GOOGLE_PLACES_API_KEY": "test-key"}), patch.object(web_app, "OUTPUT_DIR", Path(directory)), patch.object(web_app.engine, "execute_search", fake_execute):
            server = web_app.ThreadingHTTPServer(("127.0.0.1", 0), web_app.AppHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            payload = json.dumps({
                "country": "US", "state": "TX", "city": "Austin",
                "categories": ["roofing", "hvac"], "max_results": 10,
            }).encode()
            try:
                request = urllib.request.Request(base + "/api/search", data=payload, headers={"Content-Type": "application/json"}, method="POST")
                response = urllib.request.urlopen(request)
                started = json.loads(response.read())
                self.assertTrue(started["success"])
                for _ in range(30):
                    status = json.loads(urllib.request.urlopen(base + started["status_url"]).read())
                    if status["status"] in {"completed", "error"}:
                        break
                    time.sleep(0.05)
                self.assertEqual(status["status"], "completed")
                self.assertEqual(status["summary"]["demo_candidates"], 1)
                download = urllib.request.urlopen(base + started["download_url"])
                self.assertEqual(download.headers["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.assertTrue(download.read(2) == b"PK")
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
