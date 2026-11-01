"""Transactional SQLite repository mirroring the canonical Supabase PostgreSQL schema."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterator
import uuid

from atlas.auth import hash_password, verify_password
from atlas.domain import (
    CONFIDENCE_LABELS,
    MODERATION_REASONS,
    OBSERVER_ROLES,
    PHOTO_CATEGORIES,
    VENUE_CATEGORIES,
    compute_freshness_indicator,
    evaluate_accessibility_fit,
)


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


SCHEMA_DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('viewer', 'contributor', 'operator', 'moderator', 'admin')),
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    ai_consent_granted INTEGER NOT NULL DEFAULT 0,
    telemetry_opt_in INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS venues (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    created_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    address TEXT NOT NULL,
    city TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    operating_hours TEXT NOT NULL,
    operator_verified INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('published', 'under_review', 'archived')),
    active_barrier_alert TEXT DEFAULT NULL,
    is_synthetic_sample INTEGER NOT NULL DEFAULT 0,
    last_observed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_venues_workspace_status ON venues(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_venues_category_city ON venues(category, city);

CREATE TABLE IF NOT EXISTS access_attributes (
    venue_id TEXT PRIMARY KEY REFERENCES venues(id) ON DELETE CASCADE,
    step_free_entrance INTEGER NOT NULL DEFAULT 0,
    entrance_door_width_cm INTEGER NOT NULL,
    threshold_height_mm INTEGER NOT NULL DEFAULT 0,
    door_opener_type TEXT NOT NULL,
    ramp_present INTEGER NOT NULL DEFAULT 0,
    ramp_slope_degrees REAL DEFAULT NULL,
    entrance_notes TEXT NOT NULL DEFAULT '',
    accessible_restroom_type TEXT NOT NULL,
    grab_bars TEXT NOT NULL DEFAULT 'none',
    turning_circle_cm INTEGER NOT NULL DEFAULT 150,
    elevator_status TEXT NOT NULL DEFAULT 'none',
    braille_tactile_signage INTEGER NOT NULL DEFAULT 0,
    hearing_loop_available INTEGER NOT NULL DEFAULT 0,
    quiet_sensory_space INTEGER NOT NULL DEFAULT 0,
    accessible_parking_spaces INTEGER NOT NULL DEFAULT 0,
    pathway_surface TEXT NOT NULL DEFAULT 'smooth_paved',
    min_corridor_width_cm INTEGER NOT NULL DEFAULT 120,
    lighting_level TEXT NOT NULL DEFAULT 'bright_even',
    acoustic_profile TEXT NOT NULL DEFAULT 'moderate',
    route_notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_access_attributes_filter
    ON access_attributes(step_free_entrance, entrance_door_width_cm, accessible_restroom_type, elevator_status);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    venue_id TEXT NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
    author_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    observer_role TEXT NOT NULL,
    confidence_level TEXT NOT NULL,
    confidence_score INTEGER NOT NULL,
    summary TEXT NOT NULL,
    measured_door_width_cm INTEGER DEFAULT NULL,
    elevator_operational_check TEXT DEFAULT NULL,
    barriers_noted TEXT NOT NULL DEFAULT '',
    is_operational_alert INTEGER NOT NULL DEFAULT 0,
    is_synthetic_sample INTEGER NOT NULL DEFAULT 0,
    observed_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_observations_venue_observed ON observations(venue_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS photo_evidence (
    id TEXT PRIMARY KEY,
    venue_id TEXT NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
    observation_id TEXT REFERENCES observations(id) ON DELETE SET NULL,
    uploaded_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    category TEXT NOT NULL,
    alt_text TEXT NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    storage_key TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    width_px INTEGER NOT NULL,
    height_px INTEGER NOT NULL,
    sha256_hash TEXT NOT NULL,
    exif_stripped INTEGER NOT NULL DEFAULT 1,
    no_identifiable_faces_confirmed INTEGER NOT NULL DEFAULT 1,
    operator_or_public_area_consent INTEGER NOT NULL DEFAULT 1,
    consent_status TEXT NOT NULL DEFAULT 'pending_review' CHECK (
        consent_status IN ('pending_review', 'approved_public', 'rejected_privacy')
    ),
    reviewed_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    review_notes TEXT NOT NULL DEFAULT '',
    is_synthetic_sample INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    reviewed_at TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_photo_evidence_venue_status ON photo_evidence(venue_id, consent_status);

CREATE TABLE IF NOT EXISTS moderation_reports (
    id TEXT PRIMARY KEY,
    venue_id TEXT NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL CHECK (target_type IN ('venue', 'observation', 'photo_evidence')),
    target_id TEXT NOT NULL,
    reporter_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    reason TEXT NOT NULL,
    details TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (
        status IN ('open', 'investigating', 'resolved_upheld', 'resolved_dismissed')
    ),
    resolution_notes TEXT NOT NULL DEFAULT '',
    resolved_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_moderation_status ON moderation_reports(status, created_at DESC);

CREATE TABLE IF NOT EXISTS saved_views (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    filters_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_preferences (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    barrier_alerts_enabled INTEGER NOT NULL DEFAULT 1,
    stale_venue_digest_enabled INTEGER NOT NULL DEFAULT 1,
    moderation_updates_enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    actor_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_events_workspace_created ON audit_events(workspace_id, created_at DESC);
"""


