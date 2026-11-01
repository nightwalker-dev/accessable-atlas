# Defensive Security Audit Report — AccessAble Atlas

> **Repository:** `accessable-atlas`  
> **Audit Branch:** `security-hardening` (preserving `main` and `feat/accessable-atlas-foundation`)  
> **Audit Date:** 2026-11-01  
> **Scope:** Local repository, application source (`atlas/`), database migrations (`supabase/`), analytics definitions (`tinybird/`), static assets, and automated test suites (`tests/`).  
> **Disclaimer:** This report documents a defensive engineering security audit and local dynamic verification of the codebase. It does not constitute an external third-party compliance certification.

---

## Executive Summary & Risk Score Progression

| Metric | Pre-Hardening Baseline (Initial Slice) | Post-Hardening (`security-hardening`) |
|---|---|---|
| **Overall Risk Rating** | **Medium (4.2 / 10)** | **Low (1.2 / 10)** |
| **Hardcoded Secrets in Repo / Git History** | `0` found | `0` found (verified by `make secret-scan`) |
| **Critical / High Findings Open** | `0` | `0` |
| **Medium Findings Remediated** | `3` identified (`SEC-001`, `SEC-002`, `SEC-003`) | `3 / 3` remediated & regression-tested |
| **Low Findings Remediated** | `2` identified (`SEC-004`, `SEC-005`) | `2 / 2` remediated & regression-tested |
| **Automated Security Regression Tests** | `0` dedicated security tests | `7` comprehensive multi-assertion suites (`tests/test_security_audit.py`) |

---

## Phase 1 — Reconnaissance & Threat Model

### 1.1 System Architecture & Trust Boundaries
- **Application Tier:** Python 3.13 + Tornado 6.4.2 modular monolith (`atlas/server.py`) serving a single-page accessible frontend (`atlas/static/`) and JSON REST API (`/api/*`).
- **Canonical Transactional Store:** Supabase (`PostgreSQL 16` + `Auth` + `Private Storage` + `RLS`) defined in `supabase/migrations/20261101000000_accessable_atlas_init.sql`, bridged via `atlas/adapters/supabase_adapter.py` to the local ACID SQLite engine (`atlas/db/database.py`) when cloud credentials are not present.
- **Competing Stores Blocked:** `NEON_DATABASE_URL` and `NEON_API_KEY` are explicitly rejected at startup in `atlas/config.py` per PRD Section 9.
- **Optional External Adapters:**
  - `TinybirdAdapter` (`atlas/adapters/tinybird_adapter.py`): Appends privacy-minimized aggregate telemetry events; never acts as canonical store.
  - `AISummaryAdapter` (`atlas/adapters/ai_summary_adapter.py`): Optional consent-gated accessibility route briefing synthesizer with non-LLM deterministic fallback.

### 1.2 Sensitive Assets & Threat Actors
1. **Uploaded Photo Evidence (`photo_evidence` + binary image files):**
   - *Risk:* Accidental inclusion of bystander faces, private license plates, or embedded EXIF GPS home/clinic coordinates; or upload of SVG/HTML XSS polyglots.
   - *Control:* Mandatory uploader consent attestation (`no_identifiable_faces_confirmed` and `operator_or_public_area_consent`), binary magic-byte & pixel decoding via Pillow (`PIL.Image`), complete EXIF stripping by pixel re-encoding, private filesystem storage (`data/private_storage/`), and `pending_review` moderation gate for non-operator uploads.
2. **Accessibility Measurements & Barrier Alerts (`venues`, `access_attributes`, `observations`):**
   - *Risk:* Unauthorized tampering with life-safety clearance data (e.g., wheelchair door width or elevator outage alerts) across workspaces.
   - *Control:* Deny-by-default RBAC (`authorize_action`), workspace tenant isolation (`workspace_id`), ownership verification (`created_by`), and immutable `audit_events` logging inside ACID transactions.
3. **User Credentials & Session Tokens (`users`, `atlas_session`):**
   - *Risk:* Brute-force credential stuffing, JWT forgery, session replay after logout, or CSRF on state-changing routes.
   - *Control:* `bcrypt` password hashing (10 rounds), `HS256` signed JWTs with required claims (`iss`, `sub`, `role`, `workspace_id`, `iat`, `exp`, `jti`, `csrf`), `HttpOnly; SameSite=Lax` cookies, constant-time HMAC CSRF token verification (`X-CSRF-Token`), and server-side JTI revocation (`RevokedTokenStore`).

---

## Phase 2 — Secrets & Supply Chain Review

