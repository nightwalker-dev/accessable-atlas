-- ============================================================================
-- AccessAble Atlas — Canonical Supabase PostgreSQL Schema & RLS Migration
-- Migration: 20261101000000_accessable_atlas_init.sql
-- Target: Supabase PostgreSQL 16 (Development branch first; require owner approval for prod)
-- ============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Workspaces (Civic Chapters / Operator Organizations)
CREATE TABLE IF NOT EXISTS public.workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9-]{3,64}$'),
    name TEXT NOT NULL CHECK (char_length(name) BETWEEN 2 AND 120),
    region TEXT NOT NULL CHECK (char_length(region) BETWEEN 2 AND 120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Application Users (linked to Supabase auth.users where deployed)
CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE CHECK (char_length(email) BETWEEN 5 AND 254),
    display_name TEXT NOT NULL CHECK (char_length(display_name) BETWEEN 2 AND 80),
    role TEXT NOT NULL DEFAULT 'contributor' CHECK (
        role IN ('viewer', 'contributor', 'operator', 'moderator', 'admin')
    ),
    workspace_id UUID NOT NULL REFERENCES public.workspaces(id) ON DELETE RESTRICT,
    ai_consent_granted BOOLEAN NOT NULL DEFAULT FALSE,
    telemetry_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Venue Profiles
CREATE TABLE IF NOT EXISTS public.venues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    created_by UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    slug TEXT NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9-]{3,100}$'),
    name TEXT NOT NULL CHECK (char_length(name) BETWEEN 2 AND 140),
    category TEXT NOT NULL CHECK (
        category IN (
            'transit_hub',
            'civic_building',
            'healthcare',
            'library_museum',
            'park_trail',
            'dining_retail',
            'education',
            'community_center'
        )
    ),
    address TEXT NOT NULL CHECK (char_length(address) BETWEEN 4 AND 220),
    city TEXT NOT NULL CHECK (char_length(city) BETWEEN 2 AND 80),
    postal_code TEXT NOT NULL CHECK (char_length(postal_code) BETWEEN 3 AND 20),
    latitude DOUBLE PRECISION NOT NULL CHECK (latitude BETWEEN -90.0 AND 90.0),
    longitude DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180.0 AND 180.0),
    operating_hours TEXT NOT NULL DEFAULT '08:00 - 20:00 Daily' CHECK (char_length(operating_hours) <= 160),
    operator_verified BOOLEAN NOT NULL DEFAULT FALSE,
    summary TEXT NOT NULL CHECK (char_length(summary) BETWEEN 10 AND 1200),
    status TEXT NOT NULL DEFAULT 'published' CHECK (
        status IN ('published', 'under_review', 'archived')
    ),
    active_barrier_alert TEXT DEFAULT NULL CHECK (
        active_barrier_alert IS NULL OR char_length(active_barrier_alert) <= 400
    ),
    is_synthetic_sample BOOLEAN NOT NULL DEFAULT FALSE,
    last_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_venues_workspace_status ON public.venues(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_venues_category_city ON public.venues(category, city);
CREATE INDEX IF NOT EXISTS idx_venues_coords ON public.venues(latitude, longitude);

-- 4. Structured Access Attributes (1:1 per Venue, versioned via audit & observations)
CREATE TABLE IF NOT EXISTS public.access_attributes (
    venue_id UUID PRIMARY KEY REFERENCES public.venues(id) ON DELETE CASCADE,
    -- Entrance details
    step_free_entrance BOOLEAN NOT NULL DEFAULT FALSE,
    entrance_door_width_cm INTEGER NOT NULL CHECK (entrance_door_width_cm BETWEEN 40 AND 300),
    threshold_height_mm INTEGER NOT NULL DEFAULT 0 CHECK (threshold_height_mm BETWEEN 0 AND 250),
    door_opener_type TEXT NOT NULL CHECK (
        door_opener_type IN ('push_button', 'motion_sensor', 'manual_light', 'manual_heavy', 'open_archway')
    ),
    ramp_present BOOLEAN NOT NULL DEFAULT FALSE,
    ramp_slope_degrees DOUBLE PRECISION DEFAULT NULL CHECK (
        ramp_slope_degrees IS NULL OR (ramp_slope_degrees >= 0.0 AND ramp_slope_degrees <= 30.0)
    ),
    entrance_notes TEXT NOT NULL DEFAULT '' CHECK (char_length(entrance_notes) <= 500),
    -- Facility details
    accessible_restroom_type TEXT NOT NULL CHECK (
        accessible_restroom_type IN (
            'single_user_all_gender',
            'wheelchair_stall',
            'changing_places_hoist',
            'standard_only',
            'none'
        )
    ),
    grab_bars TEXT NOT NULL DEFAULT 'none' CHECK (
        grab_bars IN ('both_sides', 'left_only', 'right_only', 'none')
    ),
    turning_circle_cm INTEGER NOT NULL DEFAULT 150 CHECK (turning_circle_cm BETWEEN 0 AND 400),
    elevator_status TEXT NOT NULL DEFAULT 'none' CHECK (
        elevator_status IN ('operational', 'out_of_service', 'none')
    ),
    braille_tactile_signage BOOLEAN NOT NULL DEFAULT FALSE,
    hearing_loop_available BOOLEAN NOT NULL DEFAULT FALSE,
    quiet_sensory_space BOOLEAN NOT NULL DEFAULT FALSE,
    accessible_parking_spaces INTEGER NOT NULL DEFAULT 0 CHECK (accessible_parking_spaces BETWEEN 0 AND 500),
    -- Route & Interior details
    pathway_surface TEXT NOT NULL DEFAULT 'smooth_paved' CHECK (
        pathway_surface IN (
            'smooth_paved',
            'tactile_paving',
            'carpet_low_pile',
            'cobblestone',
            'gravel',
            'uneven'
        )
    ),
    min_corridor_width_cm INTEGER NOT NULL DEFAULT 120 CHECK (min_corridor_width_cm BETWEEN 50 AND 500),
    lighting_level TEXT NOT NULL DEFAULT 'bright_even' CHECK (
        lighting_level IN ('bright_even', 'moderate', 'dim', 'glare_heavy')
    ),
    acoustic_profile TEXT NOT NULL DEFAULT 'moderate' CHECK (
        acoustic_profile IN ('quiet', 'moderate', 'loud_echo')
    ),
    route_notes TEXT NOT NULL DEFAULT '' CHECK (char_length(route_notes) <= 500),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_access_attributes_filter
    ON public.access_attributes(step_free_entrance, entrance_door_width_cm, accessible_restroom_type, elevator_status);

-- 5. Timestamped Observations
CREATE TABLE IF NOT EXISTS public.observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    venue_id UUID NOT NULL REFERENCES public.venues(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    observer_role TEXT NOT NULL CHECK (
        observer_role IN (
            'person_with_access_need',
            'caregiver',
            'accessibility_advocate',
            'venue_operator',
            'auditor'
        )
    ),
    confidence_level TEXT NOT NULL CHECK (
        confidence_level IN (
            'verified_measurement',
            'direct_observation',
            'secondhand_report',
            'needs_reverification'
        )
    ),
    confidence_score INTEGER NOT NULL CHECK (confidence_score BETWEEN 10 AND 100),
    summary TEXT NOT NULL CHECK (char_length(summary) BETWEEN 10 AND 1000),
    measured_door_width_cm INTEGER DEFAULT NULL CHECK (
        measured_door_width_cm IS NULL OR (measured_door_width_cm BETWEEN 40 AND 300)
    ),
    elevator_operational_check TEXT DEFAULT NULL CHECK (
        elevator_operational_check IS NULL OR elevator_operational_check IN ('operational', 'out_of_service', 'not_applicable')
    ),
    barriers_noted TEXT NOT NULL DEFAULT '' CHECK (char_length(barriers_noted) <= 500),
    is_operational_alert BOOLEAN NOT NULL DEFAULT FALSE,
    is_synthetic_sample BOOLEAN NOT NULL DEFAULT FALSE,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_observations_venue_observed ON public.observations(venue_id, observed_at DESC);

-- 6. Consent-Reviewed Photo Evidence
CREATE TABLE IF NOT EXISTS public.photo_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    venue_id UUID NOT NULL REFERENCES public.venues(id) ON DELETE CASCADE,
    observation_id UUID REFERENCES public.observations(id) ON DELETE SET NULL,
    uploaded_by UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    category TEXT NOT NULL CHECK (
        category IN ('entrance', 'restroom', 'ramp_lift', 'signage', 'interior_route', 'parking')
    ),
    alt_text TEXT NOT NULL CHECK (char_length(alt_text) BETWEEN 10 AND 300),
    caption TEXT NOT NULL DEFAULT '' CHECK (char_length(caption) <= 300),
    storage_key TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL CHECK (mime_type IN ('image/png', 'image/jpeg', 'image/webp')),
    byte_size INTEGER NOT NULL CHECK (byte_size BETWEEN 64 AND 5242880),
    width_px INTEGER NOT NULL CHECK (width_px BETWEEN 16 AND 8192),
    height_px INTEGER NOT NULL CHECK (height_px BETWEEN 16 AND 8192),
    sha256_hash TEXT NOT NULL CHECK (char_length(sha256_hash) = 64),
    exif_stripped BOOLEAN NOT NULL DEFAULT TRUE,
    no_identifiable_faces_confirmed BOOLEAN NOT NULL CHECK (no_identifiable_faces_confirmed = TRUE),
    operator_or_public_area_consent BOOLEAN NOT NULL CHECK (operator_or_public_area_consent = TRUE),
    consent_status TEXT NOT NULL DEFAULT 'pending_review' CHECK (
        consent_status IN ('pending_review', 'approved_public', 'rejected_privacy')
    ),
    reviewed_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    review_notes TEXT NOT NULL DEFAULT '' CHECK (char_length(review_notes) <= 400),
    is_synthetic_sample BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_photo_evidence_venue_status ON public.photo_evidence(venue_id, consent_status);

-- 7. Moderation Reports
CREATE TABLE IF NOT EXISTS public.moderation_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    venue_id UUID NOT NULL REFERENCES public.venues(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL CHECK (target_type IN ('venue', 'observation', 'photo_evidence')),
    target_id UUID NOT NULL,
    reporter_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    reason TEXT NOT NULL CHECK (
        reason IN (
            'inaccurate_measurement',
            'privacy_face_visible',
            'outdated_barrier',
            'spam_or_abuse',
            'operator_dispute'
        )
    ),
    details TEXT NOT NULL CHECK (char_length(details) BETWEEN 10 AND 800),
    status TEXT NOT NULL DEFAULT 'open' CHECK (
        status IN ('open', 'investigating', 'resolved_upheld', 'resolved_dismissed')
    ),
    resolution_notes TEXT NOT NULL DEFAULT '' CHECK (char_length(resolution_notes) <= 600),
    resolved_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_moderation_status ON public.moderation_reports(status, created_at DESC);

-- 8. Saved Search Views
CREATE TABLE IF NOT EXISTS public.saved_views (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (char_length(name) BETWEEN 2 AND 80),
    filters_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 9. Notification Preferences
CREATE TABLE IF NOT EXISTS public.notification_preferences (
    user_id UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    barrier_alerts_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    stale_venue_digest_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    moderation_updates_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 10. Immutable Audit Events
CREATE TABLE IF NOT EXISTS public.audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    actor_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    action TEXT NOT NULL CHECK (char_length(action) BETWEEN 3 AND 80),
    target_type TEXT NOT NULL CHECK (char_length(target_type) BETWEEN 2 AND 60),
    target_id TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_workspace_created ON public.audit_events(workspace_id, created_at DESC);

-- ============================================================================
-- Row-Level Security (RLS) Policies — Deny by Default
-- ============================================================================
ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.venues ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.access_attributes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.photo_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.moderation_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.saved_views ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notification_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_events ENABLE ROW LEVEL SECURITY;

-- Published venues and their structured access attributes are readable; archived venues require workspace membership
CREATE POLICY venues_read_policy ON public.venues
    FOR SELECT USING (
        status != 'archived'
        OR created_by = auth.uid()
        OR EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = auth.uid() AND u.workspace_id = venues.workspace_id AND u.role IN ('moderator', 'admin', 'operator')
        )
    );

CREATE POLICY venues_write_policy ON public.venues
    FOR INSERT WITH CHECK (
        auth.uid() = created_by
        AND EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = auth.uid()
              AND u.workspace_id = venues.workspace_id
              AND u.role IN ('contributor', 'operator', 'moderator', 'admin')
        )
    );

CREATE POLICY venues_update_policy ON public.venues
    FOR UPDATE USING (
        created_by = auth.uid()
        OR EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = auth.uid()
              AND u.workspace_id = venues.workspace_id
              AND u.role IN ('operator', 'moderator', 'admin')
        )
    );

CREATE POLICY photo_evidence_read_policy ON public.photo_evidence
    FOR SELECT USING (
        consent_status = 'approved_public'
        OR uploaded_by = auth.uid()
        OR EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = auth.uid() AND u.role IN ('moderator', 'admin')
        )
    );

CREATE POLICY saved_views_owner_policy ON public.saved_views
    FOR ALL USING (user_id = auth.uid());

CREATE POLICY notification_preferences_owner_policy ON public.notification_preferences
    FOR ALL USING (user_id = auth.uid());

COMMIT;

