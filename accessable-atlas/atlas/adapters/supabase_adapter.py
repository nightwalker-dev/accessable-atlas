"""Canonical Supabase platform adapter with read-only health/policy inspection and local engine bridge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import urllib.error
import urllib.request
import json

from atlas.config import AtlasConfig, mask_secret


class SupabaseAdapter:
    """
    Adapter for Supabase (Auth, PostgREST, and Private Storage).
    Per PRD Section 9 & 11:
    - Supabase is the sole selected canonical operational database platform.
    - Neon is explicitly prohibited.
    - In local/CI/sandbox environments without external network or Supabase project keys,
      operations execute against the transactional SQLite engine while preserving identical
      schema constraints, ownership rules, and private storage semantics.
    """

    def __init__(self, config: AtlasConfig) -> None:
        self.config = config
        self.migration_path = (
            Path(__file__).resolve().parent.parent.parent
            / "supabase"
            / "migrations"
            / "20261101000000_accessable_atlas_init.sql"
        )

    def get_status(self) -> dict[str, Any]:
        """Return transparent integration status without fabricating live cloud connections."""
        migration_exists = self.migration_path.is_file()
        return {
            "platform": "supabase",
            "canonical_store": True,
            "competing_stores_disabled": ["neon"],
            "configured": self.config.supabase_configured,
            "mode": "supabase_cloud" if self.config.supabase_configured else "local_transactional_sqlite",
            "project_url": self.config.supabase_url if self.config.supabase_configured else "local://sqlite",
            "service_key_masked": mask_secret(self.config.supabase_service_role_key)
            if self.config.supabase_configured
            else "<local-mode>",
            "storage_bucket": self.config.supabase_storage_bucket,
            "migration_file": str(self.migration_path.name) if migration_exists else None,
            "migration_ready": migration_exists,
            "rls_policies_defined": migration_exists,
        }

    def probe_remote_health(self) -> dict[str, Any]:
        """Perform a safe read-only health check against Supabase REST if configured."""
        if not self.config.supabase_configured:
            return {
                "reachable": False,
                "mode": "local_transactional_sqlite",
                "reason": "Supabase cloud credentials not configured; using local transactional SQLite store.",
            }
        url = f"{self.config.supabase_url.rstrip('/')}/rest/v1/"
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "apikey": self.config.supabase_anon_key or self.config.supabase_service_role_key,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                status_code = resp.getcode()
                return {
                    "reachable": 200 <= status_code < 400,
                    "status_code": status_code,
                    "mode": "supabase_cloud",
                }
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {
                "reachable": False,
                "mode": "local_fallback_active",
                "reason": f"Supabase endpoint unreachable ({type(exc).__name__}); local fallback active.",
            }

