"""Core domain models, freshness indicators, confidence scoring, and accessibility evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ============================================================================
# Canonical Domain Taxonomies
# ============================================================================

USER_ROLES = ("viewer", "contributor", "operator", "moderator", "admin")

VENUE_CATEGORIES: dict[str, str] = {
    "transit_hub": "Transit Hub & Station",
    "civic_building": "Civic & Government Building",
    "healthcare": "Healthcare & Clinic",
    "library_museum": "Library, Museum & Cultural Space",
    "park_trail": "Park, Plaza & Trail",
    "dining_retail": "Dining & Retail",
    "education": "School & University Campus",
    "community_center": "Community & Recreation Center",
}

VENUE_STATUSES = ("published", "under_review", "archived")

DOOR_OPENER_TYPES: dict[str, str] = {
    "push_button": "Automatic Push-Button Opener",
    "motion_sensor": "Automatic Motion-Sensor Sliding/Swing Door",
    "manual_light": "Manual Door (Light Pull < 22N)",
    "manual_heavy": "Manual Door (Heavy Pull / Spring Closer)",
    "open_archway": "Open Barrier-Free Archway",
}

RESTROOM_TYPES: dict[str, str] = {
    "changing_places_hoist": "Changing Places Facility (Adult Bench + Ceiling Hoist)",
    "single_user_all_gender": "Single-User Accessible All-Gender Restroom",
    "wheelchair_stall": "Wheelchair-Accessible Multi-Stall Restroom",
    "standard_only": "Standard Restroom Only (Not Wheelchair Accessible)",
    "none": "No Public Restroom On Site",
}

GRAB_BAR_TYPES: dict[str, str] = {
    "both_sides": "Grab Bars on Both Transfer Sides (L & R)",
    "left_only": "Left-Side Transfer Grab Bar Only",
    "right_only": "Right-Side Transfer Grab Bar Only",
    "none": "No Grab Bars Installed",
}

ELEVATOR_STATUSES: dict[str, str] = {
    "operational": "Elevator / Platform Lift Operational",
    "out_of_service": "Elevator / Lift Out of Service (Barrier Alert)",
    "none": "Single-Level or No Elevator Present",
}

PATHWAY_SURFACES: dict[str, str] = {
    "smooth_paved": "Smooth Level Paving / Terrazzo",
    "tactile_paving": "Smooth Paving with Tactile Guidance Strips",
    "carpet_low_pile": "Firm Low-Pile Commercial Carpet",
    "cobblestone": "Cobblestone / Historic Pavers (Vibration Risk)",
    "gravel": "Compacted or Loose Gravel",
    "uneven": "Uneven / Cracked Surface",
}

LIGHTING_LEVELS: dict[str, str] = {
    "bright_even": "Bright, Evenly Diffused Lighting",
    "moderate": "Moderate Ambient Lighting",
    "dim": "Low / Dim Lighting",
    "glare_heavy": "High Glare / Direct Unshielded Fixtures",
}

ACOUSTIC_PROFILES: dict[str, str] = {
    "quiet": "Quiet & Acoustically Dampened (< 55 dB)",
    "moderate": "Moderate Conversational Background (55–70 dB)",
    "loud_echo": "High Reverberation / Loud Crowd Echo (> 70 dB)",
}

OBSERVER_ROLES: dict[str, str] = {
    "person_with_access_need": "Person with Lived Access Need",
    "caregiver": "Caregiver / Support Companion",
    "accessibility_advocate": "Community Accessibility Advocate",
    "venue_operator": "Verified Venue Operator",
    "auditor": "Certified Accessibility Specialist / Auditor",
}

CONFIDENCE_LEVELS: dict[str, int] = {
    "verified_measurement": 95,
    "direct_observation": 82,
    "secondhand_report": 55,
    "needs_reverification": 35,
}

CONFIDENCE_LABELS: dict[str, str] = {
    "verified_measurement": "Tape/Laser Measured on Site",
    "direct_observation": "Direct First-Hand Visit",
    "secondhand_report": "Operator or Secondary Report",
    "needs_reverification": "Uncertain / Needs Re-Check",
}

PHOTO_CATEGORIES: dict[str, str] = {
    "entrance": "Primary Entrance & Threshold",
    "restroom": "Accessible Restroom & Transfer Space",
    "ramp_lift": "Ramp, Elevator, or Platform Lift",
    "signage": "Wayfinding, Braille & High-Contrast Signage",
    "interior_route": "Interior Corridor & Turning Clearance",
    "parking": "Accessible Drop-Off & Parking Bay",
}

CONSENT_STATUSES = ("pending_review", "approved_public", "rejected_privacy")

MODERATION_REASONS: dict[str, str] = {
    "inaccurate_measurement": "Inaccurate Physical Measurement or Attribute",
    "privacy_face_visible": "Identifiable Person / License Plate in Photo",
    "outdated_barrier": "Construction or Elevator Barrier Changed",
    "operator_dispute": "Venue Operator Correction Request",
    "spam_or_abuse": "Off-Topic, Promotional, or Abusive Content",
}

MODERATION_STATUSES = ("open", "investigating", "resolved_upheld", "resolved_dismissed")

FRESHNESS_STATES = (
    "fresh_verified",
    "aging_review_soon",
    "stale_reverify",
    "active_alert",
)


# ============================================================================
# Freshness & Confidence Calculation Engine
# ============================================================================


def parse_iso_timestamp(value: str | None) -> datetime:
    """Parse an ISO-8601 timestamp into a timezone-aware UTC datetime."""
    if not value:
        return datetime.now(timezone.utc)
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def compute_freshness_indicator(
    last_observed_at: str | None,
    active_barrier_alert: str | None,
    observation_count: int,
    avg_confidence: float | None,
    elevator_status: str = "none",
    reference_now: datetime | None = None,
) -> dict[str, Any]:
    """
    Compute deterministic freshness and confidence indicators for a venue.
    Never relies on color alone: returns state slug, semantic badge label,
    distinct icon token, Sage Circuit color hex, days elapsed, and explanation.
    """
    now = reference_now or datetime.now(timezone.utc)
    observed_dt = parse_iso_timestamp(last_observed_at)
    delta_seconds = max(0.0, (now - observed_dt).total_seconds())
    days_elapsed = int(delta_seconds // 86400)

    base_conf = int(round(avg_confidence)) if avg_confidence is not None else 60
    # Boost confidence slightly when corroborated by multiple independent observations
    corroboration_bonus = min(10, max(0, (observation_count - 1) * 3))
    # Apply time decay for aging observations
    age_penalty = 0
    if days_elapsed > 90:
        age_penalty = min(30, 15 + (days_elapsed - 90) // 10)
    elif days_elapsed > 30:
        age_penalty = min(12, (days_elapsed - 30) // 5)

    effective_confidence = max(15, min(99, base_conf + corroboration_bonus - age_penalty))

    if effective_confidence >= 80:
        confidence_band = "High Confidence"
    elif effective_confidence >= 60:
        confidence_band = "Moderate Confidence"
    else:
        confidence_band = "Preliminary / Re-Verify"

    has_alert = bool(active_barrier_alert and active_barrier_alert.strip()) or (
        elevator_status == "out_of_service"
    )

    if has_alert:
        alert_reason = (
            active_barrier_alert.strip()
            if active_barrier_alert and active_barrier_alert.strip()
            else "Elevator or lift reported out of service."
        )
        return {
            "state": "active_alert",
            "label": "Active Barrier Alert",
            "short_badge": "ALERT · BARRIER REPORTED",
            "icon_token": "alert-triangle",
            "color_hex": "#FF5A0A",  # Signal Orange
            "surface_hex": "#590907",  # Deep Burgundy
            "days_since_last_observation": days_elapsed,
            "observation_count": observation_count,
            "confidence_score": effective_confidence,
            "confidence_band": confidence_band,
            "explanation": f"Active access barrier reported ({days_elapsed}d ago): {alert_reason}",
        }

    if days_elapsed <= 30 and observation_count >= 1 and effective_confidence >= 70:
        return {
            "state": "fresh_verified",
            "label": f"Fresh · Verified ({days_elapsed}d ago)",
            "short_badge": f"FRESH · {days_elapsed}D AGO",
            "icon_token": "check-shield",
            "color_hex": "#D4FF24",  # Acid Lime
            "surface_hex": "#030407",  # Midnight Black
            "days_since_last_observation": days_elapsed,
            "observation_count": observation_count,
            "confidence_score": effective_confidence,
            "confidence_band": confidence_band,
            "explanation": (
                f"Observed within the last 30 days ({days_elapsed}d ago) across "
                f"{observation_count} observation(s) with {effective_confidence}% confidence."
            ),
        }

    if days_elapsed <= 90:
        return {
            "state": "aging_review_soon",
            "label": f"Aging · Check Details ({days_elapsed}d ago)",
            "short_badge": f"AGING · {days_elapsed}D AGO",
            "icon_token": "clock-amber",
            "color_hex": "#E8D2B5",  # Warm Cream Beige
            "surface_hex": "#030407",
            "days_since_last_observation": days_elapsed,
            "observation_count": observation_count,
            "confidence_score": effective_confidence,
            "confidence_band": confidence_band,
            "explanation": (
                f"Last documented {days_elapsed} days ago ({observation_count} observation(s)). "
                "Core structural measurements remain useful, but operational status should be re-verified."
            ),
        }

    return {
        "state": "stale_reverify",
        "label": f"Stale · Re-Verification Needed ({days_elapsed}d ago)",
        "short_badge": f"STALE · {days_elapsed}D AGO",
        "icon_token": "refresh-warning",
        "color_hex": "#FF5A0A",  # Signal Orange
        "surface_hex": "#400849",  # Deep Eggplant Violet
        "days_since_last_observation": days_elapsed,
        "observation_count": observation_count,
        "confidence_score": effective_confidence,
        "confidence_band": confidence_band,
        "explanation": (
            f"Over 90 days since last observation ({days_elapsed}d ago). "
            "Community members or operators are encouraged to submit a fresh timestamped check."
        ),
    }


def evaluate_accessibility_fit(
    attributes: dict[str, Any],
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Evaluate structured access attributes and generate clear, human-readable
    highlights and potential barriers for people with access needs.
    """
    highlights: list[str] = []
    barriers: list[str] = []

    step_free = bool(attributes.get("step_free_entrance"))
    door_width = int(attributes.get("entrance_door_width_cm") or 0)
    threshold_mm = int(attributes.get("threshold_height_mm") or 0)
    opener = str(attributes.get("door_opener_type") or "")
    restroom = str(attributes.get("accessible_restroom_type") or "none")
    elevator = str(attributes.get("elevator_status") or "none")
    turning_cm = int(attributes.get("turning_circle_cm") or 0)
    braille = bool(attributes.get("braille_tactile_signage"))
    hearing_loop = bool(attributes.get("hearing_loop_available"))
    quiet_space = bool(attributes.get("quiet_sensory_space"))

    if step_free and threshold_mm <= 15:
        highlights.append(f"Step-free entrance ({door_width} cm clear width, {threshold_mm} mm threshold)")
    else:
        barriers.append(
            f"Entrance barrier: {'Step present' if not step_free else f'{threshold_mm} mm threshold'} "
            f"(door width {door_width} cm)"
        )

    if door_width < 81:
        barriers.append(f"Narrow entrance doorway ({door_width} cm < 81 cm standard wheelchair clearance)")

    if opener in ("push_button", "motion_sensor", "open_archway"):
        highlights.append(DOOR_OPENER_TYPES.get(opener, opener))
    elif opener == "manual_heavy":
        barriers.append("Heavy manual entrance door without powered opener")

    if restroom in ("changing_places_hoist", "single_user_all_gender", "wheelchair_stall"):
        highlights.append(
            f"{RESTROOM_TYPES.get(restroom, restroom)} ({turning_cm} cm turning circle)"
        )
    else:
        barriers.append("No wheelchair-accessible restroom on site")

    if elevator == "operational":
        highlights.append("Elevator / lift operational")
    elif elevator == "out_of_service":
        barriers.append("Elevator / lift currently OUT OF SERVICE")

    if braille:
        highlights.append("Braille & tactile wayfinding signage")
    if hearing_loop:
        highlights.append("Hearing loop / assistive listening system")
    if quiet_space:
        highlights.append("Dedicated quiet / low-sensory decompression space")

    matches_filters = True
    if filters:
        if filters.get("step_free") and not step_free:
            matches_filters = False
        if filters.get("min_door_width_cm"):
            if door_width < int(filters["min_door_width_cm"]):
                matches_filters = False
        if filters.get("accessible_restroom") and restroom not in (
            "changing_places_hoist",
            "single_user_all_gender",
            "wheelchair_stall",
        ):
            matches_filters = False
        if filters.get("elevator_operational") and elevator != "operational":
            matches_filters = False
        if filters.get("quiet_space") and not quiet_space:
            matches_filters = False
        if filters.get("hearing_loop") and not hearing_loop:
            matches_filters = False
        if filters.get("braille_signage") and not braille:
            matches_filters = False

    return {
        "matches_filters": matches_filters,
        "highlights": highlights,
        "barriers": barriers,
        "wheelchair_standard_met": step_free and door_width >= 82 and turning_cm >= 150,
    }