class AtlasDatabase:
    """Thread-safe transactional repository for AccessAble Atlas."""

    def __init__(self, db_path: Path, private_storage_dir: Path) -> None:
        self.db_path = db_path
        self.private_storage_dir = private_storage_dir.resolve()
        self._lock = threading.RLock()
        self._persistent_conn: sqlite3.Connection | None = None

        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.private_storage_dir.mkdir(parents=True, exist_ok=True)

        self.init_schema()

    def _connect(self) -> sqlite3.Connection:
        if str(self.db_path) == ":memory:":
            if self._persistent_conn is None:
                conn = sqlite3.connect(":memory:", check_same_thread=False)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON;")
                self._persistent_conn = conn
            return self._persistent_conn

        conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Execute database operations inside a serialized ACID transaction."""
        with self._lock:
            conn = self._connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                if str(self.db_path) != ":memory:":
                    conn.close()

    def init_schema(self) -> None:
        with self.transaction() as conn:
            conn.executescript(SCHEMA_DDL)

    def _record_audit_in_tx(
        self,
        conn: sqlite3.Connection,
        workspace_id: str,
        actor_id: str | None,
        action: str,
        target_type: str,
        target_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        event_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO audit_events (id, workspace_id, actor_id, action, target_type, target_id, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                workspace_id,
                actor_id,
                action,
                target_type,
                target_id,
                json.dumps(metadata or {}),
                utc_now_iso(),
            ),
        )
        return event_id

    # ========================================================================
    # Users, Workspaces & Authentication
    # ========================================================================

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self.transaction() as conn:
            row = conn.execute(
                """
                SELECT u.id, u.email, u.display_name, u.role, u.workspace_id,
                       u.ai_consent_granted, u.telemetry_opt_in, u.created_at,
                       w.slug AS workspace_slug, w.name AS workspace_name, w.region AS workspace_region
                FROM users u
                JOIN workspaces w ON w.id = u.workspace_id
                WHERE u.id = ?
                """,
                (user_id,),
            ).fetchone()
            if not row:
                return None
            return self._serialize_user(dict(row))

    def authenticate_user(self, email: str, password: str) -> dict[str, Any] | None:
        with self.transaction() as conn:
            row = conn.execute(
                """
                SELECT u.id, u.email, u.password_hash, u.display_name, u.role, u.workspace_id,
                       u.ai_consent_granted, u.telemetry_opt_in, u.created_at,
                       w.slug AS workspace_slug, w.name AS workspace_name, w.region AS workspace_region
                FROM users u
                JOIN workspaces w ON w.id = u.workspace_id
                WHERE lower(u.email) = lower(?)
                """,
                (email.strip(),),
            ).fetchone()
            if not row:
                return None
            row_dict = dict(row)
            if not verify_password(password, str(row_dict.get("password_hash") or "")):
                return None
            return self._serialize_user(row_dict)

    def register_user(
        self,
        email: str,
        password: str,
        display_name: str,
        role: str = "contributor",
        workspace_id: str | None = None,
        ai_consent_granted: bool = False,
        telemetry_opt_in: bool = False,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT id FROM users WHERE lower(email) = lower(?)", (email.strip(),)
            ).fetchone()
            if existing:
                raise ValueError("An account with this email address already exists.")

            if not workspace_id:
                ws_row = conn.execute(
                    "SELECT id FROM workspaces WHERE slug = 'metro-civic-access' LIMIT 1"
                ).fetchone()
                if not ws_row:
                    ws_row = conn.execute(
                        "SELECT id FROM workspaces ORDER BY created_at ASC LIMIT 1"
                    ).fetchone()
                if ws_row:
                    workspace_id = str(ws_row["id"])
                else:
                    workspace_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO workspaces (id, slug, name, region, created_at) VALUES (?, ?, ?, ?, ?)",
                        (
                            workspace_id,
                            "metro-civic-access",
                            "Metro Civic Accessibility Collective",
                            "Pacific Northwest Metro",
                            now,
                        ),
                    )

            user_id = str(uuid.uuid4())
            pw_hash = hash_password(password)
            conn.execute(
                """
                INSERT INTO users (id, email, password_hash, display_name, role, workspace_id, ai_consent_granted, telemetry_opt_in, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    email.strip().lower(),
                    pw_hash,
                    display_name,
                    role,
                    workspace_id,
                    1 if ai_consent_granted else 0,
                    1 if telemetry_opt_in else 0,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO notification_preferences (user_id, barrier_alerts_enabled, stale_venue_digest_enabled, moderation_updates_enabled, updated_at)
                VALUES (?, 1, 1, 1, ?)
                """,
                (user_id, now),
            )
            self._record_audit_in_tx(
                conn,
                workspace_id=workspace_id,
                actor_id=user_id,
                action="user.registered",
                target_type="user",
                target_id=user_id,
                metadata={"role": role, "ai_consent_granted": ai_consent_granted},
            )
        user = self.get_user_by_id(user_id)
        assert user is not None
        return user

    def list_demo_accounts(self) -> list[dict[str, Any]]:
        """Return safe summary of seeded demo accounts for quick role switching during evaluation."""
        with self.transaction() as conn:
            rows = conn.execute(
                """
                SELECT u.id, u.email, u.display_name, u.role, w.name AS workspace_name, w.slug AS workspace_slug
                FROM users u
                JOIN workspaces w ON w.id = u.workspace_id
                ORDER BY CASE u.role
                    WHEN 'contributor' THEN 1
                    WHEN 'operator' THEN 2
                    WHEN 'moderator' THEN 3
                    WHEN 'viewer' THEN 4
                    ELSE 5
                END
                """
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _serialize_user(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "role": row["role"],
            "workspace_id": row["workspace_id"],
            "workspace_slug": row.get("workspace_slug", "metro-civic-access"),
            "workspace_name": row.get("workspace_name", "Metro Civic Accessibility Collective"),
            "workspace_region": row.get("workspace_region", "Metro Region"),
            "ai_consent_granted": bool(row.get("ai_consent_granted")),
            "telemetry_opt_in": bool(row.get("telemetry_opt_in")),
            "created_at": row["created_at"],
        }

    # ========================================================================
    # Venue Profiles & Structured Access Attributes
    # ========================================================================

    def _hydrate_venue(
        self,
        conn: sqlite3.Connection,
        venue_row: dict[str, Any],
        viewer_user: dict[str, Any] | None = None,
        include_details: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        venue_id = str(venue_row["id"])
        attr_row = conn.execute(
            "SELECT * FROM access_attributes WHERE venue_id = ?", (venue_id,)
        ).fetchone()
        attrs = self._serialize_attributes(dict(attr_row)) if attr_row else {}

        obs_stats = conn.execute(
            """
            SELECT COUNT(*) AS cnt, AVG(confidence_score) AS avg_conf, MAX(observed_at) AS latest_obs
            FROM observations
            WHERE venue_id = ?
            """,
            (venue_id,),
        ).fetchone()
        obs_count = int(obs_stats["cnt"] or 0) if obs_stats else 0
        avg_conf = float(obs_stats["avg_conf"]) if obs_stats and obs_stats["avg_conf"] is not None else None
        latest_obs = str(obs_stats["latest_obs"] or venue_row["last_observed_at"])

        freshness = compute_freshness_indicator(
            last_observed_at=latest_obs,
            active_barrier_alert=venue_row.get("active_barrier_alert"),
            observation_count=obs_count,
            avg_confidence=avg_conf,
            elevator_status=str(attrs.get("elevator_status") or "none"),
        )
        fit = evaluate_accessibility_fit(attrs, filters=filters)

        # Count approved photos (plus pending if viewer is moderator or uploader)
        photo_count_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM photo_evidence WHERE venue_id = ? AND consent_status = 'approved_public'",
            (venue_id,),
        ).fetchone()
        approved_photo_count = int(photo_count_row["cnt"] or 0) if photo_count_row else 0

        creator_row = conn.execute(
            "SELECT display_name, role FROM users WHERE id = ?", (venue_row["created_by"],)
        ).fetchone()

        result: dict[str, Any] = {
            "id": venue_id,
            "workspace_id": venue_row["workspace_id"],
            "created_by": venue_row["created_by"],
            "creator_name": creator_row["display_name"] if creator_row else "Community Contributor",
            "creator_role": creator_row["role"] if creator_row else "contributor",
            "slug": venue_row["slug"],
            "name": venue_row["name"],
            "category": venue_row["category"],
            "category_label": VENUE_CATEGORIES.get(venue_row["category"], venue_row["category"]),
            "address": venue_row["address"],
            "city": venue_row["city"],
            "postal_code": venue_row["postal_code"],
            "latitude": float(venue_row["latitude"]),
            "longitude": float(venue_row["longitude"]),
            "operating_hours": venue_row["operating_hours"],
            "operator_verified": bool(venue_row["operator_verified"]),
            "summary": venue_row["summary"],
            "status": venue_row["status"],
            "active_barrier_alert": venue_row["active_barrier_alert"],
            "is_synthetic_sample": bool(venue_row["is_synthetic_sample"]),
            "provenance_badge": (
                "Synthetic Sample · For Evaluation"
                if venue_row["is_synthetic_sample"]
                else ("Operator Verified Record" if venue_row["operator_verified"] else "Community Verified Record")
            ),
            "last_observed_at": latest_obs,
            "created_at": venue_row["created_at"],
            "updated_at": venue_row["updated_at"],
            "access_attributes": attrs,
            "freshness": freshness,
            "accessibility_fit": fit,
            "approved_photo_count": approved_photo_count,
        }

        if include_details:
            obs_rows = conn.execute(
                """
                SELECT o.*, u.display_name AS author_name
                FROM observations o
                JOIN users u ON u.id = o.author_id
                WHERE o.venue_id = ?
                ORDER BY o.observed_at DESC, o.created_at DESC
                """,
                (venue_id,),
            ).fetchall()
            result["observations"] = [self._serialize_observation(dict(r)) for r in obs_rows]

            viewer_id = str(viewer_user["id"]) if viewer_user else ""
            viewer_role = str(viewer_user["role"]) if viewer_user else ""
            if viewer_role in ("moderator", "admin"):
                photo_rows = conn.execute(
                    """
                    SELECT p.*, u.display_name AS uploader_name
                    FROM photo_evidence p
                    JOIN users u ON u.id = p.uploaded_by
                    WHERE p.venue_id = ?
                    ORDER BY p.created_at DESC
                    """,
                    (venue_id,),
                ).fetchall()
            elif viewer_id:
                photo_rows = conn.execute(
                    """
                    SELECT p.*, u.display_name AS uploader_name
                    FROM photo_evidence p
                    JOIN users u ON u.id = p.uploaded_by
                    WHERE p.venue_id = ?
                      AND (p.consent_status = 'approved_public' OR p.uploaded_by = ?)
                    ORDER BY p.created_at DESC
                    """,
                    (venue_id, viewer_id),
                ).fetchall()
            else:
                photo_rows = conn.execute(
                    """
                    SELECT p.*, u.display_name AS uploader_name
                    FROM photo_evidence p
                    JOIN users u ON u.id = p.uploaded_by
                    WHERE p.venue_id = ? AND p.consent_status = 'approved_public'
                    ORDER BY p.created_at DESC
                    """,
                    (venue_id,),
                ).fetchall()

            result["photo_evidence"] = [self._serialize_photo(dict(r)) for r in photo_rows]

            audit_rows = conn.execute(
                """
                SELECT a.id, a.action, a.target_type, a.target_id, a.metadata_json, a.created_at,
                       u.display_name AS actor_name
                FROM audit_events a
                LEFT JOIN users u ON u.id = a.actor_id
                WHERE a.target_id = ? OR json_extract(a.metadata_json, '$.venue_id') = ?
                ORDER BY a.created_at DESC
                LIMIT 20
                """,
                (venue_id, venue_id),
            ).fetchall()
            result["provenance_history"] = [
                {
                    "id": r["id"],
                    "action": r["action"],
                    "actor_name": r["actor_name"] or "System",
                    "target_type": r["target_type"],
                    "metadata": json.loads(r["metadata_json"] or "{}"),
                    "created_at": r["created_at"],
                }
                for r in audit_rows
            ]

        return result

    @staticmethod
    def _serialize_attributes(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "step_free_entrance": bool(row.get("step_free_entrance")),
            "entrance_door_width_cm": int(row.get("entrance_door_width_cm", 85)),
            "threshold_height_mm": int(row.get("threshold_height_mm", 0)),
            "door_opener_type": row.get("door_opener_type", "manual_light"),
            "ramp_present": bool(row.get("ramp_present")),
            "ramp_slope_degrees": float(row["ramp_slope_degrees"])
            if row.get("ramp_slope_degrees") is not None
            else None,
            "entrance_notes": row.get("entrance_notes", ""),
            "accessible_restroom_type": row.get("accessible_restroom_type", "none"),
            "grab_bars": row.get("grab_bars", "none"),
            "turning_circle_cm": int(row.get("turning_circle_cm", 150)),
            "elevator_status": row.get("elevator_status", "none"),
            "braille_tactile_signage": bool(row.get("braille_tactile_signage")),
            "hearing_loop_available": bool(row.get("hearing_loop_available")),
            "quiet_sensory_space": bool(row.get("quiet_sensory_space")),
            "accessible_parking_spaces": int(row.get("accessible_parking_spaces", 0)),
            "pathway_surface": row.get("pathway_surface", "smooth_paved"),
            "min_corridor_width_cm": int(row.get("min_corridor_width_cm", 120)),
            "lighting_level": row.get("lighting_level", "bright_even"),
            "acoustic_profile": row.get("acoustic_profile", "moderate"),
            "route_notes": row.get("route_notes", ""),
            "updated_at": row.get("updated_at"),
        }

    @staticmethod
    def _serialize_observation(row: dict[str, Any]) -> dict[str, Any]:
        role_key = str(row["observer_role"])
        conf_key = str(row["confidence_level"])
        return {
            "id": row["id"],
            "venue_id": row["venue_id"],
            "author_id": row["author_id"],
            "author_name": row.get("author_name", "Contributor"),
            "observer_role": role_key,
            "observer_role_label": OBSERVER_ROLES.get(role_key, role_key),
            "confidence_level": conf_key,
            "confidence_label": CONFIDENCE_LABELS.get(conf_key, conf_key),
            "confidence_score": int(row["confidence_score"]),
            "summary": row["summary"],
            "measured_door_width_cm": row["measured_door_width_cm"],
            "elevator_operational_check": row["elevator_operational_check"],
            "barriers_noted": row["barriers_noted"],
            "is_operational_alert": bool(row["is_operational_alert"]),
            "is_synthetic_sample": bool(row["is_synthetic_sample"]),
            "observed_at": row["observed_at"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _serialize_photo(row: dict[str, Any]) -> dict[str, Any]:
        cat_key = str(row["category"])
        return {
            "id": row["id"],
            "venue_id": row["venue_id"],
            "observation_id": row["observation_id"],
            "uploaded_by": row["uploaded_by"],
            "uploader_name": row.get("uploader_name", "Contributor"),
            "category": cat_key,
            "category_label": PHOTO_CATEGORIES.get(cat_key, cat_key),
            "alt_text": row["alt_text"],
            "caption": row["caption"],
            "mime_type": row["mime_type"],
            "byte_size": int(row["byte_size"]),
            "width_px": int(row["width_px"]),
            "height_px": int(row["height_px"]),
            "sha256_hash": row["sha256_hash"],
            "exif_stripped": bool(row["exif_stripped"]),
            "no_identifiable_faces_confirmed": bool(row["no_identifiable_faces_confirmed"]),
            "operator_or_public_area_consent": bool(row["operator_or_public_area_consent"]),
            "consent_status": row["consent_status"],
            "review_notes": row["review_notes"],
            "is_synthetic_sample": bool(row["is_synthetic_sample"]),
            "file_url": f"/api/photos/{row['id']}/file",
            "created_at": row["created_at"],
            "reviewed_at": row["reviewed_at"],
        }

    def list_venues(
        self,
        filters: dict[str, Any] | None = None,
        viewer_user: dict[str, Any] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        filters = filters or {}
        clauses: list[str] = []
        params: list[Any] = []

        include_archived = bool(filters.get("include_archived"))
        viewer_role = str(viewer_user.get("role") or "") if viewer_user else ""
        viewer_id = str(viewer_user.get("id") or "") if viewer_user else ""
        viewer_ws = str(viewer_user.get("workspace_id") or "") if viewer_user else ""

        if include_archived and viewer_role in ("moderator", "admin"):
            clauses.append("v.workspace_id = ?")
            params.append(viewer_ws)
        elif include_archived and viewer_id:
            clauses.append("(v.status != 'archived' OR v.created_by = ?)")
            params.append(viewer_id)
        else:
            clauses.append("v.status != 'archived'")

        if filters.get("workspace_id"):
            clauses.append("v.workspace_id = ?")
            params.append(str(filters["workspace_id"]))

        if filters.get("category") and filters["category"] != "all":
            clauses.append("v.category = ?")
            params.append(str(filters["category"]))

        if filters.get("city") and filters["city"] != "all":
            clauses.append("lower(v.city) = lower(?)")
            params.append(str(filters["city"]).strip())

        if filters.get("q"):
            q_like = f"%{str(filters['q']).strip().lower()}%"
            clauses.append(
                "(lower(v.name) LIKE ? OR lower(v.summary) LIKE ? OR lower(v.address) LIKE ? OR lower(v.city) LIKE ?)"
            )
            params.extend([q_like, q_like, q_like, q_like])

        # Push structured attribute filters directly into parameterized SQL
        if filters.get("step_free"):
            clauses.append("a.step_free_entrance = 1")
        if filters.get("min_door_width_cm"):
            clauses.append("a.entrance_door_width_cm >= ?")
            params.append(int(filters["min_door_width_cm"]))
        if filters.get("accessible_restroom"):
            clauses.append(
                "a.accessible_restroom_type IN ('changing_places_hoist', 'single_user_all_gender', 'wheelchair_stall')"
            )
        if filters.get("elevator_operational"):
            clauses.append("a.elevator_status = 'operational'")
        if filters.get("quiet_space"):
            clauses.append("a.quiet_sensory_space = 1")
        if filters.get("hearing_loop"):
            clauses.append("a.hearing_loop_available = 1")
        if filters.get("braille_signage"):
            clauses.append("a.braille_tactile_signage = 1")

        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"""
            SELECT
                v.*,
                a.step_free_entrance, a.entrance_door_width_cm, a.threshold_height_mm,
                a.door_opener_type, a.ramp_present, a.ramp_slope_degrees, a.entrance_notes,
                a.accessible_restroom_type, a.grab_bars, a.turning_circle_cm, a.elevator_status,
                a.braille_tactile_signage, a.hearing_loop_available, a.quiet_sensory_space,
                a.accessible_parking_spaces, a.pathway_surface, a.min_corridor_width_cm,
                a.lighting_level, a.acoustic_profile, a.route_notes,
                a.updated_at AS attr_updated_at,
                u.display_name AS creator_name,
                u.role AS creator_role,
                COALESCE(obs.cnt, 0) AS obs_count,
                obs.avg_conf AS obs_avg_conf,
                obs.latest_obs AS obs_latest_at,
                COALESCE(ph.approved_cnt, 0) AS approved_photo_count
            FROM venues v
            LEFT JOIN access_attributes a ON a.venue_id = v.id
            LEFT JOIN users u ON u.id = v.created_by
            LEFT JOIN (
                SELECT venue_id, COUNT(*) AS cnt, AVG(confidence_score) AS avg_conf, MAX(observed_at) AS latest_obs
                FROM observations
                GROUP BY venue_id
            ) obs ON obs.venue_id = v.id
            LEFT JOIN (
                SELECT venue_id, COUNT(*) AS approved_cnt
                FROM photo_evidence
                WHERE consent_status = 'approved_public'
                GROUP BY venue_id
            ) ph ON ph.venue_id = v.id
            {where_sql}
            ORDER BY v.updated_at DESC
        """

        with self.transaction() as conn:
            rows = conn.execute(sql, params).fetchall()
            hydrated: list[dict[str, Any]] = []
            for row in rows:
                row_dict = dict(row)
                attrs = self._serialize_attributes(
                    {**row_dict, "updated_at": row_dict.get("attr_updated_at")}
                )
                obs_count = int(row_dict.get("obs_count") or 0)
                avg_conf = (
                    float(row_dict["obs_avg_conf"])
                    if row_dict.get("obs_avg_conf") is not None
                    else None
                )
                latest_obs = str(row_dict.get("obs_latest_at") or row_dict["last_observed_at"])

                freshness = compute_freshness_indicator(
                    last_observed_at=latest_obs,
                    active_barrier_alert=row_dict.get("active_barrier_alert"),
                    observation_count=obs_count,
                    avg_confidence=avg_conf,
                    elevator_status=str(attrs.get("elevator_status") or "none"),
                )
                freshness_filter = filters.get("freshness")
                if freshness_filter and freshness_filter != "all":
                    if freshness["state"] != freshness_filter:
                        continue

                fit = evaluate_accessibility_fit(attrs, filters=filters)
                if not fit["matches_filters"]:
                    continue

                hydrated.append(
                    {
                        "id": str(row_dict["id"]),
                        "workspace_id": row_dict["workspace_id"],
                        "created_by": row_dict["created_by"],
                        "creator_name": row_dict.get("creator_name") or "Community Contributor",
                        "creator_role": row_dict.get("creator_role") or "contributor",
                        "slug": row_dict["slug"],
                        "name": row_dict["name"],
                        "category": row_dict["category"],
                        "category_label": VENUE_CATEGORIES.get(
                            row_dict["category"], row_dict["category"]
                        ),
                        "address": row_dict["address"],
                        "city": row_dict["city"],
                        "postal_code": row_dict["postal_code"],
                        "latitude": float(row_dict["latitude"]),
                        "longitude": float(row_dict["longitude"]),
                        "operating_hours": row_dict["operating_hours"],
                        "operator_verified": bool(row_dict["operator_verified"]),
                        "summary": row_dict["summary"],
                        "status": row_dict["status"],
                        "active_barrier_alert": row_dict["active_barrier_alert"],
                        "is_synthetic_sample": bool(row_dict["is_synthetic_sample"]),
                        "provenance_badge": (
                            "Synthetic Sample · For Evaluation"
                            if row_dict["is_synthetic_sample"]
                            else (
                                "Operator Verified Record"
                                if row_dict["operator_verified"]
                                else "Community Verified Record"
                            )
                        ),
                        "last_observed_at": latest_obs,
                        "created_at": row_dict["created_at"],
                        "updated_at": row_dict["updated_at"],
                        "access_attributes": attrs,
                        "freshness": freshness,
                        "accessibility_fit": fit,
                        "approved_photo_count": int(row_dict.get("approved_photo_count") or 0),
                    }
                )

            total_matching = len(hydrated)
            bounded_limit = max(1, min(100, int(limit)))
            bounded_offset = max(0, int(offset))
            sliced = hydrated[bounded_offset : bounded_offset + bounded_limit]

            cities_rows = conn.execute(
                "SELECT DISTINCT city FROM venues WHERE status != 'archived' ORDER BY city ASC"
            ).fetchall()
            cities = [str(r["city"]) for r in cities_rows]

        return {
            "items": sliced,
            "total": total_matching,
            "limit": bounded_limit,
            "offset": bounded_offset,
            "available_cities": cities,
        }

    def get_venue_by_id(
        self,
        venue_id: str,
        viewer_user: dict[str, Any] | None = None,
        include_details: bool = True,
    ) -> dict[str, Any] | None:
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM venues WHERE id = ?", (venue_id,)).fetchone()
            if not row:
                return None
            venue_dict = dict(row)
            if venue_dict["status"] == "archived":
                viewer_id = str(viewer_user.get("id") or "") if viewer_user else ""
                viewer_role = str(viewer_user.get("role") or "") if viewer_user else ""
                viewer_ws = str(viewer_user.get("workspace_id") or "") if viewer_user else ""
                is_owner = viewer_id == str(venue_dict["created_by"])
                is_ws_mod = (
                    viewer_ws == str(venue_dict["workspace_id"])
                    and viewer_role in ("moderator", "admin", "operator")
                )
                if not (is_owner or is_ws_mod):
                    return None
            return self._hydrate_venue(
                conn,
                venue_dict,
                viewer_user=viewer_user,
                include_details=include_details,
            )

    def create_venue(
        self,
        validated_data: dict[str, Any],
        actor_user: dict[str, Any],
        is_synthetic_sample: bool = False,
        observed_at_override: str | None = None,
    ) -> dict[str, Any]:
        now = observed_at_override or utc_now_iso()
        venue_id = str(uuid.uuid4())
        base_slug = validated_data["slug"]
        slug = f"{base_slug}-{venue_id[:6]}"
        workspace_id = str(actor_user["workspace_id"])
        actor_id = str(actor_user["id"])
        operator_verified = 1 if actor_user.get("role") in ("operator", "moderator", "admin") else 0
        attrs = validated_data["access_attributes"]

        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO venues (
                    id, workspace_id, created_by, slug, name, category, address, city, postal_code,
                    latitude, longitude, operating_hours, operator_verified, summary, status,
                    active_barrier_alert, is_synthetic_sample, last_observed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    venue_id,
                    workspace_id,
                    actor_id,
                    slug,
                    validated_data["name"],
                    validated_data["category"],
                    validated_data["address"],
                    validated_data["city"],
                    validated_data["postal_code"],
                    validated_data["latitude"],
                    validated_data["longitude"],
                    validated_data["operating_hours"],
                    operator_verified,
                    validated_data["summary"],
                    validated_data.get("status", "published"),
                    validated_data.get("active_barrier_alert"),
                    1 if is_synthetic_sample else 0,
                    now,
                    now,
                    now,
                ),
            )
            self._upsert_attributes_in_tx(conn, venue_id, attrs, now)

            # Create initial baseline observation so every venue starts with verifiable provenance
            obs_id = str(uuid.uuid4())
            initial_role = (
                "venue_operator"
                if actor_user.get("role") == "operator"
                else "accessibility_advocate"
            )
            conn.execute(
                """
                INSERT INTO observations (
                    id, venue_id, author_id, observer_role, confidence_level, confidence_score,
                    summary, measured_door_width_cm, elevator_operational_check, barriers_noted,
                    is_operational_alert, is_synthetic_sample, observed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    obs_id,
                    venue_id,
                    actor_id,
                    initial_role,
                    "verified_measurement",
                    95,
                    f"Initial structured accessibility profile documented: {validated_data['summary'][:240]}",
                    attrs["entrance_door_width_cm"],
                    attrs["elevator_status"]
                    if attrs["elevator_status"] in ("operational", "out_of_service")
                    else "not_applicable",
                    validated_data.get("active_barrier_alert") or "",
                    1 if validated_data.get("active_barrier_alert") else 0,
                    1 if is_synthetic_sample else 0,
                    now,
                    now,
                ),
            )
            self._record_audit_in_tx(
                conn,
                workspace_id=workspace_id,
                actor_id=actor_id,
                action="venue.created",
                target_type="venue",
                target_id=venue_id,
                metadata={
                    "venue_id": venue_id,
                    "name": validated_data["name"],
                    "category": validated_data["category"],
                    "is_synthetic_sample": is_synthetic_sample,
                },
            )

        created = self.get_venue_by_id(venue_id, viewer_user=actor_user, include_details=True)
        assert created is not None
        return created

    def _upsert_attributes_in_tx(
        self,
        conn: sqlite3.Connection,
        venue_id: str,
        attrs: dict[str, Any],
        now: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO access_attributes (
                venue_id, step_free_entrance, entrance_door_width_cm, threshold_height_mm,
                door_opener_type, ramp_present, ramp_slope_degrees, entrance_notes,
                accessible_restroom_type, grab_bars, turning_circle_cm, elevator_status,
                braille_tactile_signage, hearing_loop_available, quiet_sensory_space,
                accessible_parking_spaces, pathway_surface, min_corridor_width_cm,
                lighting_level, acoustic_profile, route_notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(venue_id) DO UPDATE SET
                step_free_entrance = excluded.step_free_entrance,
                entrance_door_width_cm = excluded.entrance_door_width_cm,
                threshold_height_mm = excluded.threshold_height_mm,
                door_opener_type = excluded.door_opener_type,
                ramp_present = excluded.ramp_present,
                ramp_slope_degrees = excluded.ramp_slope_degrees,
                entrance_notes = excluded.entrance_notes,
                accessible_restroom_type = excluded.accessible_restroom_type,
                grab_bars = excluded.grab_bars,
                turning_circle_cm = excluded.turning_circle_cm,
                elevator_status = excluded.elevator_status,
                braille_tactile_signage = excluded.braille_tactile_signage,
                hearing_loop_available = excluded.hearing_loop_available,
                quiet_sensory_space = excluded.quiet_sensory_space,
                accessible_parking_spaces = excluded.accessible_parking_spaces,
                pathway_surface = excluded.pathway_surface,
                min_corridor_width_cm = excluded.min_corridor_width_cm,
                lighting_level = excluded.lighting_level,
                acoustic_profile = excluded.acoustic_profile,
                route_notes = excluded.route_notes,
                updated_at = excluded.updated_at
            """,
            (
                venue_id,
                1 if attrs["step_free_entrance"] else 0,
                attrs["entrance_door_width_cm"],
                attrs["threshold_height_mm"],
                attrs["door_opener_type"],
                1 if attrs["ramp_present"] else 0,
                attrs.get("ramp_slope_degrees"),
                attrs.get("entrance_notes", ""),
                attrs["accessible_restroom_type"],
                attrs["grab_bars"],
                attrs["turning_circle_cm"],
                attrs["elevator_status"],
                1 if attrs["braille_tactile_signage"] else 0,
                1 if attrs["hearing_loop_available"] else 0,
                1 if attrs["quiet_sensory_space"] else 0,
                attrs["accessible_parking_spaces"],
                attrs["pathway_surface"],
                attrs["min_corridor_width_cm"],
                attrs["lighting_level"],
                attrs["acoustic_profile"],
                attrs.get("route_notes", ""),
                now,
            ),
        )

    def update_venue(
        self,
        venue_id: str,
        validated_data: dict[str, Any],
        actor_user: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE venues
                SET name = ?, category = ?, address = ?, city = ?, postal_code = ?,
                    latitude = ?, longitude = ?, operating_hours = ?, summary = ?,
                    status = ?, active_barrier_alert = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    validated_data["name"],
                    validated_data["category"],
                    validated_data["address"],
                    validated_data["city"],
                    validated_data["postal_code"],
                    validated_data["latitude"],
                    validated_data["longitude"],
                    validated_data["operating_hours"],
                    validated_data["summary"],
                    validated_data["status"],
                    validated_data.get("active_barrier_alert"),
                    now,
                    venue_id,
                ),
            )
            if validated_data.get("access_attributes"):
                self._upsert_attributes_in_tx(
                    conn, venue_id, validated_data["access_attributes"], now
                )
            self._record_audit_in_tx(
                conn,
                workspace_id=str(actor_user["workspace_id"]),
                actor_id=str(actor_user["id"]),
                action="venue.updated",
                target_type="venue",
                target_id=venue_id,
                metadata={"venue_id": venue_id, "status": validated_data["status"]},
            )
        updated = self.get_venue_by_id(venue_id, viewer_user=actor_user, include_details=True)
        assert updated is not None
        return updated

    def archive_venue(self, venue_id: str, actor_user: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        with self.transaction() as conn:
            conn.execute(
                "UPDATE venues SET status = 'archived', updated_at = ? WHERE id = ?",
                (now, venue_id),
            )
            self._record_audit_in_tx(
                conn,
                workspace_id=str(actor_user["workspace_id"]),
                actor_id=str(actor_user["id"]),
                action="venue.archived",
                target_type="venue",
                target_id=venue_id,
                metadata={"venue_id": venue_id},
            )
        archived = self.get_venue_by_id(venue_id, viewer_user=actor_user, include_details=True)
        assert archived is not None
        return archived

    def delete_venue(self, venue_id: str, actor_user: dict[str, Any]) -> None:
        with self.transaction() as conn:
            photo_rows = conn.execute(
                "SELECT storage_key FROM photo_evidence WHERE venue_id = ?", (venue_id,)
            ).fetchall()
            conn.execute("DELETE FROM venues WHERE id = ?", (venue_id,))
            self._record_audit_in_tx(
                conn,
                workspace_id=str(actor_user["workspace_id"]),
                actor_id=str(actor_user["id"]),
                action="venue.deleted",
                target_type="venue",
                target_id=venue_id,
                metadata={"venue_id": venue_id},
            )
            for p_row in photo_rows:
                self._safe_delete_storage_file(str(p_row["storage_key"]))

    # ========================================================================
    # Timestamped Observations
    # ========================================================================

    def create_observation(
        self,
        venue_id: str,
        validated_obs: dict[str, Any],
        actor_user: dict[str, Any],
        observed_at_override: str | None = None,
        is_synthetic_sample: bool = False,
    ) -> dict[str, Any]:
        now = observed_at_override or utc_now_iso()
        obs_id = str(uuid.uuid4())
        actor_id = str(actor_user["id"])
        workspace_id = str(actor_user["workspace_id"])

        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO observations (
                    id, venue_id, author_id, observer_role, confidence_level, confidence_score,
                    summary, measured_door_width_cm, elevator_operational_check, barriers_noted,
                    is_operational_alert, is_synthetic_sample, observed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    obs_id,
                    venue_id,
                    actor_id,
                    validated_obs["observer_role"],
                    validated_obs["confidence_level"],
                    validated_obs["confidence_score"],
                    validated_obs["summary"],
                    validated_obs.get("measured_door_width_cm"),
                    validated_obs.get("elevator_operational_check"),
                    validated_obs.get("barriers_noted", ""),
                    1 if validated_obs["is_operational_alert"] else 0,
                    1 if is_synthetic_sample else 0,
                    now,
                    now,
                ),
            )

            # Update venue's last_observed_at and propagate operational alerts or verified measurements
            if validated_obs["is_operational_alert"]:
                alert_text = (
                    validated_obs.get("barriers_noted")
                    or validated_obs["summary"][:240]
                )
                conn.execute(
                    "UPDATE venues SET last_observed_at = ?, active_barrier_alert = ?, updated_at = ? WHERE id = ?",
                    (now, alert_text, now, venue_id),
                )
            else:
                conn.execute(
                    "UPDATE venues SET last_observed_at = ?, updated_at = ? WHERE id = ?",
                    (now, now, venue_id),
                )

            if validated_obs.get("measured_door_width_cm"):
                conn.execute(
                    "UPDATE access_attributes SET entrance_door_width_cm = ?, updated_at = ? WHERE venue_id = ?",
                    (validated_obs["measured_door_width_cm"], now, venue_id),
                )
            if validated_obs.get("elevator_operational_check") in ("operational", "out_of_service"):
                conn.execute(
                    "UPDATE access_attributes SET elevator_status = ?, updated_at = ? WHERE venue_id = ?",
                    (validated_obs["elevator_operational_check"], now, venue_id),
                )
                if validated_obs["elevator_operational_check"] == "operational":
                    # Clear elevator outage alert if corroborated as operational
                    conn.execute(
                        "UPDATE venues SET active_barrier_alert = NULL WHERE id = ? AND active_barrier_alert LIKE '%elevator%'",
                        (venue_id,),
                    )

            self._record_audit_in_tx(
                conn,
                workspace_id=workspace_id,
                actor_id=actor_id,
                action="observation.submitted",
                target_type="observation",
                target_id=obs_id,
                metadata={
                    "venue_id": venue_id,
                    "confidence_level": validated_obs["confidence_level"],
                    "is_operational_alert": validated_obs["is_operational_alert"],
                },
            )

            row = conn.execute(
                """
                SELECT o.*, u.display_name AS author_name
                FROM observations o
                JOIN users u ON u.id = o.author_id
                WHERE o.id = ?
                """,
                (obs_id,),
            ).fetchone()
            assert row is not None
            return self._serialize_observation(dict(row))

    # ========================================================================
    # Consent-Reviewed Photo Evidence & Private Storage
    # ========================================================================

    def _resolve_safe_storage_path(self, storage_key: str) -> Path:
        """Resolve a storage key inside private_storage_dir and block path traversal."""
        if not storage_key or "/" in storage_key or "\\" in storage_key or ".." in storage_key:
            raise ValueError("Invalid storage key: path traversal characters are forbidden.")
        candidate = (self.private_storage_dir / storage_key).resolve()
        if not candidate.is_relative_to(self.private_storage_dir):
            raise ValueError("Invalid storage key: outside private storage boundary.")
        return candidate

    def _safe_delete_storage_file(self, storage_key: str) -> None:
        try:
            target = self._resolve_safe_storage_path(storage_key)
            if target.is_file():
                target.unlink()
        except ValueError:
            pass

    def create_photo_evidence(
        self,
        venue_id: str,
        validated_photo: dict[str, Any],
        actor_user: dict[str, Any],
        observation_id: str | None = None,
        auto_approve: bool = False,
        is_synthetic_sample: bool = False,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        photo_id = str(uuid.uuid4())
        ext = validated_photo["extension"]
        storage_key = f"{photo_id}.{ext}"
        file_path = self._resolve_safe_storage_path(storage_key)
        file_path.write_bytes(validated_photo["scrubbed_bytes"])

        actor_id = str(actor_user["id"])
        workspace_id = str(actor_user["workspace_id"])
        actor_role = str(actor_user.get("role") or "contributor")
        consent_status = (
            "approved_public"
            if (auto_approve or actor_role in ("moderator", "admin", "operator"))
            else "pending_review"
        )

        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO photo_evidence (
                    id, venue_id, observation_id, uploaded_by, category, alt_text, caption,
                    storage_key, mime_type, byte_size, width_px, height_px, sha256_hash,
                    exif_stripped, no_identifiable_faces_confirmed, operator_or_public_area_consent,
                    consent_status, reviewed_by, review_notes, is_synthetic_sample, created_at, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    photo_id,
                    venue_id,
                    observation_id,
                    actor_id,
                    validated_photo["category"],
                    validated_photo["alt_text"],
                    validated_photo["caption"],
                    storage_key,
                    validated_photo["mime_type"],
                    validated_photo["byte_size"],
                    validated_photo["width_px"],
                    validated_photo["height_px"],
                    validated_photo["sha256_hash"],
                    consent_status,
                    actor_id if consent_status == "approved_public" else None,
                    "Auto-approved verified operator/moderator upload."
                    if consent_status == "approved_public"
                    else "",
                    1 if is_synthetic_sample else 0,
                    now,
                    now if consent_status == "approved_public" else None,
                ),
            )
            self._record_audit_in_tx(
                conn,
                workspace_id=workspace_id,
                actor_id=actor_id,
                action="photo.uploaded",
                target_type="photo_evidence",
                target_id=photo_id,
                metadata={
                    "venue_id": venue_id,
                    "category": validated_photo["category"],
                    "consent_status": consent_status,
                    "exif_stripped": True,
                    "sha256_hash": validated_photo["sha256_hash"][:16],
                },
            )
            row = conn.execute(
                """
                SELECT p.*, u.display_name AS uploader_name
                FROM photo_evidence p
                JOIN users u ON u.id = p.uploaded_by
                WHERE p.id = ?
                """,
                (photo_id,),
            ).fetchone()
            assert row is not None
            return self._serialize_photo(dict(row))

    def get_photo_record_and_bytes(self, photo_id: str) -> tuple[dict[str, Any], bytes] | None:
        with self.transaction() as conn:
            row = conn.execute(
                """
                SELECT p.*, v.workspace_id, u.display_name AS uploader_name
                FROM photo_evidence p
                JOIN venues v ON v.id = p.venue_id
                JOIN users u ON u.id = p.uploaded_by
                WHERE p.id = ?
                """,
                (photo_id,),
            ).fetchone()
            if not row:
                return None
            record = dict(row)
        file_path = self._resolve_safe_storage_path(str(record["storage_key"]))
        if not file_path.is_file():
            return None
        return record, file_path.read_bytes()

    def review_photo_consent(
        self,
        photo_id: str,
        consent_status: str,
        review_notes: str,
        moderator_user: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now_iso()
        mod_id = str(moderator_user["id"])
        ws_id = str(moderator_user["workspace_id"])
        with self.transaction() as conn:
            existing = conn.execute(
                """
                SELECT p.id, p.venue_id, v.workspace_id
                FROM photo_evidence p
                JOIN venues v ON v.id = p.venue_id
                WHERE p.id = ?
                """,
                (photo_id,),
            ).fetchone()
            if not existing:
                raise LookupError("Photo evidence record not found.")
            if str(existing["workspace_id"]) != ws_id:
                raise PermissionError("Cross-workspace moderation denied.")

            conn.execute(
                """
                UPDATE photo_evidence
                SET consent_status = ?, reviewed_by = ?, review_notes = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (consent_status, mod_id, review_notes, now, photo_id),
            )
            self._record_audit_in_tx(
                conn,
                workspace_id=ws_id,
                actor_id=mod_id,
                action="photo.consent_reviewed",
                target_type="photo_evidence",
                target_id=photo_id,
                metadata={
                    "venue_id": existing["venue_id"],
                    "consent_status": consent_status,
                    "review_notes": review_notes,
                },
            )
            row = conn.execute(
                """
                SELECT p.*, u.display_name AS uploader_name
                FROM photo_evidence p
                JOIN users u ON u.id = p.uploaded_by
                WHERE p.id = ?
                """,
                (photo_id,),
            ).fetchone()
            assert row is not None
            return self._serialize_photo(dict(row))

    # ========================================================================
    # Moderation Queue & Audit Trail
    # ========================================================================

    def create_moderation_report(
        self,
        validated_report: dict[str, Any],
        reporter_user: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now_iso()
        report_id = str(uuid.uuid4())
        reporter_id = str(reporter_user["id"])
        ws_id = str(reporter_user["workspace_id"])
        with self.transaction() as conn:
            venue_row = conn.execute(
                "SELECT id, name, workspace_id FROM venues WHERE id = ?",
                (validated_report["venue_id"],),
            ).fetchone()
            if not venue_row:
                raise LookupError("Target venue does not exist.")
            if str(venue_row["workspace_id"]) != ws_id:
                raise PermissionError(
                    "Cross-workspace moderation reporting denied: venue belongs to another workspace."
                )

            conn.execute(
                """
                INSERT INTO moderation_reports (
                    id, venue_id, target_type, target_id, reporter_id, reason, details,
                    status, resolution_notes, resolved_by, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', '', NULL, ?, NULL)
                """,
                (
                    report_id,
                    validated_report["venue_id"],
                    validated_report["target_type"],
                    validated_report["target_id"],
                    reporter_id,
                    validated_report["reason"],
                    validated_report["details"],
                    now,
                ),
            )
            self._record_audit_in_tx(
                conn,
                workspace_id=ws_id,
                actor_id=reporter_id,
                action="moderation.report_created",
                target_type=validated_report["target_type"],
                target_id=validated_report["target_id"],
                metadata={
                    "report_id": report_id,
                    "venue_id": validated_report["venue_id"],
                    "reason": validated_report["reason"],
                },
            )
            return {
                "id": report_id,
                "venue_id": validated_report["venue_id"],
                "venue_name": venue_row["name"],
                "target_type": validated_report["target_type"],
                "target_id": validated_report["target_id"],
                "reporter_id": reporter_id,
                "reporter_name": reporter_user["display_name"],
                "reason": validated_report["reason"],
                "reason_label": MODERATION_REASONS.get(
                    validated_report["reason"], validated_report["reason"]
                ),
                "details": validated_report["details"],
                "status": "open",
                "resolution_notes": "",
                "created_at": now,
                "resolved_at": None,
            }

    def list_moderation_queue(self, workspace_id: str) -> dict[str, Any]:
        with self.transaction() as conn:
            report_rows = conn.execute(
                """
                SELECT m.*, v.name AS venue_name, u.display_name AS reporter_name,
                       ru.display_name AS resolver_name
                FROM moderation_reports m
                JOIN venues v ON v.id = m.venue_id
                JOIN users u ON u.id = m.reporter_id
                LEFT JOIN users ru ON ru.id = m.resolved_by
                WHERE v.workspace_id = ?
                ORDER BY CASE m.status WHEN 'open' THEN 0 WHEN 'investigating' THEN 1 ELSE 2 END,
                         m.created_at DESC
                """,
                (workspace_id,),
            ).fetchall()

            pending_photos = conn.execute(
                """
                SELECT p.*, v.name AS venue_name, u.display_name AS uploader_name
                FROM photo_evidence p
                JOIN venues v ON v.id = p.venue_id
                JOIN users u ON u.id = p.uploaded_by
                WHERE v.workspace_id = ? AND p.consent_status = 'pending_review'
                ORDER BY p.created_at DESC
                """,
                (workspace_id,),
            ).fetchall()

            audit_rows = conn.execute(
                """
                SELECT a.*, u.display_name AS actor_name
                FROM audit_events a
                LEFT JOIN users u ON u.id = a.actor_id
                WHERE a.workspace_id = ?
                ORDER BY a.created_at DESC
                LIMIT 35
                """,
                (workspace_id,),
            ).fetchall()

        return {
            "reports": [
                {
                    "id": r["id"],
                    "venue_id": r["venue_id"],
                    "venue_name": r["venue_name"],
                    "target_type": r["target_type"],
                    "target_id": r["target_id"],
                    "reporter_name": r["reporter_name"],
                    "reason": r["reason"],
                    "reason_label": MODERATION_REASONS.get(r["reason"], r["reason"]),
                    "details": r["details"],
                    "status": r["status"],
                    "resolution_notes": r["resolution_notes"],
                    "resolver_name": r["resolver_name"],
                    "created_at": r["created_at"],
                    "resolved_at": r["resolved_at"],
                }
                for r in report_rows
            ],
            "pending_photos": [
                {
                    **self._serialize_photo(dict(p)),
                    "venue_name": p["venue_name"],
                }
                for p in pending_photos
            ],
            "audit_events": [
                {
                    "id": a["id"],
                    "action": a["action"],
                    "actor_name": a["actor_name"] or "System",
                    "target_type": a["target_type"],
                    "target_id": a["target_id"],
                    "metadata": json.loads(a["metadata_json"] or "{}"),
                    "created_at": a["created_at"],
                }
                for a in audit_rows
            ],
        }

    def resolve_moderation_report(
        self,
        report_id: str,
        status: str,
        resolution_notes: str,
        moderator_user: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now_iso()
        mod_id = str(moderator_user["id"])
        ws_id = str(moderator_user["workspace_id"])
        with self.transaction() as conn:
            row = conn.execute(
                """
                SELECT m.*, v.workspace_id, v.name AS venue_name
                FROM moderation_reports m
                JOIN venues v ON v.id = m.venue_id
                WHERE m.id = ?
                """,
                (report_id,),
            ).fetchone()
            if not row:
                raise LookupError("Moderation report not found.")
            if str(row["workspace_id"]) != ws_id:
                raise PermissionError("Cross-workspace moderation resolution denied.")

            conn.execute(
                """
                UPDATE moderation_reports
                SET status = ?, resolution_notes = ?, resolved_by = ?, resolved_at = ?
                WHERE id = ?
                """,
                (status, resolution_notes, mod_id, now, report_id),
            )

            # If a privacy flag on a photo is upheld, automatically reject public consent on that photo
            if (
                status == "resolved_upheld"
                and row["target_type"] == "photo_evidence"
                and row["reason"] == "privacy_face_visible"
            ):
                conn.execute(
                    """
                    UPDATE photo_evidence
                    SET consent_status = 'rejected_privacy', reviewed_by = ?, review_notes = ?, reviewed_at = ?
                    WHERE id = ?
                    """,
                    (mod_id, f"Upheld privacy report: {resolution_notes}", now, row["target_id"]),
                )

            self._record_audit_in_tx(
                conn,
                workspace_id=ws_id,
                actor_id=mod_id,
                action="moderation.report_resolved",
                target_type="moderation_report",
                target_id=report_id,
                metadata={
                    "venue_id": row["venue_id"],
                    "status": status,
                    "resolution_notes": resolution_notes,
                },
            )
            return {
                "id": report_id,
                "venue_id": row["venue_id"],
                "venue_name": row["venue_name"],
                "status": status,
                "resolution_notes": resolution_notes,
                "resolved_at": now,
            }

    # ========================================================================
    # Saved Views, Settings, Insights & Data Portability
    # ========================================================================

    def list_saved_views(self, user_id: str) -> list[dict[str, Any]]:
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_views WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "user_id": r["user_id"],
                    "workspace_id": r["workspace_id"],
                    "name": r["name"],
                    "filters": json.loads(r["filters_json"] or "{}"),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def create_saved_view(
        self,
        user: dict[str, Any],
        name: str,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now_iso()
        view_id = str(uuid.uuid4())
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO saved_views (id, user_id, workspace_id, name, filters_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    view_id,
                    user["id"],
                    user["workspace_id"],
                    name,
                    json.dumps(filters),
                    now,
                ),
            )
        return {
            "id": view_id,
            "user_id": user["id"],
            "workspace_id": user["workspace_id"],
            "name": name,
            "filters": filters,
            "created_at": now,
        }

    def get_saved_view_by_id(self, view_id: str) -> dict[str, Any] | None:
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM saved_views WHERE id = ?", (view_id,)
            ).fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "user_id": row["user_id"],
                "workspace_id": row["workspace_id"],
                "name": row["name"],
                "filters": json.loads(row["filters_json"] or "{}"),
                "created_at": row["created_at"],
            }

    def delete_saved_view(self, view_id: str) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM saved_views WHERE id = ?", (view_id,))

    def get_user_settings(self, user_id: str) -> dict[str, Any]:
        with self.transaction() as conn:
            pref_row = conn.execute(
                "SELECT * FROM notification_preferences WHERE user_id = ?", (user_id,)
            ).fetchone()
            user_row = conn.execute(
                "SELECT ai_consent_granted, telemetry_opt_in FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            return {
                "user_id": user_id,
                "barrier_alerts_enabled": bool(pref_row["barrier_alerts_enabled"]) if pref_row else True,
                "stale_venue_digest_enabled": bool(pref_row["stale_venue_digest_enabled"])
                if pref_row
                else True,
                "moderation_updates_enabled": bool(pref_row["moderation_updates_enabled"])
                if pref_row
                else True,
                "ai_consent_granted": bool(user_row["ai_consent_granted"]) if user_row else False,
                "telemetry_opt_in": bool(user_row["telemetry_opt_in"]) if user_row else False,
            }

    def update_user_settings(self, user_id: str, workspace_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO notification_preferences (
                    user_id, barrier_alerts_enabled, stale_venue_digest_enabled, moderation_updates_enabled, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    barrier_alerts_enabled = excluded.barrier_alerts_enabled,
                    stale_venue_digest_enabled = excluded.stale_venue_digest_enabled,
                    moderation_updates_enabled = excluded.moderation_updates_enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    1 if settings["barrier_alerts_enabled"] else 0,
                    1 if settings["stale_venue_digest_enabled"] else 0,
                    1 if settings["moderation_updates_enabled"] else 0,
                    now,
                ),
            )
            conn.execute(
                "UPDATE users SET ai_consent_granted = ?, telemetry_opt_in = ? WHERE id = ?",
                (
                    1 if settings["ai_consent_granted"] else 0,
                    1 if settings["telemetry_opt_in"] else 0,
                    user_id,
                ),
            )
            self._record_audit_in_tx(
                conn,
                workspace_id=workspace_id,
                actor_id=user_id,
                action="user.settings_updated",
                target_type="user",
                target_id=user_id,
                metadata={
                    "ai_consent_granted": settings["ai_consent_granted"],
                    "telemetry_opt_in": settings["telemetry_opt_in"],
                },
            )
        return self.get_user_settings(user_id)

    def get_workspace_insights(self, workspace_id: str | None = None) -> dict[str, Any]:
        """
        Compute transparent, evidence-backed workspace insights (Journey C).
        Explicitly documents time range, data source, units, assumptions, and limitations.
        """
        listing = self.list_venues(
            filters={"workspace_id": workspace_id} if workspace_id else {},
            limit=200,
        )
        venues = listing["items"]
        total_venues = len(venues)

        freshness_breakdown = {
            "fresh_verified": 0,
            "aging_review_soon": 0,
            "stale_reverify": 0,
            "active_alert": 0,
        }
        step_free_count = 0
        wheelchair_standard_count = 0
        accessible_restroom_count = 0
        hearing_loop_count = 0
        quiet_space_count = 0
        synthetic_count = 0
        real_community_count = 0
        door_widths: list[int] = []
        attention_records: list[dict[str, Any]] = []

        for v in venues:
            f_state = v["freshness"]["state"]
            freshness_breakdown[f_state] = freshness_breakdown.get(f_state, 0) + 1
            attrs = v["access_attributes"]
            if attrs.get("step_free_entrance"):
                step_free_count += 1
            if v["accessibility_fit"].get("wheelchair_standard_met"):
                wheelchair_standard_count += 1
            if attrs.get("accessible_restroom_type") in (
                "changing_places_hoist",
                "single_user_all_gender",
                "wheelchair_stall",
            ):
                accessible_restroom_count += 1
            if attrs.get("hearing_loop_available"):
                hearing_loop_count += 1
            if attrs.get("quiet_sensory_space"):
                quiet_space_count += 1
            if v.get("is_synthetic_sample"):
                synthetic_count += 1
            else:
                real_community_count += 1
            if attrs.get("entrance_door_width_cm"):
                door_widths.append(int(attrs["entrance_door_width_cm"]))

            if f_state in ("active_alert", "stale_reverify"):
                attention_records.append(
                    {
                        "venue_id": v["id"],
                        "name": v["name"],
                        "city": v["city"],
                        "category_label": v["category_label"],
                        "freshness_state": f_state,
                        "freshness_label": v["freshness"]["label"],
                        "days_since_last_observation": v["freshness"]["days_since_last_observation"],
                        "explanation": v["freshness"]["explanation"],
                        "is_synthetic_sample": v["is_synthetic_sample"],
                    }
                )

        avg_door_width_cm = (
            round(sum(door_widths) / len(door_widths), 1) if door_widths else 0.0
        )

        return {
            "generated_at": utc_now_iso(),
            "metadata": {
                "time_range": "Current published directory snapshot (rolling 30/90-day freshness windows)",
                "source": "Canonical transactional store (venues, access_attributes, observations)",
                "units": "Venues (count), Doorway clearance (centimeters / cm), Freshness age (days)",
                "assumptions": (
                    "Wheelchair standard clearance requires step-free entry, doorway width >= 82 cm, "
                    "and restroom turning circle >= 150 cm. Freshness decays after 30 days (aging) and 90 days (stale)."
                ),
                "limitations": (
                    f"Includes {synthetic_count} clearly-labelled synthetic sample venue(s) and "
                    f"{real_community_count} user-created record(s). Field conditions can change between observations."
                ),
            },
            "metrics": {
                "total_published_venues": total_venues,
                "synthetic_sample_venues": synthetic_count,
                "user_documented_venues": real_community_count,
                "step_free_venues": step_free_count,
                "wheelchair_standard_venues": wheelchair_standard_count,
                "accessible_restroom_venues": accessible_restroom_count,
                "hearing_loop_venues": hearing_loop_count,
                "quiet_sensory_venues": quiet_space_count,
                "average_entrance_door_width_cm": avg_door_width_cm,
            },
            "freshness_breakdown": freshness_breakdown,
            "records_requiring_attention": attention_records,
        }

    def export_workspace_bundle(self, actor_user: dict[str, Any]) -> dict[str, Any]:
        """Export portable JSON bundle of workspace venues, observations, user settings, and provenance."""
        ws_id = str(actor_user["workspace_id"])
        user_id = str(actor_user["id"])
        venues_resp = self.list_venues(
            filters={"workspace_id": ws_id, "include_archived": True},
            viewer_user=actor_user,
            limit=100,
        )
        detailed_venues = [
            self.get_venue_by_id(v["id"], viewer_user=actor_user, include_details=True)
            for v in venues_resp["items"]
        ]
        with self.transaction() as conn:
            self._record_audit_in_tx(
                conn,
                workspace_id=ws_id,
                actor_id=user_id,
                action="workspace.exported",
                target_type="workspace",
                target_id=ws_id,
                metadata={"venue_count": len(detailed_venues)},
            )
        return {
            "export_version": "1.0",
            "exported_at": utc_now_iso(),
            "exported_by": {
                "id": actor_user["id"],
                "email": actor_user["email"],
                "display_name": actor_user["display_name"],
                "role": actor_user["role"],
                "workspace_name": actor_user.get("workspace_name"),
            },
            "retention_and_privacy_policy": (
                "Export contains structured venue profiles, timestamped observations, and consent-verified "
                "photo metadata. Raw binary files remain in private storage and EXIF GPS metadata is stripped."
            ),
            "user_settings": self.get_user_settings(user_id),
            "saved_views": self.list_saved_views(user_id),
            "venues": [v for v in detailed_venues if v is not None],
        }

    def import_venue(
        self,
        validated_data: dict[str, Any],
        actor_user: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist an imported venue after explicit human review and confirmation (Journey B.3)."""
        created = self.create_venue(
            validated_data=validated_data,
            actor_user=actor_user,
            is_synthetic_sample=False,
        )
        with self.transaction() as conn:
            self._record_audit_in_tx(
                conn,
                workspace_id=str(actor_user["workspace_id"]),
                actor_id=str(actor_user["id"]),
                action="venue.imported_and_confirmed",
                target_type="venue",
                target_id=created["id"],
                metadata={
                    "venue_id": created["id"],
                    "import_source": validated_data.get("import_source", "json-import"),
                    "user_confirmed_imported_values": True,
                },
            )
        refreshed = self.get_venue_by_id(
            created["id"], viewer_user=actor_user, include_details=True
        )
        assert refreshed is not None
        return refreshed

    def delete_user_account(self, actor_user: dict[str, Any]) -> dict[str, Any]:
        """
        Execute user account & personal data deletion/anonymization (PRD Section 6, 8, 12):
        - Removes personal saved_views and notification_preferences.
        - Anonymizes personal PII (email, display_name, password_hash) on the user row so
          foreign-key community observations remain intact without retaining personal identity.
        - Records an immutable account.deleted audit event.
        """
        now = utc_now_iso()
        user_id = str(actor_user["id"])
        ws_id = str(actor_user["workspace_id"])
        anon_email = f"deleted-{user_id[:8]}@anonymized.atlas.local"
        disabled_pw = hash_password(str(uuid.uuid4()))

        with self.transaction() as conn:
            conn.execute("DELETE FROM saved_views WHERE user_id = ?", (user_id,))
            conn.execute(
                "DELETE FROM notification_preferences WHERE user_id = ?", (user_id,)
            )
            conn.execute(
                """
                UPDATE users
                SET email = ?, password_hash = ?, display_name = 'Anonymized Community Member',
                    role = 'viewer', ai_consent_granted = 0, telemetry_opt_in = 0
                WHERE id = ?
                """,
                (anon_email, disabled_pw, user_id),
            )
            self._record_audit_in_tx(
                conn,
                workspace_id=ws_id,
                actor_id=None,
                action="account.deleted_and_anonymized",
                target_type="user",
                target_id=user_id,
                metadata={"deleted_at": now},
            )
        return {
            "deleted": True,
            "user_id": user_id,
            "deleted_at": now,
            "policy_applied": (
                "Personal email, display name, credentials, saved views, and notification preferences "
                "have been permanently purged/anonymized."
            ),
        }
