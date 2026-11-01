# Module: Map and List Search (`modules/map-and-list-search`)

## Purpose
Provides synchronized geospatial map and accessible list search across published venues with SQL predicate pushdown (`step_free`, `min_door_width_cm`, `accessible_restroom`, `elevator_operational`, `quiet_space`, `hearing_loop`, `braille_signage`), freshness state filtering, pagination (`limit`, `offset`), and user-persisted `saved_views`.

## Boundary Contracts
- **Search Filter Schema:** [`MapAndListSearchFilterSchema`](../../atlas/schemas.py)
- **Saved View Schema:** [`SavedViewSchema`](../../atlas/schemas.py)
- **Query Engine:** [`AtlasDatabase.list_venues`](../../atlas/db/database.py) (`2` SQL `SELECT` queries regardless of result set size via single `LEFT JOIN`)

