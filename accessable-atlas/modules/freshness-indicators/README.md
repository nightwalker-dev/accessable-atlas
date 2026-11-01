# Module: Freshness Indicators (`modules/freshness-indicators`)

## Purpose
Implements the deterministic 4-state freshness decay and barrier priority engine (`fresh_verified`, `aging_review_soon`, `stale_reverify`, `active_alert`) paired with WCAG 1.4.1 non-color icon tokens (`[✓]`, `[◷]`, `[↻]`, `[!]`) and distinct SVG map pin shapes (`circle`, `square`, `diamond`, `triangle`).

## Boundary Contracts
- **Domain Function:** [`compute_freshness_indicator`](../../atlas/domain.py)
- **States:** `fresh_verified` ($\le 30\text{ days}$, confidence $\ge 70\%$), `aging_review_soon` ($31..90\text{ days}$), `stale_reverify` ($> 90\text{ days}$), `active_alert` (immediate barrier override)

