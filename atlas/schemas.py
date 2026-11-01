"""Zod-style composable schema validation at all API and domain module boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from atlas.domain import (
    ACOUSTIC_PROFILES,
    CONFIDENCE_LEVELS,
    CONSENT_STATUSES,
    DOOR_OPENER_TYPES,
    ELEVATOR_STATUSES,
    FRESHNESS_STATES,
    GRAB_BAR_TYPES,
    LIGHTING_LEVELS,
    MODERATION_REASONS,
    MODERATION_STATUSES,
    OBSERVER_ROLES,
    PATHWAY_SURFACES,
    PHOTO_CATEGORIES,
    RESTROOM_TYPES,
    VENUE_CATEGORIES,
    VENUE_STATUSES,
)
from atlas.validation import (
    ValidationError,
    sanitize_plain_text,
    validate_access_attributes_payload,
    validate_account_deletion_payload,
    validate_and_scrub_photo_upload,
    validate_auth_payload,
    validate_moderation_report_payload,
    validate_moderation_resolution_payload,
    validate_observation_payload,
    validate_photo_review_payload,
    validate_saved_view_payload,
    validate_settings_payload,
    validate_venue_import_payload,
    validate_venue_payload,
)


@dataclass(frozen=True)
class SafeParseResult:
    """Result container mirroring Zod's safeParse({ success, data, error }) contract."""

    success: bool
    data: dict[str, Any] | None = None
    error: ValidationError | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.success:
            return {"success": True, "data": self.data}
        assert self.error is not None
        return {"success": False, "error": self.error.to_dict()}


