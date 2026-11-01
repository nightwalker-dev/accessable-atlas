"""Optional AI Accessibility Briefing Adapter with strict consent, injection defense, and non-LLM fallback."""

from __future__ import annotations

import re
from typing import Any

from atlas.config import AtlasConfig
from atlas.domain import (
    ACOUSTIC_PROFILES,
    DOOR_OPENER_TYPES,
    ELEVATOR_STATUSES,
    LIGHTING_LEVELS,
    PATHWAY_SURFACES,
    RESTROOM_TYPES,
)

PROMPT_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(all\s+)?(previous|prior)\s+instructions|"
    r"system\s+prompt|developer\s+message|you\s+are\s+now|"
    r"reveal\s+secret|print\s+env|execute\s+command|tool_call)",
    re.IGNORECASE,
)


def scrub_untrusted_context(text: str, max_len: int = 240) -> str:
    """Neutralize prompt-injection phrases in user-submitted notes before building context."""
    if not text:
        return ""
    cleaned = PROMPT_INJECTION_PATTERNS.sub("[redacted-instruction-pattern]", text)
    return cleaned[:max_len].strip()


class AISummaryAdapter:
    """
    Optional adapter for generating structured accessibility route briefings.
    Enforces PRD Section 10:
    1. Core MVP never depends on an LLM.
    2. Requires explicit user consent before generating a briefing.
    3. Sanitizes untrusted venue/observation strings against prompt injection.
    4. Always returns a deterministic, evidence-backed briefing derived from verified attributes.
    """

    def __init__(self, config: AtlasConfig) -> None:
        self.config = config

    def generate_venue_briefing(
        self,
        venue: dict[str, Any],
        user_consent_granted: bool,
    ) -> dict[str, Any]:
        """Generate an evidence-backed accessibility briefing with provenance metadata."""
        if not user_consent_granted:
            return {
                "available": False,
                "consent_required": True,
                "provider": "none",
                "disclaimer": (
                    "Optional accessibility briefing requires explicit user consent in Settings "
                    "or on the request. All structured measurements remain directly visible below."
                ),
                "briefing_points": [],
            }

        attrs = venue.get("access_attributes") or {}
        freshness = venue.get("freshness") or {}
        observations = venue.get("observations") or []

        safe_entrance_note = scrub_untrusted_context(str(attrs.get("entrance_notes") or ""))
        safe_route_note = scrub_untrusted_context(str(attrs.get("route_notes") or ""))

        door_cm = int(attrs.get("entrance_door_width_cm") or 0)
        threshold_mm = int(attrs.get("threshold_height_mm") or 0)
        step_free = bool(attrs.get("step_free_entrance"))
        opener = DOOR_OPENER_TYPES.get(str(attrs.get("door_opener_type") or ""), "Manual door")
        restroom = RESTROOM_TYPES.get(str(attrs.get("accessible_restroom_type") or ""), "None")
        turning_cm = int(attrs.get("turning_circle_cm") or 0)
        elevator = ELEVATOR_STATUSES.get(str(attrs.get("elevator_status") or "none"), "None")
        surface = PATHWAY_SURFACES.get(str(attrs.get("pathway_surface") or ""), "Paved")
        lighting = LIGHTING_LEVELS.get(str(attrs.get("lighting_level") or ""), "Moderate")
        acoustics = ACOUSTIC_PROFILES.get(str(attrs.get("acoustic_profile") or ""), "Moderate")

        points: list[str] = [
            (
                f"Arrival & Entrance: {'Step-free entry' if step_free else 'Stepped entry'} "
                f"with {door_cm} cm clear doorway width, {threshold_mm} mm threshold, and {opener.lower()}."
                + (f" Note: {safe_entrance_note}" if safe_entrance_note else "")
            ),
            (
                f"Facilities & Transfer: {restroom} with {turning_cm} cm turning diameter; "
                f"vertical circulation: {elevator.lower()}."
            ),
            (
                f"Interior Route & Sensory Environment: {surface} pathways (min {attrs.get('min_corridor_width_cm', 120)} cm corridor), "
                f"{lighting.lower()}, and {acoustics.lower()}."
                + (f" Route note: {safe_route_note}" if safe_route_note else "")
            ),
            (
                f"Evidence Provenance: Based on {len(observations)} timestamped observation(s). "
                f"Current freshness state is '{freshness.get('label', 'Unverified')}' "
                f"({freshness.get('confidence_score', 60)}% confidence)."
            ),
        ]

        return {
            "available": True,
            "consent_required": False,
            "provider": "deterministic-attribute-synthesizer (non-LLM fallback)",
            "ai_cloud_enabled": bool(self.config.ai_enabled and self.config.ai_provider != "none"),
            "is_inferred_or_synthesized": True,
            "requires_human_verification": True,
            "disclaimer": (
                "Synthesized directly from structured venue attributes and timestamped community "
                "observations. Always verify critical measurements and active barrier alerts before travel."
            ),
            "briefing_points": points,
        }

