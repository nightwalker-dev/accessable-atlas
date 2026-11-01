"""Background job runner for non-blocking maintenance, freshness digests, and telemetry flushing."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any

from atlas.adapters.tinybird_adapter import TinybirdAdapter
from atlas.auth import RevokedTokenStore
from atlas.db.database import AtlasDatabase
from atlas.logging_utils import StructuredLogger
from atlas.rate_limit import IdempotencyStore


class BackgroundJobRunner:
    """Executes asynchronous/scheduled background jobs downstream of Supabase/SQLite persistence."""

    def __init__(
        self,
        db: AtlasDatabase,
        revoked_tokens: RevokedTokenStore,
        idempotency_store: IdempotencyStore,
        tinybird_adapter: TinybirdAdapter,
        logger: StructuredLogger | None = None,
    ) -> None:
        self.db = db
        self.revoked_tokens = revoked_tokens
        self.idempotency_store = idempotency_store
        self.tinybird_adapter = tinybird_adapter
        self.logger = logger or StructuredLogger()
        self._last_run_summary: dict[str, Any] = {
            "runs_completed": 0,
            "last_run_at": None,
            "jobs": {},
        }

    def prune_expired_security_state(self) -> dict[str, Any]:
        """Prune expired JWT JTI revocation entries and expired idempotency keys."""
        now_epoch = time.time()
        now_mono = time.monotonic()

        pruned_jtis = 0
        with self.revoked_tokens._lock:
            expired_jtis = [
                k for k, exp in self.revoked_tokens._revoked.items() if exp <= now_epoch
            ]
            for k in expired_jtis:
                del self.revoked_tokens._revoked[k]
                pruned_jtis += 1
            active_jtis = len(self.revoked_tokens._revoked)

        pruned_idempotency = 0
        with self.idempotency_store._lock:
            expired_idem = [
                k
                for k, (exp, _, _) in self.idempotency_store._entries.items()
                if now_mono >= exp
            ]
            for k in expired_idem:
                del self.idempotency_store._entries[k]
                pruned_idempotency += 1
            active_idempotency = len(self.idempotency_store._entries)

        result = {
            "job": "prune_expired_security_state",
            "pruned_revoked_jtis": pruned_jtis,
            "active_revoked_jtis": active_jtis,
            "pruned_idempotency_keys": pruned_idempotency,
            "active_idempotency_keys": active_idempotency,
        }
        self.logger.info(
            "background_job.completed",
            layer="background_jobs",
            module="security_maintenance",
            context=result,
        )
        return result

    def compute_stale_venue_digest(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Scan published venues to summarize stale (>90d) and active-barrier records for digests."""
        listing = self.db.list_venues(filters={}, viewer_user=None, limit=100, offset=0)
        venues = listing.get("items", [])
        if workspace_id:
            venues = [v for v in venues if str(v.get("workspace_id")) == workspace_id]

        stale_slugs: list[str] = []
        aging_slugs: list[str] = []
        alert_slugs: list[str] = []

        for v in venues:
            state = str(v.get("freshness", {}).get("state") or "")
            slug = str(v.get("slug") or v.get("id"))
            if state == "stale_reverify":
                stale_slugs.append(slug)
            elif state == "aging_review_soon":
                aging_slugs.append(slug)
            elif state == "active_alert":
                alert_slugs.append(slug)

        result = {
            "job": "compute_stale_venue_digest",
            "evaluated_venues": len(venues),
            "stale_reverify_count": len(stale_slugs),
            "aging_review_soon_count": len(aging_slugs),
            "active_alert_count": len(alert_slugs),
            "stale_venue_slugs": stale_slugs,
            "active_alert_slugs": alert_slugs,
        }
        self.logger.info(
            "background_job.completed",
            layer="background_jobs",
            module="modules/freshness-indicators",
            context=result,
        )
        return result

    def flush_minimized_telemetry(self) -> dict[str, Any]:
        """Inspect and report privacy-minimized operational telemetry buffer status."""
        status = self.tinybird_adapter.get_status()
        recent = self.tinybird_adapter.get_recent_events(limit=25)
        result = {
            "job": "flush_minimized_telemetry",
            "mode": status.get("mode", "local_minimized_buffer"),
            "buffered_events": len(recent),
            "allowed_fields_count": len(status.get("allowed_fields", [])),
        }
        self.logger.info(
            "background_job.completed",
            layer="background_jobs",
            module="telemetry",
            context=result,
        )
        return result

    def run_all_maintenance_jobs(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Run all background maintenance jobs and update runner state."""
        sec_res = self.prune_expired_security_state()
        digest_res = self.compute_stale_venue_digest(workspace_id=workspace_id)
        telemetry_res = self.flush_minimized_telemetry()

        now_iso = datetime.now(timezone.utc).isoformat()
        self._last_run_summary = {
            "runs_completed": int(self._last_run_summary.get("runs_completed", 0)) + 1,
            "last_run_at": now_iso,
            "jobs": {
                "prune_expired_security_state": sec_res,
                "compute_stale_venue_digest": digest_res,
                "flush_minimized_telemetry": telemetry_res,
            },
        }
        return self._last_run_summary

    def get_status(self) -> dict[str, Any]:
        """Return background job runner status for health/insights introspection."""
        return {
            "registered_jobs": [
                "prune_expired_security_state",
                "compute_stale_venue_digest",
                "flush_minimized_telemetry",
            ],
            "runs_completed": self._last_run_summary["runs_completed"],
            "last_run_at": self._last_run_summary["last_run_at"],
        }
