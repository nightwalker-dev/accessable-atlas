# Changelog

All notable changes to **AccessAble Atlas** (`accessable-atlas`) are documented in this file.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-11-01

### Added
- **Core Domain & Freshness Engine (`atlas/domain.py`):**
  - Canonical taxonomies for venue categories, door opener mechanisms, accessible restroom classifications (including Changing Places hoist facilities), grab bars, elevator statuses, pathway surfaces, lighting, acoustics, observer roles, and confidence levels.
  - Deterministic 4-state freshness state machine (`compute_freshness_indicator`: `fresh_verified`, `aging_review_soon`, `stale_reverify`, `active_alert`) with corroboration bonuses and non-color-only tokens (`check-shield`, `clock-amber`, `refresh-warning`, `alert-triangle`).
  - Personal accessibility requirement fit evaluator (`evaluate_accessibility_fit`).
- **Centralized Validation & EXIF Scrubbing (`atlas/validation.py`):**
  - Strict schema and numeric range validation for venues, structured access attributes, timestamped observations, moderation reports, saved search views, and privacy preferences.
  - Binary image magic-byte verification and Pillow pixel-buffer re-encoding (`validate_and_scrub_photo_upload`) stripping 100% of EXIF GPS and camera metadata while rejecting SVG/script polyglots.
  - Human-in-the-loop JSON import validator (`validate_venue_import_payload`) enforcing `user_confirmed_imported_values: True`.
  - Self-service account deletion/anonymization validator (`validate_account_deletion_payload`).
- **Authentication, RBAC & Defensive Security (`atlas/auth.py`, `atlas/rate_limit.py`, `atlas/server.py`):**
  - `bcrypt` password hashing, `HS256` JWT session tokens, server-side JTI revocation (`RevokedTokenStore`), and constant-time HMAC double-submit CSRF tokens (`X-CSRF-Token`).
  - Deny-by-default RBAC (`viewer`, `contributor`, `operator`, `moderator`, `admin`), ownership checks, workspace tenant isolation, and explicit confirmation (`confirm: true`) on consequential actions.
  - Per-IP and per-account failed-login brute-force rate limiting (`5` attempts/min → `HTTP 429`) and `X-Idempotency-Key` deduplication.
- **Canonical Supabase Schema & Local ACID SQLite Engine (`supabase/migrations/20261101000000_accessable_atlas_init.sql`, `atlas/db/database.py`):**
  - Full PostgreSQL 16 DDL and Row-Level Security (RLS) policies for `workspaces`, `users`, `venues`, `access_attributes`, `observations`, `photo_evidence`, `moderation_reports`, `saved_views`, `notification_preferences`, and `audit_events`.
  - Startup guardrail in `atlas/config.py` explicitly rejecting competing `NEON_DATABASE_URL` / `NEON_API_KEY` stores.
  - Privacy-minimized 7-field allowlisted `TinybirdAdapter` (`atlas/adapters/tinybird_adapter.py`) and consent-gated `AISummaryAdapter` (`atlas/adapters/ai_summary_adapter.py`) with deterministic non-LLM fallback.
- **Sage Circuit Accessible Frontend (`atlas/static/index.html`, `atlas/static/css/sage_circuit.css`, `atlas/static/js/app.js`):**
  - Full 9-color Sage Circuit palette anchored on Midnight Black `#030407` with WCAG AAA text contrast (`13.8:1`–`16.4:1`), `3px solid #D4FF24` `:focus-visible` outlines, `@media (prefers-reduced-motion: reduce)`, `200%` zoom reflow, modal focus trap, offline banner, and deep-link navigation (`?view=...&venue=...&role=...`).
  - Interactive SVG coordinate map (`+`, `-`, `1:1` zoom) with non-color geometric pin shapes (`circle`, `rounded-square`, `diamond`, `warning-triangle`).
- **Documentation, Benchmarks & Verification Suites:**
  - System design & ADRs (`DESIGN.md`), honest case study (`CASE_STUDY.md`), security audit report (`SECURITY_REPORT.md`), 60–90s live demo (`DEMO.md`, `scripts/run_demo.py`), multi-scale benchmark (`scripts/benchmark_performance.py`), screenshot generator (`scripts/capture_screenshots.py`), linter (`scripts/lint_and_typecheck.py`), secret scanner (`scripts/secret_scan.py`), and 17 automated test suites (`tests/`).

### Fixed & Optimized
- **Database Performance:** Replaced per-venue N+1 query hydration in `AtlasDatabase.list_venues()` (`202` `SELECT` queries for 50 venues) with a single SQL `LEFT JOIN` + composite index `idx_access_attributes_filter`, reducing SQL `SELECT` queries to `2` (**99.0% reduction**) and cutting mean latency by **44.9%**.
- **Security Hardening (`SEC-001`–`SEC-005`):** Added failed-login rate limiting, pagination integer bounds (`limit` `1..100`, `offset` `0..10000`), cross-workspace moderation report rejection, JWT JTI revocation on logout/account deletion, and `Cross-Origin-Resource-Policy` / `Strict-Transport-Security` headers.

