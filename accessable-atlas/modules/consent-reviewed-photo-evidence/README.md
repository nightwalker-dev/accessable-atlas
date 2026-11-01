# Module: Consent-Reviewed Photo Evidence (`modules/consent-reviewed-photo-evidence`)

## Purpose
Enforces privacy-safe photo uploads (`photo_evidence` table + `data/private_storage/`), requiring explicit uploader consent checkboxes (`no_identifiable_faces_confirmed`, `operator_or_public_area_consent`), descriptive screen-reader `alt_text`, Pillow pixel re-encoding to strip 100% of EXIF GPS/camera metadata, and moderator review (`pending_review` → `approved_public` / `rejected_privacy`).

## Boundary Contracts
- **Upload Schema:** [`PhotoEvidenceUploadSchema`](../../atlas/schemas.py)
- **Review Schema:** [`PhotoReviewSchema`](../../atlas/schemas.py)
- **Authorization Actions:** `photo.upload`, `photo.read`, `photo.review` (`confirm=true`)
- **Database Table:** `public.photo_evidence`

