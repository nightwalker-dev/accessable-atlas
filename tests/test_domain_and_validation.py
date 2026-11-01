"""Unit tests for domain freshness engine, accessibility fit, validation, and EXIF scrubbing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from atlas.adapters.tinybird_adapter import TinybirdAdapter
from atlas.auth import RevokedTokenStore
from atlas.background_jobs import BackgroundJobRunner
from atlas.config import load_config, mask_secret, redact_sensitive_dict
from atlas.db.database import AtlasDatabase
from atlas.db.seed import seed_if_empty
from atlas.domain import compute_freshness_indicator, evaluate_accessibility_fit
from atlas.feature_flags import FeatureFlagRegistry
from atlas.logging_utils import StructuredLogger, redact_pii_and_secrets
from atlas.modules import CANONICAL_MODULE_SLUGS, DomainModulesContainer, load_domain_module
from atlas.rate_limit import IdempotencyStore
from atlas.schemas import BOUNDARY_SCHEMA_REGISTRY, MapAndListSearchFilterSchema
from atlas.validation import (
    ValidationError,
    validate_and_scrub_photo_upload,
    validate_observation_payload,
    validate_venue_payload,
)


class DomainAndValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_freshness_indicator_states_and_non_color_tokens(self) -> None:
        fresh_iso = (self.now - timedelta(days=5)).isoformat()
        fresh = compute_freshness_indicator(
            last_observed_at=fresh_iso,
            active_barrier_alert=None,
            observation_count=2,
            avg_confidence=90,
            elevator_status="operational",
            reference_now=self.now,
        )
        self.assertEqual(fresh["state"], "fresh_verified")
        self.assertEqual(fresh["color_hex"], "#D4FF24")
        self.assertEqual(fresh["icon_token"], "check-shield")
        self.assertIn("Fresh", fresh["label"])

        aging_iso = (self.now - timedelta(days=45)).isoformat()
        aging = compute_freshness_indicator(
            last_observed_at=aging_iso,
            active_barrier_alert=None,
            observation_count=1,
            avg_confidence=85,
            elevator_status="operational",
            reference_now=self.now,
        )
        self.assertEqual(aging["state"], "aging_review_soon")
        self.assertEqual(aging["color_hex"], "#E8D2B5")

        stale_iso = (self.now - timedelta(days=120)).isoformat()
        stale = compute_freshness_indicator(
            last_observed_at=stale_iso,
            active_barrier_alert=None,
            observation_count=1,
            avg_confidence=80,
            elevator_status="none",
            reference_now=self.now,
        )
        self.assertEqual(stale["state"], "stale_reverify")
        self.assertGreater(stale["days_since_last_observation"], 90)

        alert = compute_freshness_indicator(
            last_observed_at=fresh_iso,
            active_barrier_alert="North ramp blocked by scaffolding",
            observation_count=3,
            avg_confidence=95,
            elevator_status="operational",
            reference_now=self.now,
        )
        self.assertEqual(alert["state"], "active_alert")
        self.assertEqual(alert["icon_token"], "alert-triangle")

    def test_accessibility_fit_evaluation(self) -> None:
        attrs = {
            "step_free_entrance": True,
            "entrance_door_width_cm": 94,
            "threshold_height_mm": 0,
            "door_opener_type": "push_button",
            "accessible_restroom_type": "single_user_all_gender",
            "turning_circle_cm": 175,
            "elevator_status": "operational",
            "braille_tactile_signage": True,
            "hearing_loop_available": True,
            "quiet_sensory_space": False,
        }
        fit = evaluate_accessibility_fit(
            attrs,
            filters={"step_free": True, "min_door_width_cm": 85, "accessible_restroom": True},
        )
        self.assertTrue(fit["matches_filters"])
        self.assertTrue(fit["wheelchair_standard_met"])

        no_match = evaluate_accessibility_fit(attrs, filters={"quiet_space": True})
        self.assertFalse(no_match["matches_filters"])

    def test_venue_and_observation_validation_actionable_errors(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            validate_venue_payload(
                {
                    "name": "A",
                    "category": "invalid_cat",
                    "address": "12",
                    "city": "X",
                    "postal_code": "1",
                    "latitude": 120.0,
                    "longitude": -200.0,
                    "summary": "Too short",
                    "access_attributes": {"entrance_door_width_cm": 10},
                }
            )
        errs = ctx.exception.field_errors
        self.assertIn("name", errs)
        self.assertIn("category", errs)
        self.assertIn("latitude", errs)
        self.assertIn("longitude", errs)
        self.assertIn("access_attributes.entrance_door_width_cm", errs)

        obs = validate_observation_payload(
            {
                "observer_role": "person_with_access_need",
                "confidence_level": "verified_measurement",
                "summary": "Verified 95 cm clear doorway width with laser tape measure.",
                "measured_door_width_cm": 95,
                "elevator_operational_check": "out_of_service",
            }
        )
        self.assertEqual(obs["confidence_score"], 95)
        self.assertTrue(obs["is_operational_alert"])

    def test_photo_validation_exif_stripping_and_consent_enforcement(self) -> None:
        img = Image.new("RGB", (120, 90), color=(21, 88, 201))
        buf = io.BytesIO()
        exif = img.getexif()
        exif[0x010E] = "Sensitive Camera Description GPS Metadata"
        img.save(buf, format="PNG", exif=exif)
        raw_png = buf.getvalue()

        # Missing consent must fail
        with self.assertRaises(ValidationError) as ctx:
            validate_and_scrub_photo_upload(
                metadata={
                    "category": "entrance",
                    "alt_text": "Step-free entrance with automatic push button.",
                    "no_identifiable_faces_confirmed": False,
                    "operator_or_public_area_consent": True,
                },
                file_bytes=raw_png,
            )
        self.assertIn("no_identifiable_faces_confirmed", ctx.exception.field_errors)

        # Valid consent succeeds and strips EXIF
        validated = validate_and_scrub_photo_upload(
            metadata={
                "category": "entrance",
                "alt_text": "Step-free entrance with automatic push button.",
                "no_identifiable_faces_confirmed": True,
                "operator_or_public_area_consent": True,
            },
            file_bytes=raw_png,
        )
        self.assertTrue(validated["exif_stripped"])
        with Image.open(io.BytesIO(validated["scrubbed_bytes"])) as scrubbed_img:
            scrubbed_exif = scrubbed_img.getexif()
            self.assertNotIn(0x010E, scrubbed_exif)

    def test_neon_duplicate_database_rejected_and_secrets_redacted(self) -> None:
        with self.assertRaises(ValueError):
            load_config({"NEON_DATABASE_URL": "postgres://user:pass@ep-neon.aws.neon.tech/db"})

        masked = mask_secret("super_secret_service_role_token_12345")
        self.assertNotIn("service_role", masked)
        redacted = redact_sensitive_dict(
            {"user": "maya", "supabase_service_role_key": "sbp_secret", "nested": {"api_key": "123"}}
        )
        self.assertEqual(redacted["supabase_service_role_key"], "[REDACTED]")
        self.assertEqual(redacted["nested"]["api_key"], "[REDACTED]")

    def test_domain_modules_schemas_feature_flags_logging_and_background_jobs(self) -> None:
        # 1. Verify all 7 canonical domain modules load from modules/<slug>/module.py
        for slug in CANONICAL_MODULE_SLUGS:
            mod = load_domain_module(slug)
            self.assertEqual(mod.MODULE_ID, f"modules/{slug}")

        # 2. Verify Zod-style boundary schemas (safe_parse + parse)
        self.assertGreaterEqual(len(BOUNDARY_SCHEMA_REGISTRY), 14)
        valid_search = MapAndListSearchFilterSchema.safe_parse(
            {"q": "civic", "step_free": "true", "min_door_width_cm": "85", "limit": "20"}
        )
        self.assertTrue(valid_search.success)
        assert valid_search.data is not None
        self.assertTrue(valid_search.data["step_free"])
        self.assertEqual(valid_search.data["min_door_width_cm"], 85)

        invalid_search = MapAndListSearchFilterSchema.safe_parse(
            {"category": "not_a_real_category", "limit": "999"}
        )
        self.assertFalse(invalid_search.success)
        assert invalid_search.error is not None
        self.assertIn("category", invalid_search.error.field_errors)
        self.assertIn("limit", invalid_search.error.field_errors)

        # 3. Verify structured logging with PII and credential redaction
        logger = StructuredLogger()
        entry = logger.info(
            "auth.login_attempt",
            layer="api",
            module="modules/venue-profiles",
            context={
                "email": "maya.lin@example.org",
                "client_ip": "192.168.10.45",
                "password": "SuperSecretPassword123!",
                "note": "Contact maya.lin@example.org from 10.20.30.40 with Bearer secret_token_value_12345",
            },
        )
        ctx = entry["context"]
        self.assertEqual(ctx["password"], "[REDACTED]")
        self.assertEqual(ctx["email"], "m***@example.org")
        self.assertEqual(ctx["client_ip"], "192.168.10.x")
        self.assertNotIn("maya.lin@example.org", ctx["note"])
        self.assertNotIn("10.20.30.40", ctx["note"])
        self.assertIn("[REDACTED_TOKEN]", ctx["note"])
        self.assertEqual(redact_pii_and_secrets("user@domain.org"), "u***@domain.org")

        # 4. Verify feature flags gate unfinished work by default
        flags = FeatureFlagRegistry()
        self.assertTrue(flags.is_enabled("json_venue_import"))
        self.assertFalse(flags.is_enabled("automated_face_blur_prepass"))
        self.assertFalse(flags.is_enabled("realtime_transit_elevator_feed"))
        flags.set_override("automated_face_blur_prepass", True)
        self.assertTrue(flags.is_enabled("automated_face_blur_prepass"))

        # 5. Verify DomainModulesContainer + BackgroundJobRunner + reversible migrations
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cfg = load_config(
                {
                    "ATLAS_DB_PATH": str(tmp_path / "test.db"),
                    "ATLAS_PRIVATE_STORAGE_DIR": str(tmp_path / "storage"),
                }
            )
            db = AtlasDatabase(db_path=cfg.db_path, private_storage_dir=cfg.private_storage_dir)
            seed_if_empty(db)
            container = DomainModulesContainer(db)
            self.assertEqual(len(container.describe_all()), 8)

            search_res = container.map_and_list_search.search_venues({"step_free": "true"})
            self.assertGreaterEqual(search_res["total"], 1)

            # 6. Verify Google Maps & Earth Geospatial module
            first_venue = search_res["items"][0]
            geo_profile = container.google_maps_earth_geospatial.get_venue_geospatial_profile(
                venue_id=first_venue["id"],
                raw_params={"travel_mode": "wheelchair_manual"},
            )
            self.assertIn("google_links", geo_profile)
            self.assertIn("route_from_origin", geo_profile)
            self.assertIn("curb_to_entrance_grade", geo_profile)
            self.assertIn("google_maps_wheelchair_transit_url", geo_profile["google_links"])
            self.assertIn("google_earth_3d_flyover_url", geo_profile["google_links"])

            kml_filename, kml_data = container.google_maps_earth_geospatial.export_venue_earth_kml(
                first_venue["id"]
            )
            self.assertTrue(kml_filename.endswith(".kml"))
            self.assertIn("<kml", kml_data)
            self.assertIn("<LookAt>", kml_data)

            revoked = RevokedTokenStore()
            idem = IdempotencyStore()
            tb = TinybirdAdapter(cfg)
            runner = BackgroundJobRunner(db, revoked, idem, tb, logger=logger)
            summary = runner.run_all_maintenance_jobs()
            self.assertEqual(summary["runs_completed"], 1)
            self.assertGreaterEqual(
                summary["jobs"]["compute_stale_venue_digest"]["stale_reverify_count"], 1
            )

        # 6. Verify forward and reversible down-migrations exist and cover all 10 tables
        root_dir = Path(__file__).resolve().parent.parent
        up_sql = (
            root_dir / "supabase" / "migrations" / "20261101000000_accessable_atlas_init.sql"
        ).read_text(encoding="utf-8")
        down_sql = (
            root_dir
            / "supabase"
            / "migrations"
            / "20261101000001_accessable_atlas_rollback.down.sql"
        ).read_text(encoding="utf-8")
        for table in (
            "workspaces",
            "users",
            "venues",
            "access_attributes",
            "observations",
            "photo_evidence",
            "moderation_reports",
            "saved_views",
            "notification_preferences",
            "audit_events",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS public.{table}", up_sql)
            self.assertIn(f"DROP TABLE IF EXISTS public.{table}", down_sql)


if __name__ == "__main__":
    unittest.main()

