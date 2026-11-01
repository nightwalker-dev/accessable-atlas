"""Centralized server-side request validation, normalization, and binary image verification."""

from __future__ import annotations

import hashlib
import io
import re
from typing import Any

from PIL import Image, UnidentifiedImageError

from atlas.domain import (
    ACOUSTIC_PROFILES,
    CONFIDENCE_LEVELS,
    CONSENT_STATUSES,
    DOOR_OPENER_TYPES,
    ELEVATOR_STATUSES,
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

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
DANGEROUS_HTML_RE = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|svg|math|style|link|meta|form|input|button)\b[^>]*>|"
    r"javascript\s*:|vbscript\s*:|data\s*:\s*text/html|on[a-z]+\s*=",
    re.IGNORECASE,
)
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

ALLOWED_IMAGE_FORMATS: dict[str, str] = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}


class ValidationError(Exception):
    """Structured validation error containing actionable per-field error messages."""

    def __init__(self, message: str, field_errors: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field_errors = field_errors or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "validation_error",
            "message": self.message,
            "field_errors": self.field_errors,
        }


def sanitize_plain_text(value: Any, max_len: int = 2000) -> str:
    """Normalize plain text, strip control characters, and reject embedded script/HTML payloads."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    cleaned = CONTROL_CHARS_RE.sub("", value).strip()
    if DANGEROUS_HTML_RE.search(cleaned):
        raise ValueError("Input contains disallowed HTML, script, or executable markup.")
    # Escape angle brackets in stored plain text to guarantee zero stored HTML/XSS injection
    cleaned = cleaned.replace("<", "‹").replace(">", "›")
    if len(cleaned) > max_len:
        raise ValueError(f"Must be at most {max_len} characters.")
    return cleaned


def slugify(text: str) -> str:
    """Create a URL-safe slug from a venue name and city."""
    lowered = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return lowered[:88] or "venue"


def _require_str(
    data: dict[str, Any],
    field: str,
    min_len: int,
    max_len: int,
    errors: dict[str, str],
    label: str | None = None,
) -> str:
    display = label or field
    raw = data.get(field)
    if not isinstance(raw, str):
        errors[field] = f"{display} is required and must be text."
        return ""
    try:
        cleaned = sanitize_plain_text(raw, max_len=max_len)
    except ValueError as exc:
        errors[field] = f"{display}: {exc}"
        return ""
    if len(cleaned) < min_len:
        errors[field] = f"{display} must be at least {min_len} characters."
        return ""
    return cleaned


def _require_int(
    data: dict[str, Any],
    field: str,
    min_val: int,
    max_val: int,
    errors: dict[str, str],
    label: str | None = None,
) -> int:
    display = label or field
    raw = data.get(field)
    if isinstance(raw, bool) or raw is None or raw == "":
        errors[field] = f"{display} is required and must be a whole number."
        return min_val
    try:
        val = int(raw)
    except (TypeError, ValueError):
        errors[field] = f"{display} must be a whole number between {min_val} and {max_val}."
        return min_val
    if val < min_val or val > max_val:
        errors[field] = f"{display} must be between {min_val} and {max_val}."
        return min_val
    return val


def _require_float(
    data: dict[str, Any],
    field: str,
    min_val: float,
    max_val: float,
    errors: dict[str, str],
    label: str | None = None,
) -> float:
    display = label or field
    raw = data.get(field)
    if isinstance(raw, bool) or raw is None or raw == "":
        errors[field] = f"{display} is required and must be a number."
        return min_val
    try:
        val = float(raw)
    except (TypeError, ValueError):
        errors[field] = f"{display} must be a valid number between {min_val} and {max_val}."
        return min_val
    if val < min_val or val > max_val:
        errors[field] = f"{display} must be between {min_val} and {max_val}."
        return min_val
    return round(val, 6)


def validate_auth_payload(payload: Any, is_register: bool = False) -> dict[str, Any]:
    """Validate login or registration payload."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")
    errors: dict[str, str] = {}

    email_raw = str(payload.get("email") or "").strip().lower()
    if not email_raw or len(email_raw) > 254 or not EMAIL_RE.match(email_raw):
        errors["email"] = "Enter a valid email address."

    password = payload.get("password")
    if not isinstance(password, str) or len(password) < 8 or len(password) > 128:
        errors["password"] = "Password must be between 8 and 128 characters."

    result: dict[str, Any] = {"email": email_raw, "password": password or ""}

    if is_register:
        result["display_name"] = _require_str(
            payload, "display_name", 2, 80, errors, "Display name"
        )
        role = str(payload.get("role") or "contributor").strip()
        # Self-registration only permits non-privileged community/operator roles
        if role not in ("viewer", "contributor", "operator"):
            errors["role"] = "Self-registered role must be viewer, contributor, or operator."
        result["role"] = role
        result["ai_consent_granted"] = bool(payload.get("ai_consent_granted", False))
        result["telemetry_opt_in"] = bool(payload.get("telemetry_opt_in", False))

    if errors:
        raise ValidationError("Please correct the highlighted authentication fields.", errors)
    return result


