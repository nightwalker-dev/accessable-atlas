"""End-to-End tests covering Journey A (First Use), Journey B (Core Task), and Journey C (Insights & Moderation)."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
import tornado.testing

from atlas.config import load_config
from atlas.server import create_app


class EndToEndJourneysTests(tornado.testing.AsyncHTTPTestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmp_dir.name)
        self.cfg = load_config(
            {
                "ATLAS_ENV": "test",
                "ATLAS_DB_PATH": str(tmp_path / "e2e_atlas.db"),
                "ATLAS_PRIVATE_STORAGE_DIR": str(tmp_path / "private_storage"),
                "ATLAS_SEED_SYNTHETIC_DATA": "true",
                "ATLAS_JWT_SECRET": "test_e2e_jwt_secret_key_at_least_32_bytes_9999",
            }
        )
        super().setUp()

    def tearDown(self) -> None:
        super().tearDown()
        self._tmp_dir.cleanup()

    def get_app(self):
        return create_app(self.cfg)

    def _make_sample_png_b64(self) -> str:
        img = Image.new("RGB", (240, 160), color=(3, 4, 7))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def test_complete_journeys_a_b_and_c(self) -> None:
        # ====================================================================
        # JOURNEY A — First Use, Accessible HTML Shell & Synthetic Provenance
        # ====================================================================
        index_resp = self.fetch("/")
        self.assertEqual(index_resp.code, 200)
        html_body = index_resp.body.decode("utf-8")
        self.assertIn("Skip to main content", html_body)
        self.assertIn("Find places through the details that matter", html_body)

        # Register a brand-new user
        reg_resp = self.fetch(
            "/api/auth/register",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps(
                {
                    "display_name": "Tariq Al-Mansoor (Access Advocate)",
                    "email": "tariq@community-access.org",
                    "password": "StrongPassword!2026",
                    "role": "contributor",
                    "ai_consent_granted": True,
                    "telemetry_opt_in": True,
                }
            ),
        )
        self.assertEqual(reg_resp.code, 201)
        reg_data = json.loads(reg_resp.body.decode("utf-8"))
        user_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {reg_data['token']}",
            "X-CSRF-Token": reg_data["csrf_token"],
        }

        # Verify seeded records are explicitly marked as synthetic samples
        venues_resp = self.fetch("/api/venues")
        venues_list = json.loads(venues_resp.body.decode("utf-8"))["items"]
        self.assertTrue(all(v["is_synthetic_sample"] for v in venues_list))
        self.assertTrue(all("Synthetic Sample" in v["provenance_badge"] for v in venues_list))

        # ====================================================================
        # JOURNEY B — Core Task: Create Venue, Log Observation, Upload Photo,
        #             Synthesize Briefing, Export, Archive & Delete
        # ====================================================================
        create_resp = self.fetch(
            "/api/venues",
            method="POST",
            headers=user_headers,
            body=json.dumps(
                {
                    "name": "Capitol Hill Light Rail Station (East Entry)",
                    "category": "transit_hub",
                    "address": "140 Broadway East",
                    "city": "Seattle",
                    "postal_code": "98102",
                    "latitude": 47.6192,
                    "longitude": -122.3204,
                    "operating_hours": "05:00 - 01:00 Daily",
                    "summary": "Step-free street plaza with dual wide-cab elevators, tactile platform edge tiles, and induction hearing loop.",
                    "access_attributes": {
                        "step_free_entrance": True,
                        "entrance_door_width_cm": 120,
                        "threshold_height_mm": 0,
                        "door_opener_type": "open_archway",
                        "ramp_present": False,
                        "accessible_restroom_type": "none",
                        "grab_bars": "none",
                        "turning_circle_cm": 200,
                        "elevator_status": "operational",
                        "braille_tactile_signage": True,
                        "hearing_loop_available": True,
                        "quiet_sensory_space": False,
                        "accessible_parking_spaces": 2,
                        "pathway_surface": "tactile_paving",
                        "min_corridor_width_cm": 240,
                        "lighting_level": "bright_even",
                        "acoustic_profile": "moderate",
                    },
                }
            ),
        )
        self.assertEqual(create_resp.code, 201)
        created_venue = json.loads(create_resp.body.decode("utf-8"))["venue"]
        venue_id = created_venue["id"]
        self.assertFalse(created_venue["is_synthetic_sample"])
        self.assertEqual(created_venue["freshness"]["state"], "fresh_verified")

        # Submit a timestamped observation noting a temporary elevator outage
        obs_resp = self.fetch(
            f"/api/venues/{venue_id}/observations",
            method="POST",
            headers=user_headers,
            body=json.dumps(
                {
                    "observer_role": "person_with_access_need",
                    "confidence_level": "direct_observation",
                    "summary": "North elevator temporarily paused for door sensor inspection; South elevator remains operational.",
                    "measured_door_width_cm": 120,
                    "elevator_operational_check": "out_of_service",
                    "barriers_noted": "North elevator paused for sensor check",
                    "is_operational_alert": True,
                }
            ),
        )
        self.assertEqual(obs_resp.code, 201)
        obs_data = json.loads(obs_resp.body.decode("utf-8"))
        self.assertEqual(obs_data["venue"]["freshness"]["state"], "active_alert")

        # Upload consent-reviewed photo evidence
        photo_resp = self.fetch(
            f"/api/venues/{venue_id}/photos",
            method="POST",
            headers=user_headers,
            body=json.dumps(
                {
                    "category": "ramp_lift",
                    "alt_text": "Wide elevator cab door at Capitol Hill East Entry with tactile braille call buttons at 105 cm height.",
                    "caption": "East Entry elevator call panel",
                    "no_identifiable_faces_confirmed": True,
                    "operator_or_public_area_consent": True,
                    "file_base64": self._make_sample_png_b64(),
                }
            ),
        )
        self.assertEqual(photo_resp.code, 201)
        photo_record = json.loads(photo_resp.body.decode("utf-8"))["photo"]
        self.assertEqual(photo_record["consent_status"], "pending_review")
        self.assertTrue(photo_record["exif_stripped"])

        # Request consent-checked accessibility route briefing
        brief_resp = self.fetch(
            f"/api/venues/{venue_id}/briefing",
            method="POST",
            headers=user_headers,
            body=json.dumps({"explicit_consent": True}),
        )
        self.assertEqual(brief_resp.code, 200)
        briefing = json.loads(brief_resp.body.decode("utf-8"))["briefing"]
        self.assertTrue(briefing["available"])
        self.assertGreaterEqual(len(briefing["briefing_points"]), 3)

        # ====================================================================
        # JOURNEY C — Insights, Moderation Flagging & Moderator Resolution
        # ====================================================================
        insights_resp = self.fetch("/api/insights", headers=user_headers)
        self.assertEqual(insights_resp.code, 200)
        insights = json.loads(insights_resp.body.decode("utf-8"))
        self.assertIn("time_range", insights["metadata"])
        self.assertIn("assumptions", insights["metadata"])
        self.assertIn("limitations", insights["metadata"])
        self.assertGreaterEqual(insights["metrics"]["user_documented_venues"], 1)

        # Submit a moderation report
        flag_resp = self.fetch(
            "/api/moderation/reports",
            method="POST",
            headers=user_headers,
            body=json.dumps(
                {
                    "venue_id": venue_id,
                    "target_type": "venue",
                    "target_id": venue_id,
                    "reason": "outdated_barrier",
                    "details": "Transit technician restored the North elevator; barrier alert can be cleared after verification.",
                }
            ),
        )
        self.assertEqual(flag_resp.code, 201)
        report_id = json.loads(flag_resp.body.decode("utf-8"))["report"]["id"]

        # Switch to Moderator (Samira Khan) to approve photo consent and resolve moderation report
        mod_login = self.fetch(
            "/api/auth/login",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps(
                {"email": "samira.khan@atlas-demo.local", "password": "AtlasDemo!2026"}
            ),
        )
        mod_auth = json.loads(mod_login.body.decode("utf-8"))
        mod_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {mod_auth['token']}",
            "X-CSRF-Token": mod_auth["csrf_token"],
        }

        review_photo_resp = self.fetch(
            f"/api/photos/{photo_record['id']}/review",
            method="POST",
            headers=mod_headers,
            body=json.dumps(
                {
                    "consent_status": "approved_public",
                    "review_notes": "Confirmed no faces or private data; descriptive alt text verified.",
                    "confirm": True,
                }
            ),
        )
        self.assertEqual(review_photo_resp.code, 200)

        resolve_resp = self.fetch(
            f"/api/moderation/reports/{report_id}/resolve",
            method="POST",
            headers=mod_headers,
            body=json.dumps(
                {
                    "status": "resolved_upheld",
                    "resolution_notes": "Confirmed with Sound Transit control room that elevator is back in service.",
                    "confirm": True,
                }
            ),
        )
        self.assertEqual(resolve_resp.code, 200)

        # Export workspace data bundle with confirmation
        export_resp = self.fetch(
            "/api/export",
            method="POST",
            headers=user_headers,
            body=json.dumps({"confirm": True}),
        )
        self.assertEqual(export_resp.code, 200)
        bundle = json.loads(export_resp.body.decode("utf-8"))
        self.assertEqual(bundle["export_version"], "1.0")
        self.assertGreaterEqual(len(bundle["venues"]), 7)

        # Archive and then delete the user's created venue with explicit confirmation
        arch_resp = self.fetch(
            f"/api/venues/{venue_id}/archive",
            method="POST",
            headers=user_headers,
            body=json.dumps({"confirm": True}),
        )
        self.assertEqual(arch_resp.code, 200)
        self.assertEqual(json.loads(arch_resp.body.decode("utf-8"))["venue"]["status"], "archived")

        del_resp = self.fetch(
            f"/api/venues/{venue_id}?confirm=true",
            method="DELETE",
            headers=user_headers,
        )
        self.assertEqual(del_resp.code, 200)
        self.assertTrue(json.loads(del_resp.body.decode("utf-8"))["deleted"])

    def test_venue_import_confirmation_and_account_deletion_lifecycle(self) -> None:
        # Verify accessible HTML controls for offline banner, city filter, map zoom, import, and account deletion
        index_resp = self.fetch("/")
        self.assertEqual(index_resp.code, 200)
        html_body = index_resp.body.decode("utf-8")
        for control_id in (
            'id="offline-banner"',
            'id="filter-city"',
            'id="filter-archived"',
            'id="btn-map-zoom-in"',
            'id="venue-import-details"',
            'id="account-delete-form"',
        ):
            self.assertIn(control_id, html_body)

        # Register a dedicated contributor account
        reg_resp = self.fetch(
            "/api/auth/register",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps(
                {
                    "display_name": "Elena Rostova (Civic Auditor)",
                    "email": "elena.rostova@civic-audit.org",
                    "password": "StrongPassword!2026",
                    "role": "contributor",
                    "ai_consent_granted": True,
                    "telemetry_opt_in": True,
                }
            ),
        )
        self.assertEqual(reg_resp.code, 201)
        reg_data = json.loads(reg_resp.body.decode("utf-8"))
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {reg_data['token']}",
            "X-CSRF-Token": reg_data["csrf_token"],
        }

        import_venue_data = {
            "name": "Belltown Civic Makerspace & Ramp Annex",
            "category": "community_center",
            "address": "2314 1st Ave",
            "city": "Seattle",
            "postal_code": "98121",
            "operating_hours": "Mon-Sat 09:00-20:00",
            "latitude": 47.6144,
            "longitude": -122.3456,
            "summary": "Imported municipal audit record with 96 cm sliding doors and 175 cm restroom turning circle.",
            "access_attributes": {
                "step_free_entrance": True,
                "entrance_door_width_cm": 96,
                "threshold_height_mm": 0,
                "door_opener_type": "motion_sensor",
                "ramp_present": False,
                "accessible_restroom_type": "single_user_all_gender",
                "grab_bars": "both_sides",
                "turning_circle_cm": 175,
                "elevator_status": "none",
                "braille_tactile_signage": True,
                "hearing_loop_available": True,
                "quiet_sensory_space": True,
                "accessible_parking_spaces": 2,
                "pathway_surface": "smooth_paved",
                "min_corridor_width_cm": 165,
                "lighting_level": "bright_even",
                "acoustic_profile": "moderate",
            },
        }

        # 1. Unconfirmed import must be rejected (Journey B.3: user must confirm imported values)
        unconfirmed_import = self.fetch(
            "/api/venues/import",
            method="POST",
            headers=headers,
            body=json.dumps(
                {
                    "venue_data": import_venue_data,
                    "import_source": "json_upload",
                    "user_confirmed_imported_values": False,
                }
            ),
        )
        self.assertEqual(unconfirmed_import.code, 400)

        # 2. Confirmed import succeeds and records provenance_history action 'venue.imported_and_confirmed'
        confirmed_import = self.fetch(
            "/api/venues/import",
            method="POST",
            headers=headers,
            body=json.dumps(
                {
                    "venue_data": import_venue_data,
                    "import_source": "json_upload",
                    "user_confirmed_imported_values": True,
                }
            ),
        )
        self.assertEqual(confirmed_import.code, 201)
        imported_venue = json.loads(confirmed_import.body.decode("utf-8"))["venue"]
        self.assertEqual(imported_venue["name"], "Belltown Civic Makerspace & Ramp Annex")
        actions = [h["action"] for h in imported_venue["provenance_history"]]
        self.assertIn("venue.imported_and_confirmed", actions)

        # 3. Verify city filter and available_cities metadata on /api/venues
        city_resp = self.fetch("/api/venues?city=Seattle")
        self.assertEqual(city_resp.code, 200)
        city_data = json.loads(city_resp.body.decode("utf-8"))
        self.assertIn("Seattle", city_data["available_cities"])
        self.assertTrue(all(v["city"] == "Seattle" for v in city_data["items"]))

        # 4. Self-service Account & Personal Data Deletion/Anonymization requires confirmation phrase
        bad_del = self.fetch(
            "/api/account/delete",
            method="POST",
            headers=headers,
            body=json.dumps({"confirm": True, "confirmation_phrase": "wrong phrase"}),
        )
        self.assertEqual(bad_del.code, 400)

        good_del = self.fetch(
            "/api/account/delete",
            method="POST",
            headers=headers,
            body=json.dumps({"confirm": True, "confirmation_phrase": "DELETE MY ACCOUNT"}),
        )
        self.assertEqual(good_del.code, 200)
        del_payload = json.loads(good_del.body.decode("utf-8"))
        self.assertTrue(del_payload["deleted"])

        # 5. Subsequent authenticated call with the deleted account's JWT must be rejected
        post_del_settings = self.fetch("/api/settings", headers=headers)
        self.assertEqual(post_del_settings.code, 401)

        # 6. Public venue remains intact with creator anonymized to 'Anonymized Community Member'
        venue_check = self.fetch(f"/api/venues/{imported_venue['id']}")
        self.assertEqual(venue_check.code, 200)
        v_after = json.loads(venue_check.body.decode("utf-8"))["venue"]
        self.assertEqual(v_after["creator_name"], "Anonymized Community Member")


if __name__ == "__main__":
    unittest.main()
