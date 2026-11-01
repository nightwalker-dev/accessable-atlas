# Module: Moderation (`modules/moderation`)

## Purpose
Manages community and operator flags (`moderation_reports` table), moderator consent queues, and immutable workspace audit events (`audit_events` table).

## Boundary Contracts
- **Report Schema:** [`ModerationReportSchema`](../../atlas/schemas.py)
- **Resolution Schema:** [`ModerationResolutionSchema`](../../atlas/schemas.py)
- **Authorization Actions:** `moderation.report`, `moderation.read_queue`, `moderation.resolve` (`confirm=true`)
- **Database Tables:** `public.moderation_reports`, `public.audit_events`

