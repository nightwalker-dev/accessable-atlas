"""Domain module: Consent-reviewed photo evidence (modules/consent-reviewed-photo-evidence)."""

from __future__ import annotations

from typing import Any

from atlas.auth import authorize_action
from atlas.db.database import AtlasDatabase
from atlas.domain import CONSENT_STATUSES, PHOTO_CATEGORIES
from atlas.schemas import PhotoEvidenceUploadSchema, PhotoReviewSchema

MODULE_ID = "modules/consent-reviewed-photo-evidence"
MODULE_NAME = "Consent-reviewed photo evidence"


class ConsentReviewedPhotoEvidenceModule:
    """Encapsulates photo upload consent attestations, Pillow EXIF scrubbing, and moderator review."""

    module_id = MODULE_ID
    upload_schema = PhotoEvidenceUploadSchema
    review_schema = PhotoReviewSchema
    categories = PHOTO_CATEGORIES
    consent_statuses = CONSENT_STATUSES

    def __init__(self, db: AtlasDatabase) -> None:
        self.db = db

    def upload_photo(
        self,
        venue_id: str,
        metadata: dict[str, Any],
        file_bytes: bytes,
        actor_user: dict[str, Any] | None,
        max_bytes: int = 5242880,
    ) -> dict[str, Any]:
        """Validate consent checkboxes, scrub EXIF via Pillow, and persist photo evidence."""
        existing = self.db.get_venue_by_id(
            venue_id, viewer_user=actor_user, include_details=False
        )
        if not existing:
            raise LookupError("Target venue profile not found.")
        authorize_action(actor_user, "photo.upload", resource=existing)
        assert actor_user is not None

        validated_photo = self.upload_schema.parse(
            metadata, file_bytes=file_bytes, max_bytes=max_bytes
        )
        photo = self.db.create_photo_evidence(
            venue_id=venue_id,
            validated_photo=validated_photo,
            actor_user=actor_user,
            is_synthetic_sample=False,
        )
        refreshed_venue = self.db.get_venue_by_id(
            venue_id, viewer_user=actor_user, include_details=True
        )
        return {"photo": photo, "venue": refreshed_venue}

    def read_photo_file(
        self,
        photo_id: str,
        viewer_user: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], bytes]:
        """Authorize access to a photo evidence binary file and return (record, bytes)."""
        found = self.db.get_photo_record_and_bytes(photo_id)
        if not found:
            raise LookupError("Photo evidence file not found.")
        record, raw_bytes = found
        if record["consent_status"] != "approved_public":
            authorize_action(viewer_user, "photo.read", resource=record)
        return record, raw_bytes

    def review_photo_consent(
        self,
        photo_id: str,
        payload: dict[str, Any],
        moderator_user: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Approve or reject uploaded photo evidence after moderator confirmation."""
        validated = self.review_schema.parse(payload)
        authorize_action(moderator_user, "photo.review", confirm=validated["confirm"])
        assert moderator_user is not None
        return self.db.review_photo_consent(
            photo_id=photo_id,
            consent_status=validated["consent_status"],
            review_notes=validated["review_notes"],
            moderator_user=moderator_user,
        )

