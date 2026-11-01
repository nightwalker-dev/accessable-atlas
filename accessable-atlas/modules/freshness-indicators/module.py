"""Domain module: Freshness indicators (modules/freshness-indicators)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from atlas.domain import FRESHNESS_STATES, compute_freshness_indicator

MODULE_ID = "modules/freshness-indicators"
MODULE_NAME = "Freshness indicators"


class FreshnessIndicatorsModule:
    """Computes deterministic 4-state freshness indicators with non-color icon & shape tokens."""

    module_id = MODULE_ID
    states = FRESHNESS_STATES

    def evaluate(
        self,
        last_observed_at: str | None,
        active_barrier_alert: str | None = None,
        observation_count: int = 1,
        avg_confidence: float | None = 85.0,
        elevator_status: str = "operational",
        reference_now: datetime | None = None,
    ) -> dict[str, Any]:
        """Compute deterministic freshness state, confidence band, icon token, and surface colors."""
        return compute_freshness_indicator(
            last_observed_at=last_observed_at,
            active_barrier_alert=active_barrier_alert,
            observation_count=observation_count,
            avg_confidence=avg_confidence,
            elevator_status=elevator_status,
            reference_now=reference_now,
        )
