# Module: Timestamped Observations (`modules/timestamped-observations`)

## Purpose
Manages append-only timestamped accessibility observations (`observations` table) recording observer role (`person_with_access_need`, `caregiver`, `accessibility_advocate`, `venue_operator`, `auditor`), confidence tier (`verified_measurement` = `95%`, `direct_observation` = `82%`, `secondhand_report` = `55%`, `needs_reverification` = `35%`), measured door widths, and elevator operational checks.

## Boundary Contracts
- **Boundary Schema:** [`TimestampedObservationSchema`](../../atlas/schemas.py)
- **Authorization Action:** `observation.create`
- **Database Table:** `public.observations` with index `idx_observations_venue_observed`

