"""Domain module: Moderation (modules/moderation)."""

from __future__ import annotations

from typing import Any

from atlas.auth import authorize_action
from atlas.db.database import AtlasDatabase
from atlas.domain import MODERATION_REASONS, MODERATION_STATUSES
from atlas.schemas import ModerationReportSchema, ModerationResolutionSchema

MODULE_ID = "modules/moderation"
MODULE_NAME = "Moderation"


class ModerationModule:
    """Encapsulates community inaccuracy/privacy flags, moderation queue, and resolutions."""

    module_id = MODULE_ID
    report_schema = ModerationReportSchema
    resolution_schema = ModerationResolutionSchema
    reasons = MODERATION_REASONS
    statuses = MODERATION_STATUSES

    def __init__(self, db: AtlasDatabase) -> None:
        self.db = db

    def get_queue(self, actor_user: dict[str, Any] | None) -> dict[str, Any]:
        """Authorize moderator access and return open reports, pending photos, and audit trail."""
        authorize_action(actor_user, "moderation.read_queue")
        assert actor_user is not None
        return self.db.list_moderation_queue(str(actor_user["workspace_id"]))

    def create_report(
        self,
        payload: dict[str, Any],
        reporter_user: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Validate and persist a community or operator moderation report."""
        authorize_action(reporter_user, "moderation.report")
        assert reporter_user is not None
        validated = self.report_schema.parse(payload)
        return self.db.create_moderation_report(validated, reporter_user=reporter_user)

    def resolve_report(
        self,
        report_id: str,
        payload: dict[str, Any],
        moderator_user: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Validate resolution notes, enforce confirmation, and resolve a moderation report."""
        validated = self.resolution_schema.parse(payload)
        authorize_action(
            moderator_user, "moderation.resolve", confirm=validated["confirm"]
        )
        assert moderator_user is not None
        return self.db.resolve_moderation_report(
            report_id=report_id,
            status=validated["status"],
            resolution_notes=validated["resolution_notes"],
            moderator_user=moderator_user,
        )