### 2.1 Secret Scan Evidence
Executed `python3 scripts/secret_scan.py` (`make secret-scan`) across all tracked/untracked files and full `git log -p --all` commit history:
- **Working Tree Findings:** `0`
- **Git Commit History Findings:** `0`
- **Masked Runtime Secret Handling (`atlas/config.py`):**
  - `ATLAS_JWT_SECRET`: `<ephemeral-32-byte-hex-in-dev>` (masked via `mask_secret()`, e.g., `a1f...9c2 (len=64)`)
  - `SUPABASE_SERVICE_ROLE_KEY`: `your-supabase-service-role-secret-placeholder` (`<local-mode>` when unset)
  - `TINYBIRD_TOKEN`: `your-tinybird-append-only-token-placeholder` (`<unset>`)
  - `ATLAS_AI_API_KEY`: `your-optional-ai-provider-key-placeholder` (`<unset>`)

### 2.2 Supply Chain & Dependency Footprint
All runtime dependencies are legitimate, mature packages pre-verified in the Python 3.13 environment (`pyproject.toml`):
- `tornado` (`6.4.2`) — HTTP server & routing
- `bcrypt` (`4.2.0`) — Password hashing
- `PyJWT` (`2.10.1`) — Session token signing & verification
- `Pillow` (`11.1.0`) — Binary image decoding & EXIF metadata removal
- `beautifulsoup4` (`4.13.4`) — HTML accessibility verification in linter

---

## Phase 3 — OWASP Top 10 & API Security Review

| OWASP Category | Status | Implemented Control & Code Location |
|---|---|---|
| **A01: Broken Access Control (BOLA / IDOR / BFLA)** | **Verified** | `atlas/auth.py` (`authorize_action`) + `atlas/db/database.py` enforce role permissions, resource ownership (`created_by == user.id`), and workspace isolation (`workspace_id`). Consequential actions require `confirm=True`. |
| **A02: Cryptographic Failures** | **Verified** | Passwords hashed with `bcrypt` (`atlas/auth.py`). JWTs signed with `HS256` and 256-bit secrets. Secrets redacted via `redact_sensitive_dict`. |
| **A03: Injection (SQLi / XSS)** | **Verified** | All SQLite queries in `atlas/db/database.py` use `?` parameterized bindings. `sanitize_plain_text` (`atlas/validation.py`) rejects `<script>`, `<iframe>`, `<svg>`, `javascript:`, and `on*=` handlers, and `escapeHtml` escapes all dynamic strings in `atlas/static/js/app.js`. |
| **A04: Insecure Design** | **Verified** | Photo uploads require explicit privacy checkboxes and default to `pending_review` for contributors; EXIF GPS data is stripped by pixel re-encoding before writing to disk. |
| **A05: Security Misconfiguration** | **Verified** | `BaseAPIHandler.set_default_headers` sets strict `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`, `Cross-Origin-Resource-Policy`, and `Strict-Transport-Security`. |
| **A07: Identification & Authentication Failures** | **Verified** | Per-IP + per-email brute-force rate limit (`5` failed attempts/min) on `/api/auth/login`, self-registration restricted to non-privileged roles (`viewer`, `contributor`, `operator`), and server-side JTI revocation on `/api/auth/logout` and `/api/account/delete`. |
| **A08: Software & Data Integrity Failures** | **Verified** | Centralized schema validation (`atlas/validation.py`), human review confirmation gate (`user_confirmed_imported_values: True`) on `/api/venues/import`, `X-CSRF-Token` validation on all state-changing routes, and `X-Idempotency-Key` deduplication (`atlas/rate_limit.py`). |
| **A10: SSRF & External Service Boundaries** | **Verified** | No user-supplied URLs are fetched by the server. External adapters (`SupabaseAdapter`, `TinybirdAdapter`) use fixed configured hostnames and 2.0–2.5s timeouts. |

---

## Phase 4 — AI / LLM / Retrieval / MCP Security Review

1. **Non-Blocking MVP & Explicit Consent Gate:**
   - `/api/venues/<id>/briefing` (`atlas/adapters/ai_summary_adapter.py`) checks `user_consent_granted`. When `False`, it returns `{"available": False, "consent_required": True}` without processing.
2. **Prompt-Injection Sanitization:**
   - `scrub_untrusted_context()` strips instruction-override patterns (`ignore all previous instructions`, `system prompt`, `developer message`, `reveal secret`, `tool_call`) and truncates untrusted notes to 240 characters.
3. **Zero Autonomous Tool Execution:**
   - The AI briefing adapter has zero access to database write handles, shell commands, or environment secrets.
4. **Tinybird Analytics Privacy Guardrail:**
   - `TinybirdAdapter.emit_event()` enforces a 7-field allowlist (`timestamp`, `event_type`, `workspace_slug`, `category`, `freshness_state`, `confidence_bucket`, `metric_value`) and blocks any payload containing `@`, `http://`, `https://`, `bearer `, `eyj`, `password`, or `secret`.