def validate_access_attributes_payload(payload: Any) -> dict[str, Any]:
    """Validate structured access attributes for a venue."""
    if not isinstance(payload, dict):
        raise ValidationError("Access attributes must be a JSON object.")
    errors: dict[str, str] = {}

    step_free = bool(payload.get("step_free_entrance", False))
    door_width = _require_int(
        payload, "entrance_door_width_cm", 40, 300, errors, "Entrance door clear width (cm)"
    )
    threshold_mm = _require_int(
        payload, "threshold_height_mm", 0, 250, errors, "Entrance threshold height (mm)"
    )

    door_opener = str(payload.get("door_opener_type") or "").strip()
    if door_opener not in DOOR_OPENER_TYPES:
        errors["door_opener_type"] = (
            f"Door opener must be one of: {', '.join(DOOR_OPENER_TYPES.keys())}."
        )

    ramp_present = bool(payload.get("ramp_present", False))
    ramp_slope: float | None = None
    if payload.get("ramp_slope_degrees") not in (None, ""):
        ramp_slope = _require_float(
            payload, "ramp_slope_degrees", 0.0, 30.0, errors, "Ramp slope (degrees)"
        )

    entrance_notes = ""
    if payload.get("entrance_notes"):
        entrance_notes = _require_str(payload, "entrance_notes", 0, 500, errors, "Entrance notes")

    restroom_type = str(payload.get("accessible_restroom_type") or "").strip()
    if restroom_type not in RESTROOM_TYPES:
        errors["accessible_restroom_type"] = (
            f"Restroom type must be one of: {', '.join(RESTROOM_TYPES.keys())}."
        )

    grab_bars = str(payload.get("grab_bars") or "none").strip()
    if grab_bars not in GRAB_BAR_TYPES:
        errors["grab_bars"] = f"Grab bars must be one of: {', '.join(GRAB_BAR_TYPES.keys())}."

    turning_circle = _require_int(
        payload, "turning_circle_cm", 0, 400, errors, "Restroom turning circle (cm)"
    )

    elevator_status = str(payload.get("elevator_status") or "none").strip()
    if elevator_status not in ELEVATOR_STATUSES:
        errors["elevator_status"] = (
            f"Elevator status must be one of: {', '.join(ELEVATOR_STATUSES.keys())}."
        )

    braille = bool(payload.get("braille_tactile_signage", False))
    hearing_loop = bool(payload.get("hearing_loop_available", False))
    quiet_space = bool(payload.get("quiet_sensory_space", False))
    parking_spaces = _require_int(
        payload, "accessible_parking_spaces", 0, 500, errors, "Accessible parking spaces"
    )

    pathway_surface = str(payload.get("pathway_surface") or "smooth_paved").strip()
    if pathway_surface not in PATHWAY_SURFACES:
        errors["pathway_surface"] = (
            f"Pathway surface must be one of: {', '.join(PATHWAY_SURFACES.keys())}."
        )

    corridor_width = _require_int(
        payload, "min_corridor_width_cm", 50, 500, errors, "Minimum interior corridor width (cm)"
    )

    lighting_level = str(payload.get("lighting_level") or "bright_even").strip()
    if lighting_level not in LIGHTING_LEVELS:
        errors["lighting_level"] = (
            f"Lighting level must be one of: {', '.join(LIGHTING_LEVELS.keys())}."
        )

    acoustic_profile = str(payload.get("acoustic_profile") or "moderate").strip()
    if acoustic_profile not in ACOUSTIC_PROFILES:
        errors["acoustic_profile"] = (
            f"Acoustic profile must be one of: {', '.join(ACOUSTIC_PROFILES.keys())}."
        )

    route_notes = ""
    if payload.get("route_notes"):
        route_notes = _require_str(payload, "route_notes", 0, 500, errors, "Interior route notes")

    if errors:
        raise ValidationError("Invalid structured access attributes.", errors)

    return {
        "step_free_entrance": step_free,
        "entrance_door_width_cm": door_width,
        "threshold_height_mm": threshold_mm,
        "door_opener_type": door_opener,
        "ramp_present": ramp_present,
        "ramp_slope_degrees": ramp_slope,
        "entrance_notes": entrance_notes,
        "accessible_restroom_type": restroom_type,
        "grab_bars": grab_bars,
        "turning_circle_cm": turning_circle,
        "elevator_status": elevator_status,
        "braille_tactile_signage": braille,
        "hearing_loop_available": hearing_loop,
        "quiet_sensory_space": quiet_space,
        "accessible_parking_spaces": parking_spaces,
        "pathway_surface": pathway_surface,
        "min_corridor_width_cm": corridor_width,
        "lighting_level": lighting_level,
        "acoustic_profile": acoustic_profile,
        "route_notes": route_notes,
    }


