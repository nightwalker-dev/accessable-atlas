"""Registry and dynamic loader for the 7 domain modules in modules/<slug>/module.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

from atlas.adapters.google_maps_adapter import GoogleMapsEarthAdapter
from atlas.config import load_config
from atlas.db.database import AtlasDatabase

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
MODULES_DIR = ROOT_DIR / "modules"

CANONICAL_MODULE_SLUGS: tuple[str, ...] = (
    "venue-profiles",
    "structured-access-attributes",
    "timestamped-observations",
    "consent-reviewed-photo-evidence",
    "freshness-indicators",
    "map-and-list-search",
    "moderation",
    "google-maps-earth-geospatial",
)

_LOADED_MODULES: dict[str, ModuleType] = {}


def load_domain_module(slug: str) -> ModuleType:
    """Load a domain module slice from modules/<slug>/module.py."""
    if slug not in CANONICAL_MODULE_SLUGS:
        raise KeyError(f"Unknown domain module slug: {slug}")
    if slug in _LOADED_MODULES:
        return _LOADED_MODULES[slug]

    module_path = MODULES_DIR / slug / "module.py"
    if not module_path.is_file():
        raise FileNotFoundError(f"Domain module file not found: {module_path}")

    py_mod_name = f"atlas_domain_module_{slug.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(py_mod_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create module spec for {module_path}")

    mod = importlib.util.module_from_spec(spec)
    sys.modules[py_mod_name] = mod
    spec.loader.exec_module(mod)
    _LOADED_MODULES[slug] = mod
    return mod


class DomainModulesContainer:
    """Instantiated container binding the 8 domain modules to the persistence engine."""

    def __init__(
        self,
        db: AtlasDatabase,
        google_maps_adapter: GoogleMapsEarthAdapter | None = None,
    ) -> None:
        vp_mod = load_domain_module("venue-profiles")
        saa_mod = load_domain_module("structured-access-attributes")
        to_mod = load_domain_module("timestamped-observations")
        crpe_mod = load_domain_module("consent-reviewed-photo-evidence")
        fi_mod = load_domain_module("freshness-indicators")
        mls_mod = load_domain_module("map-and-list-search")
        mod_mod = load_domain_module("moderation")
        gme_mod = load_domain_module("google-maps-earth-geospatial")

        gm_adapter = google_maps_adapter or GoogleMapsEarthAdapter(load_config())

        self.venue_profiles = vp_mod.VenueProfilesModule(db)
        self.structured_access_attributes = saa_mod.StructuredAccessAttributesModule()
        self.timestamped_observations = to_mod.TimestampedObservationsModule(db)
        self.consent_reviewed_photo_evidence = (
            crpe_mod.ConsentReviewedPhotoEvidenceModule(db)
        )
        self.freshness_indicators = fi_mod.FreshnessIndicatorsModule()
        self.map_and_list_search = mls_mod.MapAndListSearchModule(db)
        self.moderation = mod_mod.ModerationModule(db)
        self.google_maps_earth_geospatial = gme_mod.GoogleMapsEarthGeospatialModule(
            db, gm_adapter
        )

    def describe_all(self) -> list[dict[str, Any]]:
        """Return metadata for all 8 domain modules."""
        return [
            {
                "id": "modules/venue-profiles",
                "name": "Venue profiles",
                "schema": self.venue_profiles.schema.name,
            },
            {
                "id": "modules/structured-access-attributes",
                "name": "Structured access attributes",
                "schema": self.structured_access_attributes.schema.name,
            },
            {
                "id": "modules/timestamped-observations",
                "name": "Timestamped observations",
                "schema": self.timestamped_observations.schema.name,
            },
            {
                "id": "modules/consent-reviewed-photo-evidence",
                "name": "Consent-reviewed photo evidence",
                "schema": self.consent_reviewed_photo_evidence.upload_schema.name,
            },
            {
                "id": "modules/freshness-indicators",
                "name": "Freshness indicators",
                "states": list(self.freshness_indicators.states),
            },
            {
                "id": "modules/map-and-list-search",
                "name": "Map and list search",
                "schema": self.map_and_list_search.filter_schema.name,
            },
            {
                "id": "modules/moderation",
                "name": "Moderation",
                "schema": self.moderation.report_schema.name,
            },
            {
                "id": "modules/google-maps-earth-geospatial",
                "name": "Google Maps & Earth Geospatial",
                "schema": self.google_maps_earth_geospatial.schema.name,
            },
        ]

