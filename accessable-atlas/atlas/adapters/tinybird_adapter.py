"""Privacy-minimized aggregate telemetry adapter for Tinybird."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import threading
from typing import Any
import urllib.error
import urllib.request

from atlas.config import AtlasConfig

ALLOWED_EVENT_TYPES = frozenset(
    {
        "venue_searched",
        "venue_created",
        "observation_submitted",
        "photo_uploaded",
        "moderation_reported",
        "moderation_resolved",
        "freshness_status_computed",
    }
)

ALLOWED_EVENT_FIELDS = frozenset(
    {
        "timestamp",
        "event_type",
        "workspace_slug",
        "category",
        "freshness_state",
        "confidence_bucket",
        "metric_value",
    }
)

FORBIDDEN_PII_SUBSTRINGS = ("@", "http://", "https://", "bearer ", "eyj", "password", "secret")


class TinybirdAdapter:
    """
    Privacy-minimized operational telemetry adapter for Tinybird.
    - Never acts as canonical transactional store.
    - Enforces a strict schema allowlist; drops or masks any payload containing PII or secrets.
    - Fails gracefully without impacting core user workflows when Tinybird is disabled or offline.
    """

    def __init__(self, config: AtlasConfig, max_buffer: int = 200) -> None:
        self.config = config
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_buffer)
        self._lock = threading.Lock()
        self.total_emitted = 0
        self.total_dropped = 0

    def emit_event(
        self,
        event_type: str,
        workspace_slug: str = "metro-civic-access",
        category: str = "all",
        freshness_state: str = "unknown",
        confidence_bucket: str = "unknown",
        metric_value: int = 1,
        user_opted_in: bool = True,
    ) -> dict[str, Any]:
        """Validate, minimize, and record/send an aggregate operational event."""
        if not user_opted_in:
            return {"emitted": False, "reason": "user_telemetry_opted_out"}

        if event_type not in ALLOWED_EVENT_TYPES:
            self.total_dropped += 1
            return {"emitted": False, "reason": "disallowed_event_type"}

        sanitized_event: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": str(event_type)[:40],
            "workspace_slug": str(workspace_slug)[:64],
            "category": str(category)[:40],
            "freshness_state": str(freshness_state)[:40],
            "confidence_bucket": str(confidence_bucket)[:40],
            "metric_value": int(metric_value),
        }

        # Guardrail: ensure no string field accidentally contains an email, URL, or token
        for key, val in sanitized_event.items():
            if key not in ALLOWED_EVENT_FIELDS:
                self.total_dropped += 1
                return {"emitted": False, "reason": "schema_violation"}
            if isinstance(val, str):
                lower_val = val.lower()
                if any(forbidden in lower_val for forbidden in FORBIDDEN_PII_SUBSTRINGS):
                    self.total_dropped += 1
                    return {"emitted": False, "reason": "pii_or_secret_blocked"}

        with self._lock:
            self._buffer.append(sanitized_event)
            self.total_emitted += 1

        if not self.config.tinybird_configured:
            return {
                "emitted": True,
                "transport": "local_minimized_buffer",
                "event": sanitized_event,
            }

        # When Tinybird is configured, post NDJSON payload with a strict 2-second timeout
        url = (
            f"{self.config.tinybird_host.rstrip('/')}/v0/events"
            f"?name={self.config.tinybird_datasource}"
        )
        payload_bytes = (json.dumps(sanitized_event) + "\n").encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload_bytes,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.tinybird_token}",
                "Content-Type": "application/x-ndjson",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                raw_resp = resp.read(4096).decode("utf-8", errors="replace")
                parsed = json.loads(raw_resp) if raw_resp else {}
                if not isinstance(parsed, dict):
                    parsed = {}
                return {
                    "emitted": True,
                    "transport": "tinybird_http",
                    "successful_rows": int(parsed.get("successful_rows", 1)),
                }
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return {
                "emitted": True,
                "transport": "local_fallback_after_network_error",
                "event": sanitized_event,
            }

    def get_recent_events(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return recent privacy-minimized events from the in-memory ring buffer."""
        with self._lock:
            items = list(self._buffer)
        return items[-max(1, min(100, limit)) :]

    def get_status(self) -> dict[str, Any]:
        return {
            "provider": "tinybird",
            "role": "optional_privacy_minimized_analytics",
            "canonical_store": False,
            "configured": self.config.tinybird_configured,
            "datasource": self.config.tinybird_datasource,
            "buffered_events_count": len(self._buffer),
            "total_emitted": self.total_emitted,
            "total_dropped": self.total_dropped,
            "allowed_fields": sorted(ALLOWED_EVENT_FIELDS),
        }