def validate_venue_payload(payload: Any, is_update: bool = False) -> dict[str, Any]:
    """Validate venue profile creation or update payload."""
    if not isinstance(payload, dict):
        raise ValidationError("Venue payload must be a JSON object.")
    errors: dict[str, str] = {}

    name = _require_str(payload, "name", 2, 140, errors, "Venue name")
    category = str(payload.get("category") or "").strip()
    if category not in VENUE_CATEGORIES:
        errors["category"] = f"Category must be one of: {', '.join(VENUE_CATEGORIES.keys())}."

    address = _require_str(payload, "address", 4, 220, errors, "Street address")
    city = _require_str(payload, "city", 2, 80, errors, "City")
    postal_code = _require_str(payload, "postal_code", 3, 20, errors, "Postal code")
    latitude = _require_float(payload, "latitude", -90.0, 90.0, errors, "Latitude")
    longitude = _require_float(payload, "longitude", -180.0, 180.0, errors, "Longitude")

    operating_hours = "08:00 - 20:00 Daily"
    if payload.get("operating_hours"):
        operating_hours = _require_str(
            payload, "operating_hours", 3, 160, errors, "Operating hours"
        )

    summary = _require_str(payload, "summary", 10, 1200, errors, "Accessibility summary")

    status = str(payload.get("status") or "published").strip()
    if status not in VENUE_STATUSES:
        errors["status"] = f"Status must be one of: {', '.join(VENUE_STATUSES)}."

    active_barrier_alert: str | None = None
    if payload.get("active_barrier_alert"):
        active_barrier_alert = _require_str(
            payload, "active_barrier_alert", 3, 400, errors, "Active barrier alert"
        )

    attrs_raw = payload.get("access_attributes")
    validated_attrs: dict[str, Any] | None = None
    if attrs_raw is not None or not is_update:
        try:
            validated_attrs = validate_access_attributes_payload(attrs_raw or {})
        except ValidationError as attr_err:
            for k, v in attr_err.field_errors.items():
                errors[f"access_attributes.{k}"] = v

    if errors:
        raise ValidationError("Please correct the highlighted venue profile fields.", errors)

    return {
        "name": name,
        "slug": slugify(f"{name}-{city}"),
        "category": category,
        "address": address,
        "city": city,
        "postal_code": postal_code,
        "latitude": latitude,
        "longitude": longitude,
        "operating_hours": operating_hours,
        "summary": summary,
        "status": status,
        "active_barrier_alert": active_barrier_alert,
        "access_attributes": validated_attrs,
    }


