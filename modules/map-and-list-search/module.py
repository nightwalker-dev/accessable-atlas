"""Domain module: Map and list search (modules/map-and-list-search)."""

from __future__ import annotations

from typing import Any

from atlas.auth import authorize_action
from atlas.db.database import AtlasDatabase
from atlas.schemas import MapAndListSearchFilterSchema, SavedViewSchema

MODULE_ID = "modules/map-and-list-search"
MODULE_NAME = "Map and list search"


class MapAndListSearchModule:
    """Encapsulates single-query LEFT JOIN multi-facet venue search and saved filter views."""

    module_id = MODULE_ID
    filter_schema = MapAndListSearchFilterSchema
    saved_view_schema = SavedViewSchema

    def __init__(self, db: AtlasDatabase) -> None:
        self.db = db

    def search_venues(
        self,
        raw_query_params: dict[str, Any],
        viewer_user: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate search parameters at the boundary and execute single-query SQL search."""
        validated = self.filter_schema.parse(raw_query_params)
        limit = int(validated.pop("limit", 50))
        offset = int(validated.pop("offset", 0))
        return self.db.list_venues(
            filters=validated,
            viewer_user=viewer_user,
            limit=limit,
            offset=offset,
        )

    def list_saved_views(self, actor_user: dict[str, Any] | None) -> list[dict[str, Any]]:
        """List saved search filter presets owned by the authenticated user."""
        authorize_action(actor_user, "saved_view.manage")
        assert actor_user is not None
        return self.db.list_saved_views(str(actor_user["id"]))

    def create_saved_view(
        self,
        payload: dict[str, Any],
        actor_user: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Validate and persist a named search filter view for the authenticated user."""
        authorize_action(actor_user, "saved_view.manage")
        assert actor_user is not None
        validated = self.saved_view_schema.parse(payload)
        return self.db.create_saved_view(
            user=actor_user,
            name=validated["name"],
            filters=validated["filters"],
        )

    def delete_saved_view(
        self,
        view_id: str,
        actor_user: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Verify ownership and delete a saved search view."""
        existing = self.db.get_saved_view_by_id(view_id)
        if not existing:
            raise LookupError("Saved view not found.")
        authorize_action(actor_user, "saved_view.manage", resource=existing)
        self.db.delete_saved_view(view_id)
        return {"deleted": True, "id": view_id}

