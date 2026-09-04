import json
import threading
import unittest
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
DATA_DIR = WEB_DIR / "data"
PRIORITY_COUNTRIES = ["US", "PE", "CA", "MX"]
REQUIRED_COUNTRIES = {
    "US", "PE", "CA", "MX", "BR", "AR", "CL", "CO", "EC", "BO", "UY", "PY",
    "CR", "PA", "DO", "PR", "GB", "IE", "ES", "PT", "FR", "DE", "IT", "NL",
    "BE", "CH", "AT", "AU", "NZ",
}


class StaticFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.locations_payload = json.loads((DATA_DIR / "locations.json").read_text(encoding="utf-8"))
        cls.locations = cls.locations_payload["countries"]
        cls.categories = json.loads((DATA_DIR / "categories.json").read_text(encoding="utf-8"))
        cls.app_source = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    def test_location_dataset_loads_with_required_iso_countries(self):
        self.assertEqual(PRIORITY_COUNTRIES, list(self.locations)[:4])
        self.assertTrue(REQUIRED_COUNTRIES.issubset(self.locations))
        for code, country in self.locations.items():
            self.assertTrue((DATA_DIR / country["citiesFile"]).is_file(), code)

    def test_united_states_has_regions_and_texas_cities(self):
        us_regions = self.locations["US"]["regions"]
        self.assertGreaterEqual(len(us_regions), 51)
        self.assertIn("DC", us_regions)
        self.assertEqual(us_regions["TX"]["label"], "Texas")
        us_cities = json.loads((DATA_DIR / "cities/US.json").read_text(encoding="utf-8"))
        for city in ("Austin", "Dallas", "Houston", "San Antonio"):
            self.assertIn(city, us_cities["TX"])

    def test_peru_and_categories_are_available_without_backend(self):
        self.assertIn("PE", self.locations)
        self.assertGreater(len(self.locations["PE"]["regions"]), 0)
        enabled = {item["id"] for item in self.categories if item.get("enabled", True)}
        self.assertTrue({"roofing", "hvac", "plumbing", "law_firms"}.issubset(enabled))

    def test_static_http_server_serves_same_paths_as_vercel(self):
        handler = partial(SimpleHTTPRequestHandler, directory=str(WEB_DIR))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            for path in ("/", "/app.js", "/data/locations.json", "/data/categories.json", "/data/cities/US.json"):
                with urllib.request.urlopen(base + path) as response:
                    self.assertEqual(response.status, 200, path)
        finally:
            server.shutdown()
            server.server_close()

    def test_frontend_uses_static_catalogues_and_separates_backend_error(self):
        self.assertIn("fetchJson('./data/locations.json')", self.app_source)
        self.assertIn("fetchJson('./data/categories.json')", self.app_source)
        self.assertNotIn("fetch('/api/options')", self.app_source)
        self.assertNotIn("localhost", self.app_source.lower())
        self.assertNotIn("127.0.0.1", self.app_source)
        self.assertIn("Location data could not be loaded.", self.app_source)
        self.assertIn("Business categories could not be loaded.", self.app_source)
        self.assertIn("Prospect search backend is currently unavailable.", self.app_source)

    def test_frontend_reset_custom_city_precedence_and_category_actions_are_present(self):
        self.assertIn("addPlaceholder(stateSelect", self.app_source)
        self.assertIn("addPlaceholder(city", self.app_source)
        self.assertIn("return $('custom-city').value.trim() || $('city').value", self.app_source)
        self.assertIn("input.checked = true", self.app_source)
        self.assertIn("input.checked = false", self.app_source)
        self.assertIn("state.running || !formIsValid", self.app_source)


if __name__ == "__main__":
    unittest.main()