def validate_observation_payload(payload: Any) -> dict[str, Any]:
    """Validate a timestamped community/operator accessibility observation."""
    if not isinstance(payload, dict):
        raise ValidationError("Observation payload must be a JSON object.")
    errors: dict[str, str] = {}

    observer_role = str(payload.get("observer_role") or "").strip()
    if observer_role not in OBSERVER_ROLES:
        errors["observer_role"] = (
            f"Observer role must be one of: {', '.join(OBSERVER_ROLES.keys())}."
        )

    confidence_level = str(payload.get("confidence_level") or "").strip()
    if confidence_level not in CONFIDENCE_LEVELS:
        errors["confidence_level"] = (
            f"Confidence level must be one of: {', '.join(CONFIDENCE_LEVELS.keys())}."
        )

    summary = _require_str(payload, "summary", 10, 1000, errors, "Observation details")

    measured_door_width: int | None = None
    if payload.get("measured_door_width_cm") not in (None, ""):
        measured_door_width = _require_int(
            payload,
            "measured_door_width_cm",
            40,
            300,
            errors,
            "Measured entrance door width (cm)",
        )

    elevator_check: str | None = None
    if payload.get("elevator_operational_check") not in (None, ""):
        chk = str(payload.get("elevator_operational_check")).strip()
        if chk not in ("operational", "out_of_service", "not_applicable"):
            errors["elevator_operational_check"] = (
                "Elevator check must be operational, out_of_service, or not_applicable."
            )
        else:
            elevator_check = chk

    barriers_noted = ""
    if payload.get("barriers_noted"):
        barriers_noted = _require_str(
            payload, "barriers_noted", 0, 500, errors, "Barriers noted"
        )

    is_alert = bool(payload.get("is_operational_alert", False))
    if elevator_check == "out_of_service":
        is_alert = True

    if errors:
        raise ValidationError("Please correct the highlighted observation fields.", errors)

    return {
        "observer_role": observer_role,
        "confidence_level": confidence_level,
        "confidence_score": CONFIDENCE_LEVELS[confidence_level],
        "summary": summary,
        "measured_door_width_cm": measured_door_width,
        "elevator_operational_check": elevator_check,
        "barriers_noted": barriers_noted,
        "is_operational_alert": is_alert,
    }


def validate_and_scrub_photo_upload(
    metadata: dict[str, Any],
    file_bytes: bytes,
    max_bytes: int = 5 * 1024 * 1024,
) -> dict[str, Any]:
    """
    Validate photo evidence metadata and binary content:
    - Enforces explicit privacy & consent checkboxes
    - Requires descriptive screen-reader alt_text (10..300 chars)
    - Inspects magic bytes and decodes image via Pillow (rejects SVG, HTML, polyglots)
    - Strips all EXIF/GPS metadata by re-encoding clean pixel data
    """
    errors: dict[str, str] = {}

    category = str(metadata.get("category") or "").strip()
    if category not in PHOTO_CATEGORIES:
        errors["category"] = f"Photo category must be one of: {', '.join(PHOTO_CATEGORIES.keys())}."

    alt_text = _require_str(
        metadata,
        "alt_text",
        10,
        300,
        errors,
        "Screen-reader alt text (describe physical access feature)",
    )

    caption = ""
    if metadata.get("caption"):
        caption = _require_str(metadata, "caption", 0, 300, errors, "Photo caption")

    no_faces = metadata.get("no_identifiable_faces_confirmed") in (True, "true", "1", "on")
    if not no_faces:
        errors["no_identifiable_faces_confirmed"] = (
            "You must confirm the photo contains no identifiable faces or private license plates."
        )

    area_consent = metadata.get("operator_or_public_area_consent") in (True, "true", "1", "on")
    if not area_consent:
        errors["operator_or_public_area_consent"] = (
            "You must confirm the photo was taken in a public access area or with venue operator consent."
        )

    if not file_bytes or len(file_bytes) < 64:
        errors["file"] = "An image file (PNG, JPEG, or WEBP) is required."
    elif len(file_bytes) > max_bytes:
        errors["file"] = f"Image file exceeds maximum size of {max_bytes // (1024 * 1024)} MB."

    if errors:
        raise ValidationError("Photo evidence failed consent or metadata validation.", errors)

    # Reject disguised script/SVG/HTML content in header bytes
    header_sample = file_bytes[:512].lower()
    if b"<script" in header_sample or b"<svg" in header_sample or b"<!doctype html" in header_sample:
        raise ValidationError(
            "Invalid image file: executable markup or SVG is not permitted.",
            {"file": "Only binary PNG, JPEG, or WEBP images are permitted."},
        )

    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            img_format = (img.format or "").upper()
            if img_format not in ALLOWED_IMAGE_FORMATS:
                raise ValidationError(
                    "Unsupported image format.",
                    {"file": "Image must be a valid PNG, JPEG, or WEBP file."},
                )
            width, height = img.size
            if width < 16 or height < 16 or width > 8192 or height > 8192:
                raise ValidationError(
                    "Invalid image dimensions.",
                    {"file": "Image dimensions must be between 16x16 and 8192x8192 pixels."},
                )
            # Force full pixel decode to catch truncated or malformed images
            img.load()

            # Re-encode pixel data into a clean image without EXIF/GPS/XMP metadata
            clean_mode = "RGB" if img.mode not in ("RGB", "RGBA", "L") else img.mode
            if img_format == "JPEG" and clean_mode == "RGBA":
                clean_mode = "RGB"
            converted = img.convert(clean_mode)
            clean_img = Image.new(converted.mode, converted.size)
            clean_img.putdata(list(converted.getdata()))

            out_buf = io.BytesIO()
            clean_img.save(out_buf, format=img_format)
            scrubbed_bytes = out_buf.getvalue()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError(
            "Uploaded file is not a valid image.",
            {"file": f"Could not decode image content safely ({exc})."},
        ) from exc

    sha256_hash = hashlib.sha256(scrubbed_bytes).hexdigest()
    mime_type = ALLOWED_IMAGE_FORMATS[img_format]
    ext = img_format.lower()
    if ext == "jpeg":
        ext = "jpg"

    return {
        "category": category,
        "alt_text": alt_text,
        "caption": caption,
        "no_identifiable_faces_confirmed": True,
        "operator_or_public_area_consent": True,
        "mime_type": mime_type,
        "extension": ext,
        "byte_size": len(scrubbed_bytes),
        "width_px": width,
        "height_px": height,
        "sha256_hash": sha256_hash,
        "exif_stripped": True,
        "scrubbed_bytes": scrubbed_bytes,
    }


