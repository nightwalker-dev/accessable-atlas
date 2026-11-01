"""Domain module: Venue profiles (modules/venue-profiles)."""

from __future__ import annotations

from typing import Any

from atlas.auth import authorize_action
from atlas.db.database import AtlasDatabase
from atlas.domain import VENUE_CATEGORIES, VENUE_STATUSES
from atlas.schemas import VenueImportSchema, VenueProfileSchema

MODULE_ID = "modules/venue-profiles"
MODULE_NAME = "Venue profiles"


class VenueProfilesModule:
    """Encapsulates venue lifecycle, schema validation, RBAC, and confirmed JSON import."""

    module_id = MODULE_ID
    schema = VenueProfileSchema
    import_schema = VenueImportSchema
    categories = VENUE_CATEGORIES
    statuses = VENUE_STATUSES

    def __init__(self, db: AtlasDatabase) -> None:
        self.db = db

    def get_venue(
        self,
        venue_id: str,
        viewer_user: dict[str, Any] | None = None,
        include_details: bool = True,
    ) -> dict[str, Any]:
        """Retrieve a single venue profile with access attributes, observations, and photos."""
        venue = self.db.get_venue_by_id(
            venue_id, viewer_user=viewer_user, include_details=include_details
        )
        if not venue:
            raise LookupError("Venue profile not found or access restricted.")
        return venue

    def create_venue(
        self,
        payload: dict[str, Any],
        actor_user: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Validate boundary schema, authorize 'venue.create', and persist a new venue."""
        authorize_action(actor_user, "venue.create")
        assert actor_user is not None
        validated = self.schema.parse(payload, is_update=False)
        return self.db.create_venue(
            validated_data=validated,
            actor_user=actor_user,
            is_synthetic_sample=False,
        )

    def update_venue(
        self,
        venue_id: str,
        payload: dict[str, Any],
        actor_user: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Validate boundary schema, authorize ownership/workspace scope, and update a venue."""
        existing = self.db.get_venue_by_id(
            venue_id, viewer_user=actor_user, include_details=False
        )
        if not existing:
            raise LookupError("Venue profile not found.")
        authorize_action(actor_user, "venue.update", resource=existing)
        assert actor_user is not None
        validated = self.schema.parse(payload, is_update=True)
        return self.db.update_venue(venue_id, validated, actor_user=actor_user)

    def archive_venue(
        self,
        venue_id: str,
        actor_user: dict[str, Any] | None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Soft-archive a venue profile after explicit confirmation and ownership/moderator check."""
        existing = self.db.get_venue_by_id(
            venue_id, viewer_user=actor_user, include_details=False
        )
        if not existing:
            raise LookupError("Venue profile not found.")
        authorize_action(actor_user, "venue.archive", resource=existing, confirm=confirm)
        assert actor_user is not None
        return self.db.archive_venue(venue_id, actor_user=actor_user)

    def delete_venue(
        self,
        venue_id: str,
        actor_user: dict[str, Any] | None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Permanently delete a venue profile after explicit confirmation and authorization."""
        existing = self.db.get_venue_by_id(
            venue_id, viewer_user=actor_user, include_details=False
        )
        if not existing:
            raise LookupError("Venue profile not found.")
        authorize_action(actor_user, "venue.delete", resource=existing, confirm=confirm)
        assert actor_user is not None
        self.db.delete_venue(venue_id, actor_user=actor_user)
        return {"deleted": True, "venue_id": venue_id}

    def import_venue(
        self,
        payload: dict[str, Any],
        actor_user: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Validate and persist a human-confirmed municipal/audit JSON venue import."""
        authorize_action(actor_user, "venue.create")
        assert actor_user is not None
        validated = self.import_schema.parse(payload)
        return self.db.import_venue(validated_data=validated, actor_user=actor_user)

