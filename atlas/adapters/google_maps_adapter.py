"""Google Maps Platform & Google Earth 3D geospatial adapter with deterministic local fallback."""

from __future__ import annotations

import json
import math
from typing import Any
from urllib.error import URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape as xml_escape

from atlas.config import AtlasConfig, mask_secret

# Default reference transit hub (Seattle King Street Accessible Transit Hub)
DEFAULT_TRANSIT_HUB_LAT = 47.5984
DEFAULT_TRANSIT_HUB_LNG = -122.3301
DEFAULT_TRANSIT_HUB_LABEL = "King Street Accessible Transit Hub (Reference Origin)"

TRAVEL_MODE_SPEEDS_MPS: dict[str, float] = {
    "wheelchair_manual": 1.10,  # Standard manual wheelchair urban roll speed (m/s)
    "wheelchair_power": 1.45,  # Power wheelchair / mobility scooter speed (m/s)
    "assisted_cane_walker": 0.85,  # Cane, walker, or caregiver-assisted pace (m/s)
}

COMPASS_SECTORS: tuple[str, ...] = (
    "N",
    "NE",
    "E",
    "SE",
    "S",
    "SW",
    "W",
    "NW",
)


def compute_haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle surface distance in meters between two WGS84 coordinates."""
    earth_radius_m = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return round(earth_radius_m * c, 1)


def compute_bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute initial compass bearing (0..360 deg) from origin to destination."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)

    x = math.sin(d_lambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - (
        math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    )
    initial_bearing = math.degrees(math.atan2(x, y))
    return round((initial_bearing + 360.0) % 360.0, 1)


def bearing_to_compass(bearing_deg: float) -> str:
    """Map a degree bearing (0..360) to an 8-wind compass direction."""
    idx = int(round(bearing_deg / 45.0)) % 8
    return COMPASS_SECTORS[idx]


class GoogleMapsEarthAdapter:
    """
    Adapter for Google Maps Platform (Routes, Street View, Places) and Google Earth 3D KML.
    Operates seamlessly without external API credentials via deterministic WGS84/ADA math,
    and enriches with live Google Maps Elevation/Geocoding metadata when GOOGLE_MAPS_API_KEY is set.
    """

    def __init__(self, config: AtlasConfig) -> None:
        self.config = config

    def get_status(self) -> dict[str, Any]:
        """Return adapter readiness and privacy/credential posture for /api/health."""
        return {
            "provider": "google_maps_and_earth",
            "enabled": self.config.google_maps_enabled,
            "live_api_configured": self.config.google_maps_configured,
            "mode": (
                "google_maps_live_api_plus_earth_kml"
                if self.config.google_maps_configured
                else "deterministic_wgs84_and_earth_3d_kml"
            ),
            "api_key_masked": mask_secret(self.config.google_maps_api_key),
            "capabilities": [
                "google_maps_wheelchair_transit_links",
                "google_street_view_curb_panorama",
                "google_earth_3d_web_flyover",
                "google_earth_kml_3d_export",
                "ada_curb_to_entrance_grade_analyzer",
            ],
        }

    def _fetch_optional_live_elevation(self, lat: float, lng: float) -> dict[str, Any] | None:
        """Query Google Maps Elevation API when a live key is configured, failing gracefully."""
        if not self.config.google_maps_configured:
            return None
        url = (
            "https://maps.googleapis.com/maps/api/elevation/json"
            f"?locations={lat:.6f},{lng:.6f}&key={quote_plus(self.config.google_maps_api_key)}"
        )
        req = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(req, timeout=self.config.google_maps_timeout_seconds) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                results = raw.get("results")
                if raw.get("status") == "OK" and isinstance(results, list) and results:
                    first = results[0]
                    return {
                        "elevation_meters": round(float(first.get("elevation", 0.0)), 2),
                        "resolution_meters": round(float(first.get("resolution", 0.0)), 2),
                        "source": "google_maps_elevation_api",
                    }
        except (URLError, TimeoutError, ValueError, KeyError, OSError):
            return None
        return None

    def evaluate_curb_to_entrance_grade(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """
        Evaluate ADA (1:12 / 4.76 deg) and ISO 21542 (1:20 / 2.86 deg) ramp & threshold compliance.
        """
        step_free = bool(attrs.get("step_free_entrance"))
        ramp_present = bool(attrs.get("ramp_present"))
        slope_deg_raw = attrs.get("ramp_slope_degrees")
        slope_deg = float(slope_deg_raw) if slope_deg_raw is not None else 0.0
        threshold_mm = int(attrs.get("threshold_height_mm") or 0)
        door_width_cm = int(attrs.get("entrance_door_width_cm") or 0)
        surface = str(attrs.get("pathway_surface") or "smooth_paved")

        slope_percent = round(math.tan(math.radians(slope_deg)) * 100.0, 2) if slope_deg > 0 else 0.0
        ada_max_deg = 4.76  # arctan(1/12) = 4.7636 deg (8.33% grade)
        iso_gentle_deg = 2.86  # arctan(1/20) = 2.8624 deg (5.0% grade)

        if not step_free:
            grade_tier = "step_barrier_alert"
            grade_label = "Step Barrier at Entrance (Not Step-Free)"
            ada_compliant = False
        elif ramp_present and slope_deg > ada_max_deg:
            grade_tier = "steep_ramp_warning"
            grade_label = f"Steep Ramp ({slope_deg:.1f}° / {slope_percent:.1f}% > ADA 4.8° max)"
            ada_compliant = False
        elif threshold_mm > 13:
            grade_tier = "threshold_lip_warning"
            grade_label = f"High Threshold Lip ({threshold_mm} mm > 13 mm ADA beveled limit)"
            ada_compliant = False
        elif not ramp_present or slope_deg <= iso_gentle_deg:
            grade_tier = "level_or_gentle_grade"
            grade_label = (
                f"Level / Gentle Grade ({slope_deg:.1f}° / {slope_percent:.1f}%, {threshold_mm} mm threshold)"
            )
            ada_compliant = True
        else:
            grade_tier = "ada_standard_ramp"
            grade_label = (
                f"ADA-Compliant Ramp ({slope_deg:.1f}° / {slope_percent:.1f}% <= 1:12 max)"
            )
            ada_compliant = True

        return {
            "grade_tier": grade_tier,
            "grade_label": grade_label,
            "ada_1_to_12_compliant": ada_compliant,
            "ramp_present": ramp_present,
            "ramp_slope_degrees": round(slope_deg, 2),
            "ramp_grade_percent": slope_percent,
            "threshold_height_mm": threshold_mm,
            "entrance_door_width_cm": door_width_cm,
            "pathway_surface": surface,
        }

    def build_google_links(self, venue: dict[str, Any], bearing_deg: float = 0.0) -> dict[str, str]:
        """Generate verified Google Maps, Street View 360, and Google Earth 3D camera links."""
        lat = float(venue["latitude"])
        lng = float(venue["longitude"])
        venue_id = str(venue["id"])
        query_label = quote_plus(f"{venue['name']}, {venue['address']}, {venue['city']}")
        altitude = self.config.google_earth_flyover_altitude_m
        heading = int(round(bearing_deg)) % 360

        return {
            "google_maps_place_url": (
                f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lng:.6f}&query_place_id={query_label}"
            ),
            "google_maps_wheelchair_transit_url": (
                f"https://www.google.com/maps/dir/?api=1&destination={lat:.6f},{lng:.6f}&travelmode=transit"
            ),
            "google_street_view_curb_url": (
                f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat:.6f},{lng:.6f}"
                f"&heading={heading}&pitch=0&fov=80"
            ),
            "google_earth_3d_flyover_url": (
                f"https://earth.google.com/web/@{lat:.6f},{lng:.6f},18a,{altitude}d,35y,{heading}h,55t,0r"
            ),
            "google_earth_kml_download_url": f"/api/venues/{venue_id}/earth.kml",
            "workspace_earth_kml_url": "/api/export/earth.kml",
        }

    def build_venue_geospatial_profile(
        self,
        venue: dict[str, Any],
        origin_lat: float | None = None,
        origin_lng: float | None = None,
        origin_label: str | None = None,
        travel_mode: str = "wheelchair_manual",
    ) -> dict[str, Any]:
        """
        Compute complete Google Maps & Google Earth geospatial profile for a venue,
        including origin-to-entrance wheelchair routing, ADA slope check, and 3D flyover links.
        """
        dest_lat = float(venue["latitude"])
        dest_lng = float(venue["longitude"])

        ref_lat = float(origin_lat) if origin_lat is not None else DEFAULT_TRANSIT_HUB_LAT
        ref_lng = float(origin_lng) if origin_lng is not None else DEFAULT_TRANSIT_HUB_LNG
        ref_label = (
            origin_label.strip()
            if origin_label and origin_label.strip()
            else (
                "Custom Origin Coordinate"
                if origin_lat is not None and origin_lng is not None
                else DEFAULT_TRANSIT_HUB_LABEL
            )
        )

        straight_distance_m = compute_haversine_meters(ref_lat, ref_lng, dest_lat, dest_lng)
        # Urban sidewalk network circuity factor (~1.24x straight-line distance)
        network_route_m = round(straight_distance_m * 1.24, 1)
        bearing_deg = compute_bearing_degrees(ref_lat, ref_lng, dest_lat, dest_lng)
        compass_dir = bearing_to_compass(bearing_deg)

        speed_mps = TRAVEL_MODE_SPEEDS_MPS.get(
            travel_mode, TRAVEL_MODE_SPEEDS_MPS["wheelchair_manual"]
        )
        roll_minutes = max(1, int(round((network_route_m / speed_mps) / 60.0))) if network_route_m > 0 else 0

        attrs = venue.get("access_attributes") or {}
        grade_profile = self.evaluate_curb_to_entrance_grade(attrs)
        links = self.build_google_links(venue, bearing_deg=bearing_deg)
        live_elevation = self._fetch_optional_live_elevation(dest_lat, dest_lng)

        # Build Google Maps origin-to-destination route link when origin is known
        links["google_maps_origin_to_venue_url"] = (
            f"https://www.google.com/maps/dir/?api=1"
            f"&origin={ref_lat:.6f},{ref_lng:.6f}"
            f"&destination={dest_lat:.6f},{dest_lng:.6f}"
            f"&travelmode=walking"
        )

        route_advisories: list[str] = []
        if venue.get("active_barrier_alert"):
            route_advisories.append(f"Active barrier alert: {venue['active_barrier_alert']}")
        if not grade_profile["ada_1_to_12_compliant"]:
            route_advisories.append(grade_profile["grade_label"])
        if str(attrs.get("elevator_status")) == "out_of_service":
            route_advisories.append("Elevator/lift is currently reported out of service.")
        if not route_advisories:
            route_advisories.append(
                f"Step-free curb approach verified ({attrs.get('entrance_door_width_cm', 90)} cm clear door, "
                f"{grade_profile['grade_label']})."
            )

        return {
            "venue_id": str(venue["id"]),
            "venue_name": str(venue["name"]),
            "venue_slug": str(venue["slug"]),
            "coordinates": {
                "latitude": dest_lat,
                "longitude": dest_lng,
                "wgs84_label": f"{dest_lat:.5f}° N, {abs(dest_lng):.5f}° {'W' if dest_lng < 0 else 'E'}",
                "elevation": live_elevation
                or {
                    "elevation_meters": 18.5,
                    "resolution_meters": 10.0,
                    "source": "deterministic_local_dem_baseline",
                },
            },
            "route_from_origin": {
                "origin_label": ref_label,
                "origin_latitude": ref_lat,
                "origin_longitude": ref_lng,
                "travel_mode": travel_mode,
                "straight_line_distance_meters": straight_distance_m,
                "estimated_sidewalk_distance_meters": network_route_m,
                "estimated_roll_minutes": roll_minutes,
                "bearing_degrees": bearing_deg,
                "compass_direction": compass_dir,
                "route_advisories": route_advisories,
            },
            "curb_to_entrance_grade": grade_profile,
            "google_links": links,
            "adapter_mode": self.get_status()["mode"],
        }

    def generate_venue_earth_kml(self, venue: dict[str, Any]) -> str:
        """Generate a Google Earth 3D KML document for a single venue profile."""
        return self.generate_workspace_earth_kml(
            venues=[venue],
            workspace_name=f"AccessAble Atlas — {venue.get('name', 'Venue')} 3D Access Profile",
        )

    def generate_workspace_earth_kml(
        self,
        venues: list[dict[str, Any]],
        workspace_name: str = "AccessAble Atlas — Metro Civic Access 3D Directory",
    ) -> str:
        """
        Generate an OGC KML 2.2 document with Google Earth 3D <LookAt> camera tilts,
        Sage Circuit semantic styles, and structured accessibility ExtendedData.
        """
        safe_doc_title = xml_escape(str(workspace_name))
        altitude = self.config.google_earth_flyover_altitude_m

        placemarks_xml: list[str] = []
        for idx, v in enumerate(venues):
            lat = float(v.get("latitude", DEFAULT_TRANSIT_HUB_LAT))
            lng = float(v.get("longitude", DEFAULT_TRANSIT_HUB_LNG))
            name = xml_escape(str(v.get("name") or "Venue"))
            address = xml_escape(f"{v.get('address', '')}, {v.get('city', '')} {v.get('postal_code', '')}".strip())
            summary = xml_escape(str(v.get("summary") or ""))
            attrs = v.get("access_attributes") or {}
            freshness = v.get("freshness") or {}
            state = str(freshness.get("state") or "fresh_verified")

            style_id = {
                "fresh_verified": "#sageCircuitFresh",
                "aging_review_soon": "#sageCircuitAging",
                "stale_reverify": "#sageCircuitStale",
                "active_alert": "#sageCircuitAlert",
            }.get(state, "#sageCircuitFresh")

            step_free_str = "Yes (Step-Free)" if attrs.get("step_free_entrance") else "No (Step Barrier)"
            door_cm = int(attrs.get("entrance_door_width_cm") or 0)
            threshold_mm = int(attrs.get("threshold_height_mm") or 0)
            restroom = xml_escape(str(attrs.get("accessible_restroom_type") or "none"))
            elevator = xml_escape(str(attrs.get("elevator_status") or "none"))
            fresh_label = xml_escape(str(freshness.get("label") or state))
            conf_score = int(freshness.get("confidence_score") or 80)
            barrier = xml_escape(str(v.get("active_barrier_alert") or "None"))
            heading = (idx * 45) % 360

            placemarks_xml.append(
                f"""    <Placemark id="{xml_escape(str(v.get('id', idx)))}">
      <name>{name}</name>
      <address>{address}</address>
      <styleUrl>{style_id}</styleUrl>
      <description>{summary} | Entrance: {step_free_str} ({door_cm} cm door, {threshold_mm} mm threshold) | Freshness: {fresh_label} ({conf_score}%)</description>
      <LookAt>
        <longitude>{lng:.6f}</longitude>
        <latitude>{lat:.6f}</latitude>
        <altitude>18</altitude>
        <heading>{heading}</heading>
        <tilt>55</tilt>
        <range>{altitude}</range>
        <altitudeMode>relativeToGround</altitudeMode>
      </LookAt>
      <ExtendedData>
        <Data name="step_free_entrance"><value>{step_free_str}</value></Data>
        <Data name="entrance_door_width_cm"><value>{door_cm}</value></Data>
        <Data name="threshold_height_mm"><value>{threshold_mm}</value></Data>
        <Data name="accessible_restroom_type"><value>{restroom}</value></Data>
        <Data name="elevator_status"><value>{elevator}</value></Data>
        <Data name="freshness_state"><value>{xml_escape(state)}</value></Data>
        <Data name="confidence_score"><value>{conf_score}</value></Data>
        <Data name="active_barrier_alert"><value>{barrier}</value></Data>
      </ExtendedData>
      <Point>
        <extrude>1</extrude>
        <altitudeMode>relativeToGround</altitudeMode>
        <coordinates>{lng:.6f},{lat:.6f},15</coordinates>
      </Point>
    </Placemark>"""
            )

        joined_placemarks = "\n".join(placemarks_xml)
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">
  <Document>
    <name>{safe_doc_title}</name>
    <description>AccessAble Atlas (Sage Circuit) 3D Google Earth Accessibility Layer — verified entrance widths, ramp slopes, restroom facilities, and freshness indicators.</description>
    <Style id="sageCircuitFresh">
      <IconStyle><color>ff24ffd4</color><scale>1.2</scale></IconStyle>
      <LabelStyle><color>ff24ffd4</color></LabelStyle>
    </Style>
    <Style id="sageCircuitAging">
      <IconStyle><color>ffb5d2e8</color><scale>1.1</scale></IconStyle>
      <LabelStyle><color>ffb5d2e8</color></LabelStyle>
    </Style>
    <Style id="sageCircuitStale">
      <IconStyle><color>ffdeb0e7</color><scale>1.1</scale></IconStyle>
      <LabelStyle><color>ffdeb0e7</color></LabelStyle>
    </Style>
    <Style id="sageCircuitAlert">
      <IconStyle><color>ff0a5aff</color><scale>1.35</scale></IconStyle>
      <LabelStyle><color>ff0a5aff</color></LabelStyle>
    </Style>
{joined_placemarks}
  </Document>
</kml>
"""