def validate_photo_review_payload(payload: Any) -> dict[str, Any]:
    """Validate moderator consent review of uploaded photo evidence."""
    if not isinstance(payload, dict):
        raise ValidationError("Review payload must be a JSON object.")
    errors: dict[str, str] = {}

    consent_status = str(payload.get("consent_status") or "").strip()
    if consent_status not in CONSENT_STATUSES:
        errors["consent_status"] = (
            f"Consent status must be one of: {', '.join(CONSENT_STATUSES)}."
        )

    review_notes = _require_str(
        payload, "review_notes", 5, 400, errors, "Moderation review notes"
    )

    if not payload.get("confirm"):
        errors["confirm"] = "Explicit confirmation (confirm: true) is required for consent review."

    if errors:
        raise ValidationError("Invalid photo consent review payload.", errors)

    return {
        "consent_status": consent_status,
        "review_notes": review_notes,
        "confirm": True,
    }


def validate_moderation_report_payload(payload: Any) -> dict[str, Any]:
    """Validate a community moderation / inaccuracy report."""
    if not isinstance(payload, dict):
        raise ValidationError("Moderation report payload must be a JSON object.")
    errors: dict[str, str] = {}

    venue_id = _require_str(payload, "venue_id", 4, 64, errors, "Venue ID")
    target_type = str(payload.get("target_type") or "venue").strip()
    if target_type not in ("venue", "observation", "photo_evidence"):
        errors["target_type"] = "Target type must be venue, observation, or photo_evidence."

    target_id = _require_str(payload, "target_id", 4, 64, errors, "Target record ID")
    reason = str(payload.get("reason") or "").strip()
    if reason not in MODERATION_REASONS:
        errors["reason"] = f"Reason must be one of: {', '.join(MODERATION_REASONS.keys())}."

    details = _require_str(payload, "details", 10, 800, errors, "Report details and evidence")

    if errors:
        raise ValidationError("Please complete all required moderation report fields.", errors)

    return {
        "venue_id": venue_id,
        "target_type": target_type,
        "target_id": target_id,
        "reason": reason,
        "details": details,
    }


def validate_moderation_resolution_payload(payload: Any) -> dict[str, Any]:
    """Validate moderator resolution of a flagged report."""
    if not isinstance(payload, dict):
        raise ValidationError("Resolution payload must be a JSON object.")
    errors: dict[str, str] = {}

    status = str(payload.get("status") or "").strip()
    if status not in MODERATION_STATUSES or status == "open":
        errors["status"] = "Resolution status must be investigating, resolved_upheld, or resolved_dismissed."

    resolution_notes = _require_str(
        payload, "resolution_notes", 8, 600, errors, "Resolution explanation"
    )

    if not payload.get("confirm"):
        errors["confirm"] = "Explicit confirmation (confirm: true) is required to resolve a report."

    if errors:
        raise ValidationError("Please provide a valid moderation status, notes, and confirmation.", errors)

    return {
        "status": status,
        "resolution_notes": resolution_notes,
        "confirm": True,
    }