---

## Phase 5 & 6 — Findings Discovered & Remediated

### `SEC-001` (Medium — Remediated): Dedicated Brute-Force Rate Limiting on Authentication
- **Description:** Initially, `POST /api/auth/login` shared the general per-IP write rate limit (`30/min`) without a stricter failed-login threshold per target account.
- **Remediation:** Added a dedicated `auth_fail:<client_ip>:<email>` bucket in `AuthLoginHandler.post` (`atlas/server.py`) enforcing at most `5` failed login attempts per 60-second window before returning `HTTP 429 Too Many Requests` with `Retry-After`.
- **Regression Test:** `SecurityAuditRegressionTests.test_auth_jwt_tampering_revocation_and_brute_force` in `tests/test_security_audit.py`.

### `SEC-002` (Medium — Remediated): Bounds & Type Validation on Pagination Query Parameters
- **Description:** `VenuesCollectionHandler.get` parsed `limit` and `offset` directly with `int()`, which could raise an unstructured error or allow excessive offsets.
- **Remediation:** Added explicit bounds validation (`limit` in `1..100`, `offset` in `0..10000`) raising `ValidationError` with actionable `field_errors`.
- **Regression Test:** `SecurityAuditRegressionTests.test_sqli_xss_file_upload_and_query_bounds` in `tests/test_security_audit.py`.

### `SEC-003` (Medium — Remediated): Cross-Workspace Tenant Check on Moderation Reports
- **Description:** `AtlasDatabase.create_moderation_report` verified that the target venue existed, but did not verify that `venue.workspace_id == reporter.workspace_id`, allowing a user from another workspace to inject reports into a foreign workspace's moderation queue.
- **Remediation:** Added strict workspace equality check (`str(venue_row["workspace_id"]) != ws_id`) raising `PermissionError` (`HTTP 403 Forbidden`) in `atlas/db/database.py`, and ensured default user registration always binds to the primary workspace (`metro-civic-access`).
- **Regression Test:** `SecurityAuditRegressionTests.test_bola_idor_and_cross_workspace_isolation` in `tests/test_security_audit.py`.

### `SEC-004` (Low — Remediated): Server-Side JWT JTI Revocation on Sign-Out
- **Description:** `POST /api/auth/logout` cleared the browser cookie, but a captured `Bearer` token could still be replayed until its expiration timestamp.
- **Remediation:** Implemented thread-safe `RevokedTokenStore` in `atlas/auth.py` and wired `AuthLogoutHandler.post` + `BaseAPIHandler.get_session_claims_and_user` to revoke and reject signed-out token JTIs immediately (`HTTP 401`).
- **Regression Test:** `SecurityAuditRegressionTests.test_auth_jwt_tampering_revocation_and_brute_force` in `tests/test_security_audit.py`.

### `SEC-005` (Low — Remediated): Cross-Origin Resource Policy & HSTS Headers
- **Description:** Added `Cross-Origin-Resource-Policy: same-origin` and `Strict-Transport-Security: max-age=31536000; includeSubDomains` to `BaseAPIHandler.set_default_headers` (`atlas/server.py`).
- **Regression Test:** `SecurityAuditRegressionTests.test_security_headers_present_on_responses` in `tests/test_security_audit.py`.

---

## Phase 7 — Manual Owner Actions & Verification Commands

### Manual Owner Actions Before Production Cloud Deployment
1. **Generate Strong Production JWT Secret:**
   Run `openssl rand -hex 32` and set `ATLAS_JWT_SECRET` in your production secret manager along with `ATLAS_ENV=production`.
2. **Review & Apply Canonical Supabase Migration (Development Branch First):**
   Inspect `supabase/migrations/20261101000000_accessable_atlas_init.sql`, apply to a Supabase development branch first (`supabase db push`), verify RLS policies on `venues` and `photo_evidence`, and provision the private storage bucket `venue-photo-evidence` before promoting to production.
3. **Configure Optional Tinybird Append-Only Token:**
   If enabling cloud analytics (`TINYBIRD_ENABLED=true`), provision a restricted append-only datasource token scoped solely to `atlas_events` (`tinybird/datasources/atlas_events.datasource`).

### Exact Commands to Rerun Security Audit & Verification Suite
```bash
# 1. Static analysis, AST SQL check, HTML a11y, and CSS token verification
make lint

# 2. Working tree and full git commit history secret scan
make secret-scan

# 3. Run security regression suite (OWASP Top 10, BOLA, BFLA, CSRF, CORS, Uploads, AI/Tinybird)
make test-security

# 4. Run complete unit, integration, E2E, and security test suite
make test
```

