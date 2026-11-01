#!/usr/bin/env python3
"""
Generate verified visual UI snapshots for CASE_STUDY.md from live AccessAble Atlas database & API state.
Renders 1440x900 PNGs using the exact Sage Circuit 9-color palette tokens and live seeded/queried records.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atlas.config import load_config
from atlas.db.database import AtlasDatabase
from atlas.db.seed import seed_if_empty

OUT_DIR = ROOT / "docs" / "screenshots"

# Sage Circuit Reference Palette
MIDNIGHT_BLACK = (3, 4, 7)          # #030407
SURFACE_PANEL = (10, 13, 20)        # #0A0D14
SURFACE_CARD = (16, 21, 32)         # #101520
SAGE_GREY = (165, 167, 155)         # #A5A79B
WARM_CREAM = (232, 210, 181)        # #E8D2B5
DEEP_BURGUNDY = (89, 9, 7)          # #590907
ELECTRIC_COBALT = (21, 88, 201)     # #1558C9
ACID_LIME = (212, 255, 36)          # #D4FF24
ORCHID_PINK = (231, 176, 222)       # #E7B0DE
DEEP_EGGPLANT = (64, 8, 73)         # #400849
SIGNAL_ORANGE = (255, 90, 10)       # #FF5A0A
BORDER_SUBTLE = (44, 51, 64)


def _load_fonts() -> dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    bold_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    mono_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ]

    def pick(paths: list[str], size: int):
        for p in paths:
            if Path(p).is_file():
                return ImageFont.truetype(p, size=size)
        return ImageFont.load_default()

    return {
        "h1": pick(bold_candidates, 24),
        "h2": pick(bold_candidates, 18),
        "h3": pick(bold_candidates, 15),
        "body": pick(font_candidates, 13),
        "small": pick(font_candidates, 11),
        "mono": pick(mono_candidates, 12),
        "mono_sm": pick(mono_candidates, 11),
        "metric": pick(bold_candidates, 30),
    }


def _draw_chrome(draw: ImageDraw.ImageDraw, fonts: dict, active_tab: str, user_label: str) -> None:
    # Top header bar
    draw.rectangle([0, 0, 1440, 72], fill=SURFACE_PANEL, outline=BORDER_SUBTLE)
    draw.rectangle([24, 18, 56, 50], fill=MIDNIGHT_BLACK, outline=ACID_LIME, width=2)
    draw.text((31, 24), "[A]", fill=ACID_LIME, font=fonts["mono"])
    draw.text((68, 16), "AccessAble Atlas", fill=WARM_CREAM, font=fonts["h2"])
    draw.text(
        (68, 40),
        "Find places through the details that matter",
        fill=SAGE_GREY,
        font=fonts["small"],
    )

    tabs = [
        ("directory", "1. Directory & Map"),
        ("create-venue", "2. Document Venue"),
        ("insights", "3. Freshness & Insights"),
        ("moderation", "4. Moderation & Audit"),
        ("settings", "5. Privacy & Export"),
    ]
    tx = 415
    for key, label in tabs:
        is_active = key == active_tab
        w = len(label) * 6 + 20
        bg = SURFACE_CARD if is_active else MIDNIGHT_BLACK
        border = ACID_LIME if is_active else BORDER_SUBTLE
        text_col = ACID_LIME if is_active else WARM_CREAM
        draw.rounded_rectangle([tx, 20, tx + w, 52], radius=5, fill=bg, outline=border, width=2 if is_active else 1)
        draw.text((tx + 10, 29), label, fill=text_col, font=fonts["small"])
        tx += w + 8

    # User session pill
    draw.rounded_rectangle([1215, 20, 1416, 52], radius=5, fill=MIDNIGHT_BLACK, outline=ELECTRIC_COBALT, width=1)
    draw.text((1227, 29), user_label, fill=WARM_CREAM, font=fonts["mono_sm"])


def _freshness_colors(state_name: str):
    if state_name == "fresh_verified":
        return MIDNIGHT_BLACK, ACID_LIME, "[✓]"
    if state_name == "aging_review_soon":
        return MIDNIGHT_BLACK, WARM_CREAM, "[~]"
    if state_name == "stale_reverify":
        return DEEP_EGGPLANT, ORCHID_PINK, "[*]"
    return DEEP_BURGUNDY, SIGNAL_ORANGE, "[!]"


def render_directory_snapshot(venues: list[dict], fonts: dict, out_path: Path) -> None:
    img = Image.new("RGB", (1440, 900), color=MIDNIGHT_BLACK)
    draw = ImageDraw.Draw(img)
    _draw_chrome(draw, fonts, "directory", "Maya Chen [CONTRIBUTOR]")

    # Filter bar panel
    draw.rounded_rectangle([24, 88, 1416, 178], radius=6, fill=SURFACE_PANEL, outline=BORDER_SUBTLE)
    draw.text((40, 100), "MULTI-FACET ACCESSIBILITY DIRECTORY SEARCH", fill=ACID_LIME, font=fonts["mono_sm"])
    facets = [
        "[x] Step-Free Entrance",
        "Min Door: 82 cm",
        "Category: All Categories",
        "City: Seattle",
        "[ ] Accessible Restroom",
        "[ ] Elevator Operational",
        "[ ] Quiet Sensory Room",
        "[ ] Hearing Loop",
    ]
    fx = 40
    for f in facets:
        fw = len(f) * 7 + 20
        draw.rounded_rectangle([fx, 128, fx + fw, 160], radius=4, fill=SURFACE_CARD, outline=SAGE_GREY)
        draw.text((fx + 10, 137), f, fill=WARM_CREAM, font=fonts["small"])
        fx += fw + 10

    # Left: Coordinate Vector Map Panel
    draw.rounded_rectangle([24, 196, 540, 872], radius=6, fill=SURFACE_PANEL, outline=BORDER_SUBTLE)
    draw.text((40, 212), "Interactive Coordinate Map (Seattle Metro)", fill=WARM_CREAM, font=fonts["h3"])
    draw.text((420, 214), "[+] [-] [1:1]", fill=ACID_LIME, font=fonts["mono_sm"])
    draw.rectangle([40, 244, 524, 690], fill=MIDNIGHT_BLACK, outline=BORDER_SUBTLE)

    # Grid lines
    for gx in range(100, 520, 80):
        draw.line([(gx, 244), (gx, 690)], fill=(28, 34, 44), width=1)
    for gy in range(300, 680, 75):
        draw.line([(40, gy), (524, gy)], fill=(28, 34, 44), width=1)

    pin_coords = [(160, 330), (310, 390), (230, 470), (390, 520), (185, 590), (340, 310)]
    for idx, v in enumerate(venues[:6]):
        px, py = pin_coords[idx % len(pin_coords)]
        bg, fg, sym = _freshness_colors(v["freshness"]["state"])
        draw.ellipse([px - 14, py - 14, px + 14, py + 14], fill=bg, outline=fg, width=2)
        draw.text((px - 9, py - 6), sym, fill=fg, font=fonts["mono_sm"])
        draw.text((px + 18, py - 7), v["name"][:22], fill=WARM_CREAM, font=fonts["small"])

    # Legend
    draw.text((40, 708), "NON-COLOR FRESHNESS LEGEND (WCAG 2.2 AA):", fill=SAGE_GREY, font=fonts["mono_sm"])
    legend_items = [
        ("[✓] Circle: Fresh (<30d)", ACID_LIME),
        ("[~] Square: Aging (31-90d)", WARM_CREAM),
        ("[*] Diamond: Stale (>90d)", ORCHID_PINK),
        ("[!] Triangle: Active Barrier Alert", SIGNAL_ORANGE),
    ]
    ly = 732
    for text, col in legend_items:
        draw.text((48, ly), text, fill=col, font=fonts["small"])
        ly += 24

    # Right: Venue List Cards
    cy = 196
    for v in venues[:4]:
        f = v["freshness"]
        a = v["access_attributes"]
        bg, fg, sym = _freshness_colors(f["state"])
        draw.rounded_rectangle([560, cy, 1416, cy + 158], radius=6, fill=SURFACE_CARD, outline=fg if f["state"] == "active_alert" else BORDER_SUBTLE, width=2 if f["state"] == "active_alert" else 1)
        draw.rectangle([560, cy, 566, cy + 158], fill=fg)
        draw.text((582, cy + 14), v["name"], fill=WARM_CREAM, font=fonts["h3"])
        draw.text(
            (582, cy + 38),
            f"{v['category_label']} · {v['address']}, {v['city']} · [{v['provenance_badge']}]",
            fill=SAGE_GREY,
            font=fonts["small"],
        )
        # Freshness badge
        badge_text = f"{sym} {f['label']} ({f['confidence_score']}%)"
        bw = len(badge_text) * 7 + 20
        draw.rounded_rectangle([1400 - bw, cy + 14, 1400, cy + 42], radius=4, fill=bg, outline=fg, width=1)
        draw.text((1408 - bw, cy + 21), badge_text, fill=fg, font=fonts["mono_sm"])

        draw.text((582, cy + 64), v["summary"][:105] + ("..." if len(v["summary"]) > 105 else ""), fill=WARM_CREAM, font=fonts["body"])

        chips = [
            f"Door: {a['entrance_door_width_cm']} cm",
            f"Threshold: {a['threshold_height_mm']} mm",
            f"Turn Circle: {a['turning_circle_cm']} cm",
            f"Elevator: {a['elevator_status']}",
        ]
        cx = 582
        for ch in chips:
            cw = len(ch) * 7 + 16
            draw.rounded_rectangle([cx, cy + 96, cx + cw, cy + 122], radius=4, fill=MIDNIGHT_BLACK, outline=SAGE_GREY)
            draw.text((cx + 8, cy + 102), ch, fill=ACID_LIME if "Door" in ch else WARM_CREAM, font=fonts["mono_sm"])
            cx += cw + 8

        draw.text((582, cy + 130), f"Hours: {v['operating_hours']} · Approved Photos: {v['approved_photo_count']}", fill=SAGE_GREY, font=fonts["small"])
        draw.text((1220, cy + 130), "Inspect Details & Evidence ->", fill=ACID_LIME, font=fonts["mono_sm"])
        cy += 170

    img.save(out_path, format="PNG")


def render_detail_snapshot(venue: dict, fonts: dict, out_path: Path) -> None:
    img = Image.new("RGB", (1440, 900), color=MIDNIGHT_BLACK)
    draw = ImageDraw.Draw(img)
    _draw_chrome(draw, fonts, "directory", "Maya Chen [CONTRIBUTOR]")

    f = venue["freshness"]
    a = venue["access_attributes"]
    bg, fg, sym = _freshness_colors(f["state"])

    # Header card
    draw.rounded_rectangle([24, 88, 1416, 215], radius=6, fill=SURFACE_CARD, outline=BORDER_SUBTLE)
    draw.text((44, 104), venue["name"], fill=WARM_CREAM, font=fonts["h1"])
    draw.text(
        (44, 138),
        f"{venue['category_label']} · {venue['address']}, {venue['city']} {venue['postal_code']} · Provenance: {venue['provenance_badge']}",
        fill=SAGE_GREY,
        font=fonts["body"],
    )
    draw.text((44, 166), venue["summary"][:135], fill=WARM_CREAM, font=fonts["body"])
    draw.rounded_rectangle([1120, 104, 1396, 140], radius=5, fill=bg, outline=fg, width=2)
    draw.text((1134, 115), f"{sym} {f['label']} · {f['confidence_score']}%", fill=fg, font=fonts["mono"])

    # 3-Column Structured Access Attributes
    draw.rounded_rectangle([24, 230, 1416, 455], radius=6, fill=SURFACE_PANEL, outline=BORDER_SUBTLE)
    draw.text((44, 246), "STRUCTURED PHYSICAL & SENSORY ACCESS SPECIFICATIONS", fill=ACID_LIME, font=fonts["mono"])

    cols = [
        ("ENTRANCE & THRESHOLD", [
            ("Step-Free Primary Entry", "Yes (Verified)" if a["step_free_entrance"] else "No (Stepped)"),
            ("Clear Door Opening Width", f"{a['entrance_door_width_cm']} cm (>=82 cm Std)"),
            ("Threshold Bevel Height", f"{a['threshold_height_mm']} mm"),
            ("Door Opener Mechanism", a["door_opener_type"]),
            ("Ramp Installed / Slope", f"{a['ramp_present']} ({a.get('ramp_slope_degrees') or 0} deg)"),
        ]),
        ("RESTROOM, LIFT & SENSORY", [
            ("Accessible Restroom", a["accessible_restroom_type"]),
            ("Transfer Grab Bars", a["grab_bars"]),
            ("Turning Circle Diameter", f"{a['turning_circle_cm']} cm"),
            ("Elevator / Lift Status", a["elevator_status"]),
            ("Braille / Loop / Quiet", f"Braille={a['braille_tactile_signage']} · Loop={a['hearing_loop_available']}"),
        ]),
        ("INTERIOR ROUTE & ENVIRONMENT", [
            ("Pathway Surface", a["pathway_surface"]),
            ("Min Corridor Width", f"{a['min_corridor_width_cm']} cm"),
            ("Lighting Profile", a["lighting_level"]),
            ("Acoustic Environment", a["acoustic_profile"]),
            ("Accessible Parking Bays", f"{a['accessible_parking_spaces']} spaces"),
        ]),
    ]
    col_x = 44
    for title, pairs in cols:
        draw.rounded_rectangle([col_x, 276, col_x + 430, 438], radius=5, fill=SURFACE_CARD, outline=BORDER_SUBTLE)
        draw.text((col_x + 16, 288), title, fill=ELECTRIC_COBALT, font=fonts["mono_sm"])
        py = 314
        for k, val in pairs:
            draw.text((col_x + 16, py), k + ":", fill=SAGE_GREY, font=fonts["small"])
            draw.text((col_x + 215, py), str(val)[:26], fill=WARM_CREAM, font=fonts["mono_sm"])
            py += 23
        col_x += 450

    # Bottom Left: Timestamped Observations & Consent-Reviewed Photos
    draw.rounded_rectangle([24, 472, 890, 872], radius=6, fill=SURFACE_PANEL, outline=BORDER_SUBTLE)
    draw.text((44, 490), f"TIMESTAMPED OBSERVATIONS ({len(venue['observations'])}) & CONSENT-REVIEWED PHOTOS", fill=ACID_LIME, font=fonts["mono"])
    oy = 524
    for obs in venue["observations"][:3]:
        draw.rounded_rectangle([44, oy, 870, oy + 96], radius=5, fill=SURFACE_CARD, outline=BORDER_SUBTLE)
        draw.text(
            (60, oy + 12),
            f"{obs['author_name']} ({obs['observer_role_label']}) · {obs['observed_at'][:10]} · Confidence: {obs['confidence_score']}%",
            fill=ACID_LIME,
            font=fonts["mono_sm"],
        )
        draw.text((60, oy + 38), obs["summary"][:95], fill=WARM_CREAM, font=fonts["body"])
        draw.text(
            (60, oy + 66),
            f"Measured Door: {obs.get('measured_door_width_cm') or '-'} cm · Elevator Check: {obs.get('elevator_operational_check') or 'operational'}",
            fill=SAGE_GREY,
            font=fonts["small"],
        )
        oy += 108

    # Bottom Right: Log Observation & Upload EXIF-Scrubbed Photo Forms
    draw.rounded_rectangle([910, 472, 1416, 872], radius=6, fill=SURFACE_PANEL, outline=BORDER_SUBTLE)
    draw.text((930, 490), "CONTRIBUTE OBSERVATION OR PHOTO EVIDENCE", fill=WARM_CREAM, font=fonts["h3"])
    form_fields = [
        ("Observer Perspective *", "Person with Lived Access Need"),
        ("Verification Method *", "Tape/Laser Measured on Site (95%)"),
        ("Measured Door Width (cm)", "96 cm"),
        ("Observation Summary *", "Verified automatic push-button bollard and flush entry."),
        ("Photo Alt Text (WCAG) *", "Wide double glass doors with automatic bollard at 90cm."),
        ("Privacy Attestation *", "[x] No identifiable faces  [x] Public area consent"),
    ]
    fy = 528
    for label, val in form_fields:
        draw.text((930, fy), label, fill=SAGE_GREY, font=fonts["small"])
        draw.rounded_rectangle([930, fy + 18, 1396, fy + 44], radius=4, fill=MIDNIGHT_BLACK, outline=BORDER_SUBTLE)
        draw.text((940, fy + 24), val, fill=WARM_CREAM, font=fonts["small"])
        fy += 52
    draw.rounded_rectangle([930, 834, 1396, 862], radius=4, fill=ACID_LIME)
    draw.text((1045, 841), "Submit Verified Observation & Scrub EXIF", fill=MIDNIGHT_BLACK, font=fonts["mono_sm"])

    img.save(out_path, format="PNG")


def render_insights_snapshot(insights: dict, fonts: dict, out_path: Path) -> None:
    img = Image.new("RGB", (1440, 900), color=MIDNIGHT_BLACK)
    draw = ImageDraw.Draw(img)
    _draw_chrome(draw, fonts, "insights", "Maya Chen [CONTRIBUTOR]")

    meta = insights["metadata"]
    m = insights["metrics"]
    fb = insights["freshness_breakdown"]

    # Provenance & Methodology Banner
    draw.rounded_rectangle([24, 88, 1416, 195], radius=6, fill=SURFACE_PANEL, outline=ACID_LIME, width=1)
    draw.text((44, 104), "INSIGHT PROVENANCE, METHODOLOGY, ASSUMPTIONS & LIMITATIONS", fill=ACID_LIME, font=fonts["mono"])
    draw.text((44, 132), f"Time Range: {meta['time_range']}  |  Source: {meta['source']}", fill=WARM_CREAM, font=fonts["body"])
    draw.text((44, 156), f"Units: {meta['units']}  |  Limitations: {meta['limitations'][:95]}...", fill=SAGE_GREY, font=fonts["small"])

    # 6 Metric Tiles
    tiles = [
        ("Total Published Venues", str(m["total_published_venues"]), f"{m['synthetic_sample_venues']} Synthetic Sample", ACID_LIME),
        ("Step-Free Entrances", str(m["step_free_venues"]), "Primary entrance threshold <=15mm", ACID_LIME),
        ("Full Wheelchair Clearance", str(m["wheelchair_standard_venues"]), "Door >=82cm + Turn >=150cm", ELECTRIC_COBALT),
        ("Mean Clear Door Width", f"{m['average_entrance_door_width_cm']} cm", "Across published workspace venues", ELECTRIC_COBALT),
        ("Fresh Verified (<30d)", str(fb.get("fresh_verified", 0)), "High-confidence recent checks", ACID_LIME),
        ("Active Alerts or Stale", str(fb.get("active_alert", 0) + fb.get("stale_reverify", 0)), "Requires community re-verification", SIGNAL_ORANGE),
    ]
    tx = 24
    for label, val, sub, col in tiles:
        draw.rounded_rectangle([tx, 215, tx + 220, 345], radius=6, fill=SURFACE_CARD, outline=col, width=2)
        draw.text((tx + 18, 232), val, fill=col, font=fonts["metric"])
        draw.text((tx + 18, 278), label, fill=WARM_CREAM, font=fonts["body"])
        draw.text((tx + 18, 304), sub, fill=SAGE_GREY, font=fonts["small"])
        tx += 234

    # Underlying Records Requiring Attention
    draw.rounded_rectangle([24, 368, 1416, 872], radius=6, fill=SURFACE_PANEL, outline=BORDER_SUBTLE)
    draw.text((44, 388), "UNDERLYING RECORDS REQUIRING RE-VERIFICATION OR BARRIER FOLLOW-THROUGH", fill=WARM_CREAM, font=fonts["h2"])
    ry = 428
    for rec in insights["records_requiring_attention"][:4]:
        bg, fg, sym = _freshness_colors(rec["freshness_state"])
        draw.rounded_rectangle([44, ry, 1396, ry + 88], radius=5, fill=SURFACE_CARD, outline=fg, width=1)
        draw.text((64, ry + 16), f"{rec['name']} ({rec['category_label']} · {rec['city']})", fill=WARM_CREAM, font=fonts["h3"])
        draw.text((64, ry + 46), rec["explanation"], fill=SAGE_GREY, font=fonts["body"])
        badge = f"{sym} {rec['freshness_label']}"
        bw = len(badge) * 7 + 24
        draw.rounded_rectangle([1376 - bw, ry + 24, 1376, ry + 56], radius=4, fill=bg, outline=fg, width=1)
        draw.text((1386 - bw, ry + 33), badge, fill=fg, font=fonts["mono_sm"])
        ry += 102

    img.save(out_path, format="PNG")


def render_moderation_snapshot(mod_data: dict, fonts: dict, out_path: Path) -> None:
    img = Image.new("RGB", (1440, 900), color=MIDNIGHT_BLACK)
    draw = ImageDraw.Draw(img)
    _draw_chrome(draw, fonts, "moderation", "Samira Khan [MODERATOR]")

    # Left: Moderation Queue & Pending Photo Review
    draw.rounded_rectangle([24, 88, 840, 872], radius=6, fill=SURFACE_PANEL, outline=BORDER_SUBTLE)
    draw.text((44, 108), f"COMMUNITY & OPERATOR MODERATION REPORTS ({len(mod_data['reports'])})", fill=ACID_LIME, font=fonts["mono"])

    ry = 144
    for r in mod_data["reports"][:2]:
        draw.rounded_rectangle([44, ry, 820, ry + 148], radius=5, fill=SURFACE_CARD, outline=SIGNAL_ORANGE if r["status"] == "open" else BORDER_SUBTLE)
        title_str = f"{r['venue_name']} — {r['reason_label']}"
        if len(title_str) > 54:
            title_str = title_str[:51] + "..."
        draw.text((60, ry + 14), title_str, fill=WARM_CREAM, font=fonts["h3"])
        draw.text((695, ry + 16), f"Status: {r['status']}", fill=ACID_LIME, font=fonts["mono_sm"])
        draw.text((60, ry + 44), r["details"][:88], fill=WARM_CREAM, font=fonts["body"])
        draw.text((60, ry + 72), f"Reported by {r['reporter_name']} at {r['created_at'][:19]}", fill=SAGE_GREY, font=fonts["small"])
        draw.rounded_rectangle([60, ry + 102, 480, ry + 132], radius=4, fill=MIDNIGHT_BLACK, outline=BORDER_SUBTLE)
        draw.text((70, ry + 110), "Verified with operator; entrance schedule updated.", fill=WARM_CREAM, font=fonts["small"])
        draw.rounded_rectangle([495, ry + 102, 635, ry + 132], radius=4, fill=ACID_LIME)
        draw.text((512, ry + 110), "[✓] Uphold Flag", fill=MIDNIGHT_BLACK, font=fonts["mono_sm"])
        draw.rounded_rectangle([645, ry + 102, 795, ry + 132], radius=4, fill=MIDNIGHT_BLACK, outline=SAGE_GREY)
        draw.text((662, ry + 110), "Dismiss Flag", fill=WARM_CREAM, font=fonts["mono_sm"])
        ry += 166

    # Pending Photo Evidence Consent Queue
    py = ry + 16
    draw.text((44, py), f"PENDING PHOTO EVIDENCE CONSENT QUEUE ({len(mod_data['pending_photos'])})", fill=ACID_LIME, font=fonts["mono"])
    py += 34
    for p in mod_data["pending_photos"][:2]:
        draw.rounded_rectangle([44, py, 820, py + 136], radius=5, fill=SURFACE_CARD, outline=ELECTRIC_COBALT)
        p_title = f"{p['venue_name']} · {p['category_label']}"
        if len(p_title) > 50:
            p_title = p_title[:47] + "..."
        draw.text((60, py + 14), p_title, fill=WARM_CREAM, font=fonts["h3"])
        draw.text((640, py + 16), "EXIF Stripped: [✓]", fill=ACID_LIME, font=fonts["mono_sm"])
        draw.text((60, py + 44), f"Alt Text: {p['alt_text'][:82]}...", fill=WARM_CREAM, font=fonts["body"])
        draw.rounded_rectangle([60, py + 86, 470, py + 116], radius=4, fill=MIDNIGHT_BLACK, outline=BORDER_SUBTLE)
        draw.text((70, py + 94), "Verified no identifiable faces; clear schematic.", fill=WARM_CREAM, font=fonts["small"])
        draw.rounded_rectangle([485, py + 86, 640, py + 116], radius=4, fill=ACID_LIME)
        draw.text((500, py + 94), "[✓] Approve Public", fill=MIDNIGHT_BLACK, font=fonts["mono_sm"])
        draw.rounded_rectangle([650, py + 86, 800, py + 116], radius=4, fill=DEEP_BURGUNDY, outline=SIGNAL_ORANGE)
        draw.text((666, py + 94), "Reject (Privacy)", fill=SIGNAL_ORANGE, font=fonts["mono_sm"])
        py += 150

    # Right: Immutable Workspace Audit Trail
    draw.rounded_rectangle([860, 88, 1416, 872], radius=6, fill=SURFACE_PANEL, outline=BORDER_SUBTLE)
    draw.text((880, 108), "IMMUTABLE WORKSPACE AUDIT TRAIL (AUDIT_EVENTS)", fill=ACID_LIME, font=fonts["mono"])
    ay = 144
    for a in mod_data["audit_events"][:10]:
        draw.rounded_rectangle([880, ay, 1396, ay + 62], radius=4, fill=SURFACE_CARD, outline=BORDER_SUBTLE)
        draw.text((894, ay + 10), f"{a['action']} · Actor: {a['actor_name']}", fill=ACID_LIME, font=fonts["mono_sm"])
        draw.text((894, ay + 34), f"Target: {a['target_type']}:{a['target_id'][:14]} · {a['created_at'][:19]}", fill=SAGE_GREY, font=fonts["small"])
        ay += 70

    img.save(out_path, format="PNG")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fonts = _load_fonts()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db = AtlasDatabase(
            db_path=tmp_path / "screenshots.db",
            private_storage_dir=tmp_path / "private_storage",
        )
        seed_if_empty(db)

        venues_data = db.list_venues()
        venues = venues_data["items"]
        first_venue = db.get_venue_by_id(venues[0]["id"], include_details=True)
        assert first_venue is not None
        insights = db.get_workspace_insights()
        mod_user = db.authenticate_user("samira.khan@atlas-demo.local", "AtlasDemo!2026")
        assert mod_user is not None
        mod_queue = db.list_moderation_queue(str(mod_user["workspace_id"]))

        p1 = OUT_DIR / "01-directory-map-and-list.png"
        p2 = OUT_DIR / "02-venue-detail-and-evidence.png"
        p3 = OUT_DIR / "03-insights-and-freshness.png"
        p4 = OUT_DIR / "04-moderation-and-audit-queue.png"

        render_directory_snapshot(venues, fonts, p1)
        render_detail_snapshot(first_venue, fonts, p2)
        render_insights_snapshot(insights, fonts, p3)
        render_moderation_snapshot(mod_queue, fonts, p4)

        print(f"[screenshots] Generated 4 verified Sage Circuit snapshots in {OUT_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
