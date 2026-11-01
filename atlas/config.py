"""Centralized configuration, environment validation, and secret redaction for AccessAble Atlas."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "secret",
        "token",
        "api_key",
        "authorization",
        "cookie",
        "supabase_service_role_key",
        "atlas_jwt_secret",
        "tinybird_token",
        "atlas_ai_api_key",
        "google_maps_api_key",
        "csrf_token",
    }
)


def mask_secret(value: str | None) -> str:
    """Return a masked representation of a secret value safe for logs and reports."""
    if not value:
        return "<unset>"
    cleaned = str(value).strip()
    if len(cleaned) <= 8:
        return "****"
    return f"{cleaned[:3]}...{cleaned[-3:]} (len={len(cleaned)})"


def redact_sensitive_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact sensitive keys from dictionaries before logging or telemetry."""
    redacted: dict[str, Any] = {}
    for key, val in data.items():
        key_lower = str(key).lower()
        if any(s in key_lower for s in SENSITIVE_KEYS):
            redacted[key] = "[REDACTED]"
        elif isinstance(val, dict):
            redacted[key] = redact_sensitive_dict(val)
        elif isinstance(val, list):
            redacted[key] = [
                redact_sensitive_dict(item) if isinstance(item, dict) else item
                for item in val
            ]
        else:
            redacted[key] = val
    return redacted


def _load_dotenv_file(dotenv_path: Path) -> None:
    """Load simple KEY=VALUE pairs from .env without overwriting existing env vars."""
    if not dotenv_path.is_file():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class AtlasConfig:
    """Validated runtime configuration for AccessAble Atlas."""

    env: str
    host: str
    port: int
    db_path: Path
    private_storage_dir: Path
    seed_synthetic_data: bool
    jwt_secret: str
    session_ttl_seconds: int
    allowed_origins: tuple[str, ...]
    rate_limit_read_per_min: int
    rate_limit_write_per_min: int
    max_upload_bytes: int
    max_json_body_bytes: int
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_storage_bucket: str
    tinybird_enabled: bool
    tinybird_host: str
    tinybird_token: str
    tinybird_datasource: str
    ai_enabled: bool
    ai_provider: str
    ai_api_key: str
    ai_max_tokens: int
    ai_timeout_seconds: int
    google_maps_enabled: bool = True
    google_maps_api_key: str = ""
    google_maps_timeout_seconds: int = 4
    google_earth_flyover_altitude_m: int = 240

    @property
    def google_maps_configured(self) -> bool:
        """Return True when a live Google Maps Platform API key is configured."""
        return bool(
            self.google_maps_enabled
            and self.google_maps_api_key
            and "placeholder" not in self.google_maps_api_key.lower()
        )

    @property
    def supabase_configured(self) -> bool:
        """Return True only when real Supabase project credentials are configured."""
        return bool(
            self.supabase_url
            and self.supabase_service_role_key
            and "your-project-ref" not in self.supabase_url
            and "placeholder" not in self.supabase_service_role_key
        )

    @property
    def tinybird_configured(self) -> bool:
        """Return True only when Tinybird telemetry is enabled and configured."""
        return bool(
            self.tinybird_enabled
            and self.tinybird_host
            and self.tinybird_token
            and "placeholder" not in self.tinybird_token
        )


