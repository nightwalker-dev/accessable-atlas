"""Integration tests for AccessAble Atlas HTTP API, persistence, adapters, and idempotency."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import tornado.testing

from atlas.config import load_config
from atlas.server import create_app


class APIIntegrationTests(tornado.testing.AsyncHTTPTestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmp_dir.name)
        self.cfg = load_config(
            {
                "ATLAS_ENV": "test",
                "ATLAS_DB_PATH": str(tmp_path / "test_atlas.db"),
                "ATLAS_PRIVATE_STORAGE_DIR": str(tmp_path / "private_storage"),
                "ATLAS_SEED_SYNTHETIC_DATA": "true",
                "ATLAS_JWT_SECRET": "test_integration_jwt_secret_key_32_bytes_long_0001",
            }
        )
        super().setUp()

    def tearDown(self) -> None:
        super().tearDown()
        self._tmp_dir.cleanup()

    def get_app(self):
        return create_app(self.cfg)

    def _login(self, email: str, password: str = "AtlasDemo!2026") -> dict:
        resp = self.fetch(
            "/api/auth/login",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"email": email, "password": password}),
        )
        self.assertEqual(resp.code, 200)
        return json.loads(resp.body.decode("utf-8"))

    def test_health_and_taxonomies_endpoints(self) -> None:
        resp = self.fetch("/api/health")
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body.decode("utf-8"))
        self.assertEqual(data["product"], "AccessAble Atlas")
        self.assertEqual(data["canonical_database"]["platform"], "supabase")
        self.assertIn("neon", data["canonical_database"]["competing_stores_disabled"])
        self.assertFalse(data["ai_adapter"]["mvp_requires_llm"])

        tax_resp = self.fetch("/api/meta/taxonomies")
        self.assertEqual(tax_resp.code, 200)
        tax_data = json.loads(tax_resp.body.decode("utf-8"))
        self.assertIn("transit_hub", tax_data["venue_categories"])
        self.assertGreaterEqual(len(tax_data["demo_accounts"]), 4)

    def test_venue_filtering_and_idempotent_creation(self) -> None:
        # Filter by step-free and quiet space
        resp = self.fetch("/api/venues?step_free=true&quiet_space=true&min_door_width_cm=95")
        self.assertEqual(resp.code, 200)
        listing = json.loads(resp.body.decode("utf-8"))
        self.assertGreaterEqual(listing["total"], 2)
        for item in listing["items"]:
            self.assertTrue(item["access_attributes"]["step_free_entrance"])
            self.assertTrue(item["access_attributes"]["quiet_sensory_space"])
            self.assertGreaterEqual(item["access_attributes"]["entrance_door_width_cm"], 95)

        # Idempotent venue creation with X-Idempotency-Key
        auth = self._login("maya.chen@atlas-demo.local")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth['token']}",
            "X-CSRF-Token": auth["csrf_token"],
            "X-Idempotency-Key": "idem-venue-create-001",
        }
        venue_payload = {
            "name": "Ballard Maritime Accessibility Center",
            "category": "community_center",
            "address": "5400 Shilshole Ave NW",
            "city": "Seattle",
            "postal_code": "98107",
            "latitude": 47.6685,
            "longitude": -122.3845,
            "summary": "Zero-step waterfront hall with automatic push-button entry and tactile map.",
            "access_attributes": {
                "step_free_entrance": True,
                "entrance_door_width_cm": 102,
                "threshold_height_mm": 0,
                "door_opener_type": "push_button",
                "ramp_present": False,
                "accessible_restroom_type": "single_user_all_gender",
                "grab_bars": "both_sides",
                "turning_circle_cm": 180,
                "elevator_status": "none",
                "braille_tactile_signage": True,
                "hearing_loop_available": True,
                "quiet_sensory_space": True,
                "accessible_parking_spaces": 3,
                "pathway_surface": "smooth_paved",
                "min_corridor_width_cm": 160,
                "lighting_level": "bright_even",
                "acoustic_profile": "quiet",
            },
        }
        r1 = self.fetch("/api/venues", method="POST", headers=headers, body=json.dumps(venue_payload))
        self.assertEqual(r1.code, 201)
        v1 = json.loads(r1.body.decode("utf-8"))["venue"]

        # Retry with identical idempotency key must return the exact same venue without duplicating
        r2 = self.fetch("/api/venues", method="POST", headers=headers, body=json.dumps(venue_payload))
        self.assertEqual(r2.code, 201)
        v2 = json.loads(r2.body.decode("utf-8"))["venue"]
        self.assertEqual(v1["id"], v2["id"])

    def test_saved_views_and_settings_persistence(self) -> None:
        auth = self._login("maya.chen@atlas-demo.local")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth['token']}",
            "X-CSRF-Token": auth["csrf_token"],
        }
        sv_resp = self.fetch(
            "/api/saved-views",
            method="POST",
            headers=headers,
            body=json.dumps(
                {
                    "name": "Transit + Hearing Loop",
                    "filters": {"category": "transit_hub", "hearing_loop": True},
                }
            ),
        )
        self.assertEqual(sv_resp.code, 201)
        sv = json.loads(sv_resp.body.decode("utf-8"))["saved_view"]

        list_resp = self.fetch("/api/saved-views", headers=headers)
        self.assertEqual(list_resp.code, 200)
        ids = [item["id"] for item in json.loads(list_resp.body.decode("utf-8"))["saved_views"]]
        self.assertIn(sv["id"], ids)

        set_resp = self.fetch(
            "/api/settings",
            method="PUT",
            headers=headers,
            body=json.dumps(
                {
                    "barrier_alerts_enabled": True,
                    "stale_venue_digest_enabled": False,
                    "moderation_updates_enabled": True,
                    "ai_consent_granted": False,
                    "telemetry_opt_in": False,
                }
            ),
        )
        self.assertEqual(set_resp.code, 200)
        updated_settings = json.loads(set_resp.body.decode("utf-8"))["settings"]
        self.assertFalse(updated_settings["ai_consent_granted"])
        self.assertFalse(updated_settings["telemetry_opt_in"])

    def test_google_maps_and_earth_geospatial_endpoints(self) -> None:
        # 1. Check health reflects google_maps_earth_adapter
        health_resp = self.fetch("/api/health")
        self.assertEqual(health_resp.code, 200)
        health_data = json.loads(health_resp.body.decode("utf-8"))
        self.assertIn("google_maps_earth_adapter", health_data)
        self.assertTrue(health_data["google_maps_earth_adapter"]["enabled"])

        # 2. Get list of venues and test geospatial endpoint
        venues_resp = self.fetch("/api/venues?limit=1")
        self.assertEqual(venues_resp.code, 200)
        venue_id = json.loads(venues_resp.body.decode("utf-8"))["items"][0]["id"]

        geo_resp = self.fetch(f"/api/venues/{venue_id}/geospatial?travel_mode=wheelchair_manual")
        self.assertEqual(geo_resp.code, 200)
        geo_data = json.loads(geo_resp.body.decode("utf-8"))["geospatial"]
        self.assertIn("google_links", geo_data)
        self.assertIn("curb_to_entrance_grade", geo_data)
        self.assertIn("google_street_view_curb_url", geo_data["google_links"])
        self.assertIn("google_earth_3d_flyover_url", geo_data["google_links"])

        # 3. Test venue Earth KML download
        kml_resp = self.fetch(f"/api/venues/{venue_id}/earth.kml")
        self.assertEqual(kml_resp.code, 200)
        self.assertIn("application/vnd.google-earth.kml+xml", kml_resp.headers.get("Content-Type", ""))
        self.assertIn(b"<kml", kml_resp.body)
        self.assertIn(b"<LookAt>", kml_resp.body)

        # 4. Test workspace Earth KML download
        ws_kml_resp = self.fetch("/api/export/earth.kml")
        self.assertEqual(ws_kml_resp.code, 200)
        self.assertIn("application/vnd.google-earth.kml+xml", ws_kml_resp.headers.get("Content-Type", ""))
        self.assertIn(b"<kml", ws_kml_resp.body)
        self.assertIn(b"Placemark", ws_kml_resp.body)


if __name__ == "__main__":
    unittest.main()

