"""Domain module: Timestamped observations (modules/timestamped-observations)."""

from __future__ import annotations

from typing import Any

from atlas.auth import authorize_action
from atlas.db.database import AtlasDatabase
from atlas.domain import CONFIDENCE_LABELS, CONFIDENCE_LEVELS, OBSERVER_ROLES
from atlas.schemas import TimestampedObservationSchema

MODULE_ID = "modules/timestamped-observations"
MODULE_NAME = "Timestamped observations"


class TimestampedObservationsModule:
    """Encapsulates timestamped field observations, confidence tiers, and barrier propagation."""

    module_id = MODULE_ID
    schema = TimestampedObservationSchema
    observer_roles = OBSERVER_ROLES
    confidence_levels = CONFIDENCE_LEVELS
    confidence_labels = CONFIDENCE_LABELS

    def __init__(self, db: AtlasDatabase) -> None:
        self.db = db

    def log_observation(
        self,
        venue_id: str,
        payload: dict[str, Any],
        actor_user: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Validate observation payload, verify authorization, and persist with venue state sync."""
        existing = self.db.get_venue_by_id(
            venue_id, viewer_user=actor_user, include_details=False
        )
        if not existing:
            raise LookupError("Target venue profile not found.")
        authorize_action(actor_user, "observation.create", resource=existing)
        assert actor_user is not None

        validated = self.schema.parse(payload)
        observation = self.db.create_observation(
            venue_id=venue_id,
            validated_obs=validated,
            actor_user=actor_user,
            is_synthetic_sample=False,
        )
        refreshed_venue = self.db.get_venue_by_id(
            venue_id, viewer_user=actor_user, include_details=True
        )
        assert refreshed_venue is not None
        return {"observation": observation, "venue": refreshed_venue}

