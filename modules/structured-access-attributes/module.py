"""Domain module: Structured access attributes (modules/structured-access-attributes)."""

from __future__ import annotations

from typing import Any

from atlas.domain import (
    ACOUSTIC_PROFILES,
    DOOR_OPENER_TYPES,
    ELEVATOR_STATUSES,
    GRAB_BAR_TYPES,
    LIGHTING_LEVELS,
    PATHWAY_SURFACES,
    RESTROOM_TYPES,
    evaluate_accessibility_fit,
)
from atlas.schemas import StructuredAccessAttributesSchema

MODULE_ID = "modules/structured-access-attributes"
MODULE_NAME = "Structured access attributes"


class StructuredAccessAttributesModule:
    """Encapsulates physical entrance, facility, and interior route attributes and fit scoring."""

    module_id = MODULE_ID
    schema = StructuredAccessAttributesSchema
    taxonomies = {
        "door_opener_types": DOOR_OPENER_TYPES,
        "restroom_types": RESTROOM_TYPES,
        "grab_bar_types": GRAB_BAR_TYPES,
        "elevator_statuses": ELEVATOR_STATUSES,
        "pathway_surfaces": PATHWAY_SURFACES,
        "lighting_levels": LIGHTING_LEVELS,
        "acoustic_profiles": ACOUSTIC_PROFILES,
    }

    def validate(self, payload: Any) -> dict[str, Any]:
        """Validate structured access attributes against numeric bounds and enums."""
        return self.schema.parse(payload)

    def evaluate_fit(
        self,
        attributes: dict[str, Any],
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Evaluate personal accessibility fit, matched features, and barrier warnings."""
        return evaluate_accessibility_fit(attributes, filters=filters)
