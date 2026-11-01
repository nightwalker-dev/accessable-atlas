"""Feature flag registry gating optional adapters and unfinished work."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from atlas.config import AtlasConfig


@dataclass(frozen=True)
class FeatureFlag:
    """Typed feature flag definition with rollout state and rationale."""

    key: str
    enabled: bool
    stage: str
    owner_module: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "enabled": self.enabled,
            "stage": self.stage,
            "owner_module": self.owner_module,
            "description": self.description,
        }


class FeatureFlagRegistry:
    """Server-side feature flag evaluator with environment variable overrides."""

    def __init__(
        self,
        config: AtlasConfig | None = None,
        overrides: dict[str, bool] | None = None,
    ) -> None:
        ai_default = bool(config.ai_enabled) if config else False
        tb_default = bool(config.tinybird_enabled) if config else False
        gm_default = bool(config.google_maps_enabled) if config else True

        base_flags: tuple[FeatureFlag, ...] = (
            FeatureFlag(
                key="google_maps_earth_integration",
                enabled=gm_default,
                stage="ga",
                owner_module="modules/google-maps-earth-geospatial",
                description=(
                    "Google Maps Platform (Street View 360, Wheelchair Transit, Elevation) & Google Earth 3D KML exporter."
                ),
            ),
            FeatureFlag(
                key="json_venue_import",
                enabled=True,
                stage="ga",
                owner_module="modules/venue-profiles",
                description=(
                    "Structured municipal/audit JSON venue import with mandatory human review confirmation."
                ),
            ),
            FeatureFlag(
                key="offline_cached_snapshot",
                enabled=True,
                stage="ga",
                owner_module="modules/map-and-list-search",
                description=(
                    "Offline connectivity detection banner and cached local directory snapshot browsing."
                ),
            ),
            FeatureFlag(
                key="ai_route_briefing",
                enabled=ai_default,
                stage="opt_in",
                owner_module="modules/structured-access-attributes",
                description=(
                    "Optional consent-gated AI route briefing adapter; falls back to deterministic summary when disabled."
                ),
            ),
            FeatureFlag(
                key="tinybird_analytics",
                enabled=tb_default,
                stage="opt_in",
                owner_module="modules/freshness-indicators",
                description=(
                    "Optional privacy-minimized 7-field operational event forwarding to Tinybird."
                ),
            ),
            FeatureFlag(
                key="automated_face_blur_prepass",
                enabled=False,
                stage="unfinished_flagged_off",
                owner_module="modules/consent-reviewed-photo-evidence",
                description=(
                    "Experimental client/server CV face-blurring pre-pass. Flagged off so all community photos require human moderator review."
                ),
            ),
            FeatureFlag(
                key="realtime_transit_elevator_feed",
                enabled=False,
                stage="unfinished_flagged_off",
                owner_module="modules/timestamped-observations",
                description=(
                    "Unfinished GTFS-RT automated transit elevator feed ingestion. Flagged off in favor of verified human/operator observations."
                ),
            ),
        )

        self._flags: dict[str, FeatureFlag] = {}
        for flag in base_flags:
            env_key = f"ATLAS_FLAG_{flag.key.upper()}"
            env_val = os.environ.get(env_key)
            enabled = flag.enabled
            if env_val is not None:
                enabled = env_val.strip().lower() in ("1", "true", "yes", "on")
            if overrides and flag.key in overrides:
                enabled = bool(overrides[flag.key])
            self._flags[flag.key] = FeatureFlag(
                key=flag.key,
                enabled=enabled,
                stage=flag.stage,
                owner_module=flag.owner_module,
                description=flag.description,
            )

    def is_enabled(self, key: str) -> bool:
        """Return True if the named feature flag is active."""
        flag = self._flags.get(key)
        return bool(flag and flag.enabled)

    def set_override(self, key: str, enabled: bool) -> None:
        """Override a feature flag state at runtime (used in tests and admin toggles)."""
        if key not in self._flags:
            raise KeyError(f"Unknown feature flag: {key}")
        existing = self._flags[key]
        self._flags[key] = FeatureFlag(
            key=existing.key,
            enabled=bool(enabled),
            stage=existing.stage,
            owner_module=existing.owner_module,
            description=existing.description,
        )

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """Return full feature flag map for health/taxonomy introspection."""
        return {k: v.to_dict() for k, v in self._flags.items()}