def load_config(env_override: dict[str, str] | None = None) -> AtlasConfig:
    """Load and validate configuration from environment variables."""
    root_dir = Path(__file__).resolve().parent.parent
    _load_dotenv_file(root_dir / ".env")

    merged_env = dict(os.environ)
    if env_override:
        merged_env.update(env_override)

    # Enforce PRD Section 9 architectural guardrail: Neon must never be configured as a second store
    if merged_env.get("NEON_DATABASE_URL") or merged_env.get("NEON_API_KEY"):
        raise ValueError(
            "Configuration error: Neon is explicitly prohibited by PRD Section 9. "
            "Supabase is the sole canonical operational database platform for AccessAble Atlas."
        )

    env_name = merged_env.get("ATLAS_ENV", "development").strip().lower()
    host = merged_env.get("ATLAS_HOST", "127.0.0.1").strip()
    port = int(merged_env.get("ATLAS_PORT", "8080"))

    db_path_raw = merged_env.get("ATLAS_DB_PATH", str(root_dir / "data" / "accessable_atlas.db"))
    db_path = Path(db_path_raw) if db_path_raw != ":memory:" else Path(":memory:")

    storage_raw = merged_env.get(
        "ATLAS_PRIVATE_STORAGE_DIR", str(root_dir / "data" / "private_storage")
    )
    private_storage_dir = Path(storage_raw)

    seed_synthetic = merged_env.get("ATLAS_SEED_SYNTHETIC_DATA", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    jwt_secret = merged_env.get("ATLAS_JWT_SECRET", "").strip()
    if not jwt_secret or jwt_secret == "CHANGE_ME_GENERATE_WITH_OPENSSL_RAND_HEX_32":
        if env_name == "production":
            raise ValueError(
                "ATLAS_JWT_SECRET must be set to a strong cryptographic secret in production."
            )
        # Generate an ephemeral strong 32-byte hex secret for local/test execution
        jwt_secret = secrets.token_hex(32)

    origins_raw = merged_env.get(
        "ATLAS_ALLOWED_ORIGINS", f"http://127.0.0.1:{port},http://localhost:{port}"
    )
    allowed_origins = tuple(o.strip() for o in origins_raw.split(",") if o.strip())

    return AtlasConfig(
        env=env_name,
        host=host,
        port=port,
        db_path=db_path,
        private_storage_dir=private_storage_dir,
        seed_synthetic_data=seed_synthetic,
        jwt_secret=jwt_secret,
        session_ttl_seconds=max(300, int(merged_env.get("ATLAS_SESSION_TTL_SECONDS", "28800"))),
        allowed_origins=allowed_origins,
        rate_limit_read_per_min=max(10, int(merged_env.get("ATLAS_RATE_LIMIT_READ_PER_MIN", "120"))),
        rate_limit_write_per_min=max(5, int(merged_env.get("ATLAS_RATE_LIMIT_WRITE_PER_MIN", "30"))),
        max_upload_bytes=min(
            10 * 1024 * 1024, max(1024, int(merged_env.get("ATLAS_MAX_UPLOAD_BYTES", "5242880")))
        ),
        max_json_body_bytes=262144,  # 256 KiB bound for JSON requests
        supabase_url=merged_env.get("SUPABASE_URL", "").strip(),
        supabase_anon_key=merged_env.get("SUPABASE_ANON_KEY", "").strip(),
        supabase_service_role_key=merged_env.get("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
        supabase_storage_bucket=merged_env.get(
            "SUPABASE_STORAGE_BUCKET", "venue-photo-evidence"
        ).strip(),
        tinybird_enabled=merged_env.get("TINYBIRD_ENABLED", "false").lower() in ("1", "true", "yes"),
        tinybird_host=merged_env.get("TINYBIRD_HOST", "https://api.us-east.tinybird.co").strip(),
        tinybird_token=merged_env.get("TINYBIRD_TOKEN", "").strip(),
        tinybird_datasource=merged_env.get("TINYBIRD_DATASOURCE", "atlas_events").strip(),
        ai_enabled=merged_env.get("ATLAS_AI_ENABLED", "false").lower() in ("1", "true", "yes"),
        ai_provider=merged_env.get("ATLAS_AI_PROVIDER", "none").strip().lower(),
        ai_api_key=merged_env.get("ATLAS_AI_API_KEY", "").strip(),
        ai_max_tokens=min(1000, max(50, int(merged_env.get("ATLAS_AI_MAX_TOKENS", "350")))),
        ai_timeout_seconds=min(15, max(1, int(merged_env.get("ATLAS_AI_TIMEOUT_SECONDS", "4")))),
        google_maps_enabled=merged_env.get("GOOGLE_MAPS_ENABLED", "true").lower()
        in ("1", "true", "yes"),
        google_maps_api_key=merged_env.get("GOOGLE_MAPS_API_KEY", "").strip(),
        google_maps_timeout_seconds=min(
            15, max(1, int(merged_env.get("GOOGLE_MAPS_TIMEOUT_SECONDS", "4")))
        ),
        google_earth_flyover_altitude_m=min(
            5000, max(50, int(merged_env.get("GOOGLE_EARTH_FLYOVER_ALTITUDE_M", "240")))
        ),
    )

