"""Synthetic sample data seeder for AccessAble Atlas (explicitly labelled is_synthetic_sample=True)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
from typing import Any

from PIL import Image, ImageDraw

from atlas.db.database import AtlasDatabase
from atlas.validation import validate_and_scrub_photo_upload, validate_venue_payload


def _generate_diagram_png(
    title: str,
    subtitle: str,
    accent_rgb: tuple[int, int, int] = (212, 255, 36),
) -> bytes:
    """Generate a clean schematic diagram PNG (no faces, no EXIF) for synthetic photo evidence."""
    img = Image.new("RGB", (480, 300), color=(3, 4, 7))
    draw = ImageDraw.Draw(img)
    # Sage Circuit border and architectural grid lines
    draw.rectangle([8, 8, 471, 291], outline=(165, 167, 155), width=2)
    draw.rectangle([24, 24, 456, 76], fill=(21, 88, 201))
    draw.line([24, 180, 456, 180], fill=accent_rgb, width=3)
    draw.rectangle([60, 105, 180, 250], outline=accent_rgb, width=3)
    draw.rectangle([210, 120, 430, 250], outline=(232, 210, 181), width=2)
    draw.text((36, 42), title[:42], fill=(232, 210, 181))
    draw.text((224, 145), subtitle[:36], fill=accent_rgb)
    draw.text((224, 200), "SYNTHETIC SCHEMATIC SAMPLE", fill=(165, 167, 155))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def seed_if_empty(db: AtlasDatabase) -> dict[str, Any]:
    """Seed synthetic demo accounts, venues, observations, photos, and moderation items if empty."""
    existing = db.list_demo_accounts()
    if existing:
        return {"seeded": False, "reason": "already_populated"}

    now = datetime.now(timezone.utc)

    def days_ago_iso(days: int) -> str:
        return (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Register primary workspace users
    contributor = db.register_user(
        email="maya.chen@atlas-demo.local",
        password="AtlasDemo!2026",
        display_name="Maya Chen (Wheelchair User & Advocate)",
        role="contributor",
        ai_consent_granted=True,
        telemetry_opt_in=True,
    )
    primary_ws_id = str(contributor["workspace_id"])

    operator = db.register_user(
        email="alex.rivera@atlas-demo.local",
        password="AtlasDemo!2026",
        display_name="Alex Rivera (Civic Facilities Operator)",
        role="operator",
        workspace_id=primary_ws_id,
        ai_consent_granted=True,
        telemetry_opt_in=True,
    )

    moderator = db.register_user(
        email="samira.khan@atlas-demo.local",
        password="AtlasDemo!2026",
        display_name="Samira Khan (Accessibility Lead & Moderator)",
        role="moderator",
        workspace_id=primary_ws_id,
        ai_consent_granted=True,
        telemetry_opt_in=True,
    )

    viewer = db.register_user(
        email="jordan.lee@atlas-demo.local",
        password="AtlasDemo!2026",
        display_name="Jordan Lee (Caregiver & Route Planner)",
        role="viewer",
        workspace_id=primary_ws_id,
        ai_consent_granted=False,
        telemetry_opt_in=False,
    )

    # Secondary workspace for cross-tenant isolation testing
    with db.transaction() as conn:
        secondary_ws_id = "ws-harbor-isolated-002"
        conn.execute(
            "INSERT INTO workspaces (id, slug, name, region, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                secondary_ws_id,
                "harbor-access-guild",
                "Harborside Access Guild",
                "Coastal Bay District",
                days_ago_iso(60),
            ),
        )
    db.register_user(
        email="external.auditor@harbor-demo.local",
        password="AtlasDemo!2026",
        display_name="Devon Brooks (Harborside Chapter)",
        role="contributor",
        workspace_id=secondary_ws_id,
    )

    # 2. Seed 6 diverse, realistic venues (all marked is_synthetic_sample=True)
    sample_venues = [
        {
            "actor": operator,
            "observed_at": days_ago_iso(4),
            "payload": {
                "name": "Central Civic Library & Archive",
                "category": "library_museum",
                "address": "400 Fourth Avenue North",
                "city": "Seattle",
                "postal_code": "98104",
                "latitude": 47.6067,
                "longitude": -122.3325,
                "operating_hours": "09:00 - 20:00 Mon-Sat, 11:00 - 18:00 Sun",
                "summary": (
                    "Step-free Fourth Ave plaza entrance with dual automatic sliding doors (112 cm clear width), "
                    "Changing Places facility on Level 1 with adult hoist, tactile floor guidance to elevators, "
                    "and an acoustically dampened sensory reading room on Level 3."
                ),
                "status": "published",
                "active_barrier_alert": None,
                "access_attributes": {
                    "step_free_entrance": True,
                    "entrance_door_width_cm": 112,
                    "threshold_height_mm": 0,
                    "door_opener_type": "motion_sensor",
                    "ramp_present": True,
                    "ramp_slope_degrees": 2.4,
                    "entrance_notes": "Flush plaza threshold at Fourth Ave entrance; tactile warning pavers lead directly to main desk.",
                    "accessible_restroom_type": "changing_places_hoist",
                    "grab_bars": "both_sides",
                    "turning_circle_cm": 210,
                    "elevator_status": "operational",
                    "braille_tactile_signage": True,
                    "hearing_loop_available": True,
                    "quiet_sensory_space": True,
                    "accessible_parking_spaces": 6,
                    "pathway_surface": "tactile_paving",
                    "min_corridor_width_cm": 180,
                    "lighting_level": "bright_even",
                    "acoustic_profile": "quiet",
                    "route_notes": "All 5 public floors connected via dual wide-cab elevators (140 cm door opening).",
                },
            },
        },
        {
            "actor": contributor,
            "observed_at": days_ago_iso(2),
            "payload": {
                "name": "Pioneer Square Transit Station (North Concourse)",
                "category": "transit_hub",
                "address": "301 Yesler Way",
                "city": "Seattle",
                "postal_code": "98104",
                "latitude": 47.6021,
                "longitude": -122.3312,
                "operating_hours": "05:00 - 01:00 Daily",
                "summary": (
                    "Underground light-rail and bus transfer hub. Street-to-mezzanine elevator is currently "
                    "OUT OF SERVICE for hydraulic cylinder replacement; step-free reroute requires boarding at "
                    "University Street Station 550 meters north."
                ),
                "status": "published",
                "active_barrier_alert": (
                    "North street-to-platform elevator #42 out of service since yesterday; use University St Station for step-free access."
                ),
                "access_attributes": {
                    "step_free_entrance": True,
                    "entrance_door_width_cm": 105,
                    "threshold_height_mm": 4,
                    "door_opener_type": "open_archway",
                    "ramp_present": True,
                    "ramp_slope_degrees": 4.1,
                    "entrance_notes": "North plaza entry is flush, but vertical lift to platform is temporarily offline.",
                    "accessible_restroom_type": "none",
                    "grab_bars": "none",
                    "turning_circle_cm": 160,
                    "elevator_status": "out_of_service",
                    "braille_tactile_signage": True,
                    "hearing_loop_available": True,
                    "quiet_sensory_space": False,
                    "accessible_parking_spaces": 2,
                    "pathway_surface": "tactile_paving",
                    "min_corridor_width_cm": 220,
                    "lighting_level": "bright_even",
                    "acoustic_profile": "loud_echo",
                    "route_notes": "High train announcement reverberation; visual digital readerboards installed on both platforms.",
                },
            },
        },
        {
            "actor": operator,
            "observed_at": days_ago_iso(11),
            "payload": {
                "name": "Cascade Community Health & Mobility Clinic",
                "category": "healthcare",
                "address": "1220 East Madison Street",
                "city": "Seattle",
                "postal_code": "98122",
                "latitude": 47.6134,
                "longitude": -122.3160,
                "operating_hours": "07:30 - 19:00 Mon-Fri, 08:30 - 15:00 Sat",
                "summary": (
                    "Outpatient rehabilitation and primary care center with covered accessible van drop-off, "
                    "push-button entry doors (96 cm clearance), height-adjustable exam tables, and low-glare "
                    "sensory waiting alcoves."
                ),
                "status": "published",
                "active_barrier_alert": None,
                "access_attributes": {
                    "step_free_entrance": True,
                    "entrance_door_width_cm": 96,
                    "threshold_height_mm": 2,
                    "door_opener_type": "push_button",
                    "ramp_present": True,
                    "ramp_slope_degrees": 1.8,
                    "entrance_notes": "Covered canopy curb cut at East Madison pull-in bay with high-contrast bollard push pads.",
                    "accessible_restroom_type": "single_user_all_gender",
                    "grab_bars": "both_sides",
                    "turning_circle_cm": 185,
                    "elevator_status": "operational",
                    "braille_tactile_signage": True,
                    "hearing_loop_available": True,
                    "quiet_sensory_space": True,
                    "accessible_parking_spaces": 8,
                    "pathway_surface": "smooth_paved",
                    "min_corridor_width_cm": 165,
                    "lighting_level": "moderate",
                    "acoustic_profile": "quiet",
                    "route_notes": "Check-in counter includes 76 cm lowered knee-clearance section and portable induction loop.",
                },
            },
        },
        {
            "actor": contributor,
            "observed_at": days_ago_iso(52),
            "payload": {
                "name": "Elliott Bay Waterfront Conservatory & Pavilion",
                "category": "park_trail",
                "address": "1401 Alaskan Way Pier 62",
                "city": "Seattle",
                "postal_code": "98101",
                "latitude": 47.6082,
                "longitude": -122.3418,
                "operating_hours": "06:00 - 22:00 Daily",
                "summary": (
                    "Boardwalk promenade and glass botanical pavilion. Step-free shoreline deck with 180 cm "
                    "passing lanes and single-user wheelchair restroom; last verified 52 days ago prior to "
                    "seasonal planter reconfiguration."
                ),
                "status": "published",
                "active_barrier_alert": None,
                "access_attributes": {
                    "step_free_entrance": True,
                    "entrance_door_width_cm": 92,
                    "threshold_height_mm": 8,
                    "door_opener_type": "push_button",
                    "ramp_present": True,
                    "ramp_slope_degrees": 3.2,
                    "entrance_notes": "8 mm beveled timber-to-concrete transition strip at pier apron.",
                    "accessible_restroom_type": "single_user_all_gender",
                    "grab_bars": "both_sides",
                    "turning_circle_cm": 160,
                    "elevator_status": "none",
                    "braille_tactile_signage": False,
                    "hearing_loop_available": False,
                    "quiet_sensory_space": True,
                    "accessible_parking_spaces": 4,
                    "pathway_surface": "smooth_paved",
                    "min_corridor_width_cm": 180,
                    "lighting_level": "bright_even",
                    "acoustic_profile": "moderate",
                    "route_notes": "Single-level pier deck with seated rest benches every 45 meters.",
                },
            },
        },
        {
            "actor": contributor,
            "observed_at": days_ago_iso(118),
            "payload": {
                "name": "Old Town Brickworks Roastery & Study Hall",
                "category": "dining_retail",
                "address": "214 Occidental Avenue South",
                "city": "Seattle",
                "postal_code": "98104",
                "latitude": 47.6003,
                "longitude": -122.3331,
                "operating_hours": "07:00 - 18:00 Daily",
                "summary": (
                    "Historic timber-and-brick cafe. Main Occidental Ave entrance has a 95 mm masonry step "
                    "and manual spring door (78 cm width). Portable aluminum ramp available on request via "
                    "doorbell, but restroom stall lacks transfer grab bars."
                ),
                "status": "published",
                "active_barrier_alert": None,
                "access_attributes": {
                    "step_free_entrance": False,
                    "entrance_door_width_cm": 78,
                    "threshold_height_mm": 95,
                    "door_opener_type": "manual_heavy",
                    "ramp_present": False,
                    "ramp_slope_degrees": None,
                    "entrance_notes": "9.5 cm step at front threshold; 78 cm doorway is narrower than standard power-chair clearance.",
                    "accessible_restroom_type": "standard_only",
                    "grab_bars": "none",
                    "turning_circle_cm": 105,
                    "elevator_status": "none",
                    "braille_tactile_signage": False,
                    "hearing_loop_available": False,
                    "quiet_sensory_space": False,
                    "accessible_parking_spaces": 0,
                    "pathway_surface": "cobblestone",
                    "min_corridor_width_cm": 95,
                    "lighting_level": "dim",
                    "acoustic_profile": "loud_echo",
                    "route_notes": "Exterior approach crosses historic cobblestone pedestrian mall.",
                },
            },
        },
        {
            "actor": operator,
            "observed_at": days_ago_iso(9),
            "payload": {
                "name": "Rainier Valley Civic Maker & Advocacy Hub",
                "category": "community_center",
                "address": "4820 Rainier Avenue South",
                "city": "Seattle",
                "postal_code": "98118",
                "latitude": 47.5588,
                "longitude": -122.2850,
                "operating_hours": "08:30 - 21:00 Mon-Sat",
                "summary": (
                    "Single-story universal-design community hall with motion-activated 108 cm doors, "
                    "ASL-friendly circular meeting lighting, hearing loop in auditorium, and dedicated "
                    "low-stimulation sensory room."
                ),
                "status": "published",
                "active_barrier_alert": None,
                "access_attributes": {
                    "step_free_entrance": True,
                    "entrance_door_width_cm": 108,
                    "threshold_height_mm": 0,
                    "door_opener_type": "motion_sensor",
                    "ramp_present": True,
                    "ramp_slope_degrees": 1.5,
                    "entrance_notes": "Zero-step entry with high-contrast Acid Lime threshold guidance stripe.",
                    "accessible_restroom_type": "single_user_all_gender",
                    "grab_bars": "both_sides",
                    "turning_circle_cm": 195,
                    "elevator_status": "none",
                    "braille_tactile_signage": True,
                    "hearing_loop_available": True,
                    "quiet_sensory_space": True,
                    "accessible_parking_spaces": 5,
                    "pathway_surface": "smooth_paved",
                    "min_corridor_width_cm": 190,
                    "lighting_level": "bright_even",
                    "acoustic_profile": "quiet",
                    "route_notes": "All workshops on ground level with adjustable-height workbenches (68–92 cm).",
                },
            },
        },
    ]

    created_venues: list[dict[str, Any]] = []
    for item in sample_venues:
        validated = validate_venue_payload(item["payload"])
        v = db.create_venue(
            validated_data=validated,
            actor_user=item["actor"],
            is_synthetic_sample=True,
            observed_at_override=item["observed_at"],
        )
        created_venues.append(v)

    # 3. Add corroborating second observations on the first two venues
    library_venue = created_venues[0]
    db.create_observation(
        venue_id=library_venue["id"],
        validated_obs={
            "observer_role": "person_with_access_need",
            "confidence_level": "verified_measurement",
            "confidence_score": 95,
            "summary": (
                "Confirmed 112 cm clear opening at Fourth Ave sliding doors with laser measure. "
                "Level 1 Changing Places ceiling hoist tested operational and spotless."
            ),
            "measured_door_width_cm": 112,
            "elevator_operational_check": "operational",
            "barriers_noted": "",
            "is_operational_alert": False,
        },
        actor_user=contributor,
        observed_at_override=days_ago_iso(3),
        is_synthetic_sample=True,
    )

    # 4. Seed consent-reviewed schematic photo evidence (1 approved_public, 1 pending_review)
    approved_png = _generate_diagram_png(
        "Central Library Entrance (112cm)",
        "Step-Free Motion Door + Tactile Path",
        accent_rgb=(212, 255, 36),
    )
    validated_photo_1 = validate_and_scrub_photo_upload(
        metadata={
            "category": "entrance",
            "alt_text": "Architectural schematic of Central Civic Library Fourth Ave step-free sliding entrance measuring 112 cm wide with tactile guidance paving.",
            "caption": "Fourth Ave step-free entrance clearance (112 cm) — Synthetic Sample Diagram",
            "no_identifiable_faces_confirmed": True,
            "operator_or_public_area_consent": True,
        },
        file_bytes=approved_png,
    )
    db.create_photo_evidence(
        venue_id=library_venue["id"],
        validated_photo=validated_photo_1,
        actor_user=operator,
        auto_approve=True,
        is_synthetic_sample=True,
    )

    pending_png = _generate_diagram_png(
        "Pioneer Sq Elevator #42 Outage",
        "Temporary Maintenance Barrier Notice",
        accent_rgb=(255, 90, 10),
    )
    validated_photo_2 = validate_and_scrub_photo_upload(
        metadata={
            "category": "ramp_lift",
            "alt_text": "Schematic diagram showing North Concourse Elevator 42 out-of-service barricade and 550m detour arrow to University Street Station.",
            "caption": "Elevator #42 hydraulic maintenance notice — awaiting moderator consent check",
            "no_identifiable_faces_confirmed": True,
            "operator_or_public_area_consent": True,
        },
        file_bytes=pending_png,
    )
    db.create_photo_evidence(
        venue_id=created_venues[1]["id"],
        validated_photo=validated_photo_2,
        actor_user=contributor,
        auto_approve=False,
        is_synthetic_sample=True,
    )

    # 5. Seed an open moderation report for the Moderation workflow
    brickworks = created_venues[4]
    db.create_moderation_report(
        validated_report={
            "venue_id": brickworks["id"],
            "target_type": "venue",
            "target_id": brickworks["id"],
            "reason": "outdated_barrier",
            "details": (
                "Operator reported that a permanent bevelled threshold ramp is scheduled for installation "
                "at the Occidental Ave side door; requesting moderator re-verification of entrance width."
            ),
        },
        reporter_user=contributor,
    )

    # 6. Seed a default saved view for Maya Chen
    db.create_saved_view(
        user=contributor,
        name="Step-Free + Accessible Restroom + Quiet Space",
        filters={
            "step_free": True,
            "accessible_restroom": True,
            "quiet_space": True,
        },
    )

    return {"seeded": True, "venue_count": len(created_venues)}

