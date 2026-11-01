"""Structured JSON logging with automatic PII, credential, token, and IP redaction."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import re
from typing import Any

from atlas.config import SENSITIVE_KEYS

EMAIL_PATTERN = re.compile(r"\b([A-Za-z0-9._%+-])([A-Za-z0-9._%+-]*)(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
BEARER_PATTERN = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")
IPV4_PATTERN = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3})\.(\d{1,3})\b")

PII_KEYS = frozenset(
    {
        "email",
        "author_email",
        "reporter_email",
        "uploader_email",
        "ip",
        "client_ip",
        "remote_ip",
        "phone",
        "address_private",
    }
)


def mask_email(email: str) -> str:
    """Mask an email address while preserving domain for operational debugging."""

    def _repl(match: re.Match[str]) -> str:
        first_char = match.group(1)
        domain = match.group(3)
        return f"{first_char}***{domain}"

    return EMAIL_PATTERN.sub(_repl, email)


def mask_ipv4(text: str) -> str:
    """Mask the final octet of IPv4 addresses for privacy-preserving request logs."""
    return IPV4_PATTERN.sub(r"\1.x", text)


def redact_string_pii(value: str) -> str:
    """Scrub embedded JWTs, Bearer tokens, email addresses, and client IPs from strings."""
    cleaned = JWT_PATTERN.sub("[REDACTED_JWT]", value)
    cleaned = BEARER_PATTERN.sub(r"\1[REDACTED_TOKEN]", cleaned)
    cleaned = mask_email(cleaned)
    cleaned = mask_ipv4(cleaned)
    return cleaned


def redact_pii_and_secrets(data: Any) -> Any:
    """Recursively redact secrets and mask PII across dicts, lists, and scalar values."""
    if isinstance(data, dict):
        redacted: dict[str, Any] = {}
        for key, val in data.items():
            key_lower = str(key).lower()
            if any(secret_key in key_lower for secret_key in SENSITIVE_KEYS):
                redacted[key] = "[REDACTED]"
            elif key_lower in PII_KEYS and isinstance(val, str):
                if "@" in val:
                    redacted[key] = mask_email(val)
                else:
                    redacted[key] = mask_ipv4(val)
            else:
                redacted[key] = redact_pii_and_secrets(val)
        return redacted
    if isinstance(data, list):
        return [redact_pii_and_secrets(item) for item in data]
    if isinstance(data, tuple):
        return [redact_pii_and_secrets(item) for item in data]
    if isinstance(data, str):
        return redact_string_pii(data)
    return data


class StructuredLogger:
    """Structured JSON logger enforcing PII & secret redaction on every log entry."""

    def __init__(self, service_name: str = "accessable-atlas", max_buffer: int = 250) -> None:
        self.service_name = service_name
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_buffer)

    def log(
        self,
        level: str,
        event: str,
        *,
        layer: str = "api",
        module: str = "core",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create, redact, buffer, and serialize a structured log record."""
        safe_context = redact_pii_and_secrets(context or {})
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": self.service_name,
            "level": level.upper(),
            "layer": layer,
            "module": module,
            "event": event,
            "context": safe_context,
        }
        self._buffer.append(entry)
        return entry

    def info(
        self,
        event: str,
        *,
        layer: str = "api",
        module: str = "core",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.log("INFO", event, layer=layer, module=module, context=context)

    def warning(
        self,
        event: str,
        *,
        layer: str = "api",
        module: str = "core",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.log("WARNING", event, layer=layer, module=module, context=context)

    def error(
        self,
        event: str,
        *,
        layer: str = "api",
        module: str = "core",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.log("ERROR", event, layer=layer, module=module, context=context)

    def to_json_line(self, entry: dict[str, Any]) -> str:
        """Serialize a redacted log entry to a single-line JSON string."""
        return json.dumps(entry, ensure_ascii=False, sort_keys=True)

    def get_recent_logs(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return recent redacted structured logs (newest first)."""
        items = list(self._buffer)
        items.reverse()
        return items[: max(1, min(limit, 250))]