class BoundarySchema:
    """Composable Zod-style schema wrapper enforcing strict boundary parsing."""

    def __init__(
        self,
        name: str,
        validator_fn: Callable[..., dict[str, Any]],
        description: str = "",
        field_specs: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self._validator_fn = validator_fn
        self.description = description
        self.field_specs = field_specs or {}

    def parse(self, payload: Any, **kwargs: Any) -> dict[str, Any]:
        """Validate and normalize payload or raise ValidationError."""
        return self._validator_fn(payload, **kwargs)

    def safe_parse(self, payload: Any, **kwargs: Any) -> SafeParseResult:
        """Validate payload without throwing, returning SafeParseResult."""
        try:
            validated = self.parse(payload, **kwargs)
            return SafeParseResult(success=True, data=validated, error=None)
        except ValidationError as exc:
            return SafeParseResult(success=False, data=None, error=exc)

    def describe(self) -> dict[str, Any]:
        """Return schema metadata for introspection and contract testing."""
        return {
            "schema": self.name,
            "description": self.description,
            "fields": dict(self.field_specs),
        }


def validate_search_filters_boundary(payload: Any) -> dict[str, Any]:
    """Validate and normalize map and list search query parameters at the HTTP/module boundary."""
    if not isinstance(payload, dict):
        raise ValidationError("Search filter boundary input must be an object.")
    errors: dict[str, str] = {}

    def _to_bool(val: Any) -> bool:
        if isinstance(val, bool):
            return val
        return str(val or "false").strip().lower() in ("1", "true", "yes")

    q_raw = str(payload.get("q") or "").strip()
    try:
        q_clean = sanitize_plain_text(q_raw, max_len=120) if q_raw else ""
    except ValueError as exc:
        errors["q"] = f"Search query: {exc}"
        q_clean = ""

    category = str(payload.get("category") or "all").strip()
    if category != "all" and category not in VENUE_CATEGORIES:
        errors["category"] = (
            f"Category filter must be 'all' or one of: {', '.join(VENUE_CATEGORIES.keys())}."
        )

    city_raw = str(payload.get("city") or "all").strip()
    try:
        city = sanitize_plain_text(city_raw, max_len=80) if city_raw else "all"
    except ValueError as exc:
        errors["city"] = f"City filter: {exc}"
        city = "all"

    freshness = str(payload.get("freshness") or "all").strip()
    if freshness != "all" and freshness not in FRESHNESS_STATES:
        errors["freshness"] = (
            f"Freshness filter must be 'all' or one of: {', '.join(FRESHNESS_STATES)}."
        )

    min_door_raw = payload.get("min_door_width_cm", 0)
    min_door_cm = 0
    if min_door_raw not in (None, "", 0, "0"):
        try:
            min_door_cm = int(min_door_raw)
            if min_door_cm < 0 or min_door_cm > 300:
                raise ValueError()
        except (TypeError, ValueError):
            errors["min_door_width_cm"] = "Must be an integer between 0 and 300."

    limit_raw = payload.get("limit", 50)
    limit = 50
    try:
        limit = int(limit_raw)
        if limit < 1 or limit > 100:
            raise ValueError()
    except (TypeError, ValueError):
        errors["limit"] = "limit must be an integer between 1 and 100."

    offset_raw = payload.get("offset", 0)
    offset = 0
    try:
        offset = int(offset_raw)
        if offset < 0 or offset > 10000:
            raise ValueError()
    except (TypeError, ValueError):
        errors["offset"] = "offset must be an integer between 0 and 10000."

    if errors:
        raise ValidationError("Invalid map and list search query parameters.", errors)

    return {
        "q": q_clean,
        "category": category,
        "city": city,
        "freshness": freshness,
        "step_free": _to_bool(payload.get("step_free")),
        "min_door_width_cm": min_door_cm,
        "accessible_restroom": _to_bool(payload.get("accessible_restroom")),
        "elevator_operational": _to_bool(payload.get("elevator_operational")),
        "quiet_space": _to_bool(payload.get("quiet_space")),
        "hearing_loop": _to_bool(payload.get("hearing_loop")),
        "braille_signage": _to_bool(payload.get("braille_signage")),
        "include_archived": _to_bool(payload.get("include_archived")),
        "limit": limit,
        "offset": offset,
    }


def validate_geospatial_route_boundary(payload: Any) -> dict[str, Any]:
    """Validate Google Maps & Earth geospatial route calculation parameters."""
    if not isinstance(payload, dict):
        raise ValidationError("Geospatial route request must be a JSON object.")
    errors: dict[str, str] = {}

    origin_lat: float | None = None
    origin_lng: float | None = None

    if payload.get("origin_lat") not in (None, ""):
        try:
            origin_lat = float(payload["origin_lat"])
            if origin_lat < -90.0 or origin_lat > 90.0:
                raise ValueError()
        except (TypeError, ValueError):
            errors["origin_lat"] = "origin_lat must be a valid latitude between -90.0 and 90.0."

    if payload.get("origin_lng") not in (None, ""):
        try:
            origin_lng = float(payload["origin_lng"])
            if origin_lng < -180.0 or origin_lng > 180.0:
                raise ValueError()
        except (TypeError, ValueError):
            errors["origin_lng"] = "origin_lng must be a valid longitude between -180.0 and 180.0."

    if (origin_lat is None) != (origin_lng is None):
        errors["origin_coordinates"] = (
            "Both origin_lat and origin_lng must be provided together when specifying a custom origin."
        )

    origin_label = ""
    if payload.get("origin_label"):
        try:
            origin_label = sanitize_plain_text(payload["origin_label"], max_len=120)
        except ValueError as exc:
            errors["origin_label"] = f"Origin label: {exc}"

    travel_mode = str(payload.get("travel_mode") or "wheelchair_manual").strip()
    allowed_modes = ("wheelchair_manual", "wheelchair_power", "assisted_cane_walker")
    if travel_mode not in allowed_modes:
        errors["travel_mode"] = (
            f"travel_mode must be one of: {', '.join(allowed_modes)}."
        )

    if errors:
        raise ValidationError("Invalid Google Maps / Earth geospatial route parameters.", errors)

    return {
        "origin_lat": origin_lat,
        "origin_lng": origin_lng,
        "origin_label": origin_label,
        "travel_mode": travel_mode,
    }


# ============================================================================
# Canonical Boundary Schemas Registry
# ============================================================================

AuthLoginSchema = BoundarySchema(
    name="AuthLoginSchema",
    validator_fn=lambda payload: validate_auth_payload(payload, is_register=False),
    description="Boundary schema for user sign-in credentials.",
    field_specs={"email": "email (<=254 chars)", "password": "string (8..128 chars)"},
)

AuthRegisterSchema = BoundarySchema(
    name="AuthRegisterSchema",
    validator_fn=lambda payload: validate_auth_payload(payload, is_register=True),
    description="Boundary schema for self-service community/operator registration.",
    field_specs={
        "email": "email (<=254 chars)",
        "password": "string (8..128 chars)",
        "display_name": "plain_text (2..80 chars)",
        "role": "enum(viewer, contributor, operator)",
        "ai_consent_granted": "boolean",
        "telemetry_opt_in": "boolean",
    },
)

StructuredAccessAttributesSchema = BoundarySchema(
    name="StructuredAccessAttributesSchema",
    validator_fn=validate_access_attributes_payload,
    description="1:1 physical entrance, facility, and interior route measurements per venue.",
    field_specs={
        "step_free_entrance": "boolean",
        "entrance_door_width_cm": "int (40..300)",
        "threshold_height_mm": "int (0..250)",
        "door_opener_type": f"enum({', '.join(DOOR_OPENER_TYPES.keys())})",
        "ramp_present": "boolean",
        "ramp_slope_degrees": "optional float (0.0..30.0)",
        "entrance_notes": "plain_text (0..500 chars)",
        "accessible_restroom_type": f"enum({', '.join(RESTROOM_TYPES.keys())})",
        "grab_bars": f"enum({', '.join(GRAB_BAR_TYPES.keys())})",
        "turning_circle_cm": "int (0..400)",
        "elevator_status": f"enum({', '.join(ELEVATOR_STATUSES.keys())})",
        "braille_tactile_signage": "boolean",
        "hearing_loop_available": "boolean",
        "quiet_sensory_space": "boolean",
        "accessible_parking_spaces": "int (0..500)",
        "pathway_surface": f"enum({', '.join(PATHWAY_SURFACES.keys())})",
        "min_corridor_width_cm": "int (50..500)",
        "lighting_level": f"enum({', '.join(LIGHTING_LEVELS.keys())})",
        "acoustic_profile": f"enum({', '.join(ACOUSTIC_PROFILES.keys())})",
        "route_notes": "plain_text (0..500 chars)",
    },
)

VenueProfileSchema = BoundarySchema(
    name="VenueProfileSchema",
    validator_fn=validate_venue_payload,
    description="Venue profile identity, geospatial coordinates, status, and nested access attributes.",
    field_specs={
        "name": "plain_text (2..140 chars)",
        "category": f"enum({', '.join(VENUE_CATEGORIES.keys())})",
        "address": "plain_text (4..220 chars)",
        "city": "plain_text (2..80 chars)",
        "postal_code": "plain_text (3..20 chars)",
        "latitude": "float (-90.0..90.0)",
        "longitude": "float (-180.0..180.0)",
        "operating_hours": "plain_text (3..160 chars)",
        "summary": "plain_text (10..1200 chars)",
        "status": f"enum({', '.join(VENUE_STATUSES)})",
        "active_barrier_alert": "optional plain_text (3..400 chars)",
        "access_attributes": "StructuredAccessAttributesSchema",
    },
)

VenueImportSchema = BoundarySchema(
    name="VenueImportSchema",
    validator_fn=validate_venue_import_payload,
    description="Imported municipal/audit venue JSON requiring explicit human confirmation.",
    field_specs={
        "venue_data": "VenueProfileSchema",
        "import_source": "plain_text (2..120 chars)",
        "user_confirmed_imported_values": "literal(true)",
    },
)

TimestampedObservationSchema = BoundarySchema(
    name="TimestampedObservationSchema",
    validator_fn=validate_observation_payload,
    description="Timestamped field observation with observer role, confidence tier, and measurements.",
    field_specs={
        "observer_role": f"enum({', '.join(OBSERVER_ROLES.keys())})",
        "confidence_level": f"enum({', '.join(CONFIDENCE_LEVELS.keys())})",
        "summary": "plain_text (10..1000 chars)",
        "measured_door_width_cm": "optional int (40..300)",
        "elevator_operational_check": "optional enum(operational, out_of_service, not_applicable)",
        "barriers_noted": "plain_text (0..500 chars)",
        "is_operational_alert": "boolean",
    },
)

PhotoEvidenceUploadSchema = BoundarySchema(
    name="PhotoEvidenceUploadSchema",
    validator_fn=lambda payload, file_bytes=b"", max_bytes=5242880: validate_and_scrub_photo_upload(
        metadata=payload, file_bytes=file_bytes, max_bytes=max_bytes
    ),
    description="Consent-attested photo upload with mandatory alt text and Pillow EXIF scrubbing.",
    field_specs={
        "category": f"enum({', '.join(PHOTO_CATEGORIES.keys())})",
        "alt_text": "plain_text (10..300 chars)",
        "caption": "plain_text (0..300 chars)",
        "no_identifiable_faces_confirmed": "literal(true)",
        "operator_or_public_area_consent": "literal(true)",
        "file": "binary(PNG|JPEG|WEBP, <=5MB)",
    },
)

PhotoReviewSchema = BoundarySchema(
    name="PhotoReviewSchema",
    validator_fn=validate_photo_review_payload,
    description="Moderator consent review decision for uploaded photo evidence.",
    field_specs={
        "consent_status": f"enum({', '.join(CONSENT_STATUSES)})",
        "review_notes": "plain_text (5..400 chars)",
        "confirm": "literal(true)",
    },
)

MapAndListSearchFilterSchema = BoundarySchema(
    name="MapAndListSearchFilterSchema",
    validator_fn=validate_search_filters_boundary,
    description="Map and list search query filter & pagination boundary contract.",
    field_specs={
        "q": "optional plain_text (<=120 chars)",
        "category": "all | VenueCategory",
        "city": "all | plain_text (<=80 chars)",
        "freshness": f"all | enum({', '.join(FRESHNESS_STATES)})",
        "step_free": "boolean",
        "min_door_width_cm": "int (0..300)",
        "accessible_restroom": "boolean",
        "elevator_operational": "boolean",
        "quiet_space": "boolean",
        "hearing_loop": "boolean",
        "braille_signage": "boolean",
        "include_archived": "boolean",
        "limit": "int (1..100)",
        "offset": "int (0..10000)",
    },
)

ModerationReportSchema = BoundarySchema(
    name="ModerationReportSchema",
    validator_fn=validate_moderation_report_payload,
    description="Community or operator report flagging inaccurate measurements or privacy concerns.",
    field_specs={
        "venue_id": "id (4..64 chars)",
        "target_type": "enum(venue, observation, photo_evidence)",
        "target_id": "id (4..64 chars)",
        "reason": f"enum({', '.join(MODERATION_REASONS.keys())})",
        "details": "plain_text (10..800 chars)",
    },
)

ModerationResolutionSchema = BoundarySchema(
    name="ModerationResolutionSchema",
    validator_fn=validate_moderation_resolution_payload,
    description="Moderator resolution decision for an open moderation report.",
    field_specs={
        "status": f"enum({', '.join(s for s in MODERATION_STATUSES if s != 'open')})",
        "resolution_notes": "plain_text (8..600 chars)",
        "confirm": "literal(true)",
    },
)

SavedViewSchema = BoundarySchema(
    name="SavedViewSchema",
    validator_fn=validate_saved_view_payload,
    description="User-persisted search filter view.",
    field_specs={"name": "plain_text (2..80 chars)", "filters": "SearchFilterSubset"},
)

UserSettingsSchema = BoundarySchema(
    name="UserSettingsSchema",
    validator_fn=validate_settings_payload,
    description="User notification, AI consent, and telemetry preferences.",
    field_specs={
        "barrier_alerts_enabled": "boolean",
        "stale_venue_digest_enabled": "boolean",
        "moderation_updates_enabled": "boolean",
        "ai_consent_granted": "boolean",
        "telemetry_opt_in": "boolean",
    },
)

AccountDeletionSchema = BoundarySchema(
    name="AccountDeletionSchema",
    validator_fn=validate_account_deletion_payload,
    description="Self-service account deletion and personal data anonymization confirmation.",
    field_specs={
        "confirm": "literal(true)",
        "confirmation_phrase": "literal('DELETE MY ACCOUNT')",
    },
)

GeospatialRouteQuerySchema = BoundarySchema(
    name="GeospatialRouteQuerySchema",
    validator_fn=validate_geospatial_route_boundary,
    description="Google Maps & Earth wheelchair route, ADA grade, and 3D flyover boundary contract.",
    field_specs={
        "origin_lat": "optional float (-90.0..90.0)",
        "origin_lng": "optional float (-180.0..180.0)",
        "origin_label": "optional plain_text (<=120 chars)",
        "travel_mode": "enum(wheelchair_manual, wheelchair_power, assisted_cane_walker)",
    },
)

BOUNDARY_SCHEMA_REGISTRY: dict[str, BoundarySchema] = {
    schema.name: schema
    for schema in (
        AuthLoginSchema,
        AuthRegisterSchema,
        StructuredAccessAttributesSchema,
        VenueProfileSchema,
        VenueImportSchema,
        TimestampedObservationSchema,
        PhotoEvidenceUploadSchema,
        PhotoReviewSchema,
        MapAndListSearchFilterSchema,
        ModerationReportSchema,
        ModerationResolutionSchema,
        SavedViewSchema,
        UserSettingsSchema,
        AccountDeletionSchema,
        GeospatialRouteQuerySchema,
    )
}

