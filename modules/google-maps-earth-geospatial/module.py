"""Domain module: Google Maps & Earth Geospatial (modules/google-maps-earth-geospatial)."""

from __future__ import annotations

from typing import Any

from atlas.adapters.google_maps_adapter import GoogleMapsEarthAdapter
from atlas.db.database import AtlasDatabase
from atlas.schemas import GeospatialRouteQuerySchema

MODULE_ID = "modules/google-maps-earth-geospatial"
MODULE_NAME = "Google Maps & Earth Geospatial"


class GoogleMapsEarthGeospatialModule:
    """
    Encapsulates Google Maps Platform (Routes, Street View 360, Elevation) and
    Google Earth 3D KML flyover exports, ADA curb-to-entrance grade checks, and
    wheelchair travel time estimation.
    """

    module_id = MODULE_ID
    schema = GeospatialRouteQuerySchema

    def __init__(self, db: AtlasDatabase, adapter: GoogleMapsEarthAdapter) -> None:
        self.db = db
        self.adapter = adapter

    def get_venue_geospatial_profile(
        self,
        venue_id: str,
        raw_params: dict[str, Any] | None = None,
        viewer_user: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate route parameters, load venue, and compute Google Maps/Earth profile."""
        venue = self.db.get_venue_by_id(
            venue_id, viewer_user=viewer_user, include_details=True
        )
        if not venue:
            raise LookupError("Venue profile not found or access restricted.")

        validated = self.schema.parse(raw_params or {})
        return self.adapter.build_venue_geospatial_profile(
            venue=venue,
            origin_lat=validated["origin_lat"],
            origin_lng=validated["origin_lng"],
            origin_label=validated["origin_label"],
            travel_mode=validated["travel_mode"],
        )

    def export_venue_earth_kml(
        self,
        venue_id: str,
        viewer_user: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Return (filename, kml_xml_string) for a single venue's Google Earth 3D placemark."""
        venue = self.db.get_venue_by_id(
            venue_id, viewer_user=viewer_user, include_details=True
        )
        if not venue:
            raise LookupError("Venue profile not found or access restricted.")
        slug = str(venue.get("slug") or venue_id)
        kml_xml = self.adapter.generate_venue_earth_kml(venue)
        return f"{slug}-earth-3d.kml", kml_xml

    def export_workspace_earth_kml(
        self,
        filters: dict[str, Any] | None = None,
        viewer_user: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Return (filename, kml_xml_string) for all filtered published venues in Google Earth."""
        listing = self.db.list_venues(
            filters=filters or {}, viewer_user=viewer_user, limit=100, offset=0
        )
        venues = listing.get("items", [])
        kml_xml = self.adapter.generate_workspace_earth_kml(
            venues=venues,
            workspace_name="AccessAble Atlas — Metro Civic Access 3D Directory",
        )
        return "accessable-atlas-earth-3d.kml", kml_xml

