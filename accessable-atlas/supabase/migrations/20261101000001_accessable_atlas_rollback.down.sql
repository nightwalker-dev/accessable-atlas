-- ============================================================================
-- AccessAble Atlas — Reversible Down-Migration (Rollback Companion)
-- Migration: 20261101000001_accessable_atlas_rollback.down.sql
-- Reverses: 20261101000000_accessable_atlas_init.sql
-- Safety Note: Execute only on development/staging branches or with explicit
--              human owner approval after exporting a workspace snapshot.
-- ============================================================================

BEGIN;

-- 1. Drop Row-Level Security (RLS) policies in reverse order
DROP POLICY IF EXISTS notification_preferences_owner_policy ON public.notification_preferences;
DROP POLICY IF EXISTS saved_views_owner_policy ON public.saved_views;
DROP POLICY IF EXISTS photo_evidence_read_policy ON public.photo_evidence;
DROP POLICY IF EXISTS venues_update_policy ON public.venues;
DROP POLICY IF EXISTS venues_write_policy ON public.venues;
DROP POLICY IF EXISTS venues_read_policy ON public.venues;

-- 2. Drop secondary indexes
DROP INDEX IF EXISTS public.idx_audit_events_workspace_created;
DROP INDEX IF EXISTS public.idx_moderation_status;
DROP INDEX IF EXISTS public.idx_photo_evidence_venue_status;
DROP INDEX IF EXISTS public.idx_observations_venue_observed;
DROP INDEX IF EXISTS public.idx_access_attributes_filter;
DROP INDEX IF EXISTS public.idx_venues_coords;
DROP INDEX IF EXISTS public.idx_venues_category_city;
DROP INDEX IF EXISTS public.idx_venues_workspace_status;

-- 3. Drop tables in reverse foreign-key dependency order
DROP TABLE IF EXISTS public.audit_events;
DROP TABLE IF EXISTS public.notification_preferences;
DROP TABLE IF EXISTS public.saved_views;
DROP TABLE IF EXISTS public.moderation_reports;
DROP TABLE IF EXISTS public.photo_evidence;
DROP TABLE IF EXISTS public.observations;
DROP TABLE IF EXISTS public.access_attributes;
DROP TABLE IF EXISTS public.venues;
DROP TABLE IF EXISTS public.users;
DROP TABLE IF EXISTS public.workspaces;

COMMIT;