def validate_saved_view_payload(payload: Any) -> dict[str, Any]:
    """Validate a user saved search view."""
    if not isinstance(payload, dict):
        raise ValidationError("Saved view payload must be a JSON object.")
    errors: dict[str, str] = {}
    name = _require_str(payload, "name", 2, 80, errors, "Saved view name")
    filters_raw = payload.get("filters")
    if not isinstance(filters_raw, dict):
        errors["filters"] = "Filters must be a JSON object."
        filters_raw = {}

    allowed_filter_keys = {
        "q",
        "category",
        "city",
        "freshness",
        "step_free",
        "min_door_width_cm",
        "accessible_restroom",
        "elevator_operational",
        "quiet_space",
        "hearing_loop",
        "braille_signage",
    }
    sanitized_filters: dict[str, Any] = {}
    for k, v in filters_raw.items():
        if k in allowed_filter_keys and v is not None and v != "":
            if isinstance(v, str):
                sanitized_filters[k] = sanitize_plain_text(v, max_len=100)
            elif isinstance(v, (bool, int, float)):
                sanitized_filters[k] = v

    if errors:
        raise ValidationError("Invalid saved view payload.", errors)
    return {"name": name, "filters": sanitized_filters}


def validate_settings_payload(payload: Any) -> dict[str, Any]:
    """Validate user privacy, notification, and optional AI consent preferences."""
    if not isinstance(payload, dict):
        raise ValidationError("Preferences payload must be a JSON object.")
    return {
        "barrier_alerts_enabled": bool(payload.get("barrier_alerts_enabled", True)),
        "stale_venue_digest_enabled": bool(payload.get("stale_venue_digest_enabled", True)),
        "moderation_updates_enabled": bool(payload.get("moderation_updates_enabled", True)),
        "ai_consent_granted": bool(payload.get("ai_consent_granted", False)),
        "telemetry_opt_in": bool(payload.get("telemetry_opt_in", False)),
    }


def validate_venue_import_payload(payload: Any) -> dict[str, Any]:
    """
    Validate an imported venue JSON payload.
    Enforces Journey B.3: user must explicitly confirm reviewed imported values before persistence.
    """
    if not isinstance(payload, dict):
        raise ValidationError("Import payload must be a JSON object.")

    if isinstance(payload.get("venue_data"), dict):
        venue_raw = payload["venue_data"]
    elif isinstance(payload.get("venue"), dict):
        venue_raw = payload["venue"]
    else:
        venue_raw = payload
    validated_venue = validate_venue_payload(venue_raw, is_update=False)

    errors: dict[str, str] = {}
    if not payload.get("user_confirmed_imported_values"):
        errors["user_confirmed_imported_values"] = (
            "You must review and explicitly confirm the imported accessibility values before saving."
        )

    source_label = "municipal-open-data-json"
    if payload.get("import_source"):
        source_label = _require_str(
            payload, "import_source", 2, 120, errors, "Import source provenance"
        )

    if errors:
        raise ValidationError("Imported venue requires human review confirmation.", errors)

    validated_venue["import_source"] = source_label
    return validated_venue


def validate_account_deletion_payload(payload: Any) -> dict[str, Any]:
    """Validate self-service account deletion/anonymization request."""
    if not isinstance(payload, dict):
        raise ValidationError("Account deletion payload must be a JSON object.")
    errors: dict[str, str] = {}
    if not payload.get("confirm"):
        errors["confirm"] = "Explicit confirmation (confirm: true) is required."
    phrase = str(payload.get("confirmation_phrase") or "").strip()
    if phrase != "DELETE MY ACCOUNT":
        errors["confirmation_phrase"] = (
            "Type 'DELETE MY ACCOUNT' exactly to confirm personal data deletion."
        )
    if errors:
        raise ValidationError("Account deletion confirmation failed.", errors)
    return {"confirm": True, "confirmation_phrase": phrase}

