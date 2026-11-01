# Module: Venue Profiles (`modules/venue-profiles`)

## Purpose
Manages public place records (`venues` table), spatial coordinates, operating hours, active barrier alerts, lifecycle states (`published`, `under_review`, `archived`), and human-reviewed JSON venue imports.

## Boundary Contracts
- **Primary Schema:** [`VenueProfileSchema`](../../atlas/schemas.py)
- **Import Schema:** [`VenueImportSchema`](../../atlas/schemas.py) (enforces `user_confirmed_imported_values: true`)
- **Authorization Actions:** `venue.read`, `venue.create`, `venue.update`, `venue.archive` (`confirm=true`), `venue.delete` (`confirm=true`)
- **Database Table:** `public.venues` ([`20261101000000_accessable_atlas_init.sql`](../../supabase/migrations/20261101000000_accessable_atlas_init.sql))

