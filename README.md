<div align="center">

# 🌍 AccessAble Atlas

### *Find places through the details that matter.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-brightgreen.svg)](pyproject.toml)
[![Design System: Sage Circuit](https://img.shields.io/badge/design%20system-Sage%20Circuit-D4FF24.svg)](DESIGN.md)
[![Accessibility: WCAG 2.1 AA](https://img.shields.io/badge/accessibility-WCAG%202.1%20AA-1558C9.svg)](atlas/static/css/sage_circuit.css)
[![Tests: 100% Pass (19/19)](https://img.shields.io/badge/tests-19%2F19%20passed-D4FF24.svg)](tests/)
[![Security: 0 Secrets Detected](https://img.shields.io/badge/security-0%20secrets-brightgreen.svg)](scripts/secret_scan.py)

**AccessAble Atlas** is a community-driven, privacy-first civic accessibility directory engineered for people with lived access needs, wheelchair users, caregivers, venue operators, and civic advocates. 

[Explore Live Demo](#-quickstart--installation) • [Marketing Overview](#-why-accessable-atlas-marketing-overview) • [Google Maps & Earth Integration](#-google-maps-platform--google-earth-3d-integration) • [System Architecture](DESIGN.md) • [Engineering Case Study](CASE_STUDY.md)

</div>

---

## 🌟 Why AccessAble Atlas? (Marketing Overview)

### The Problem: When "Accessible" Doesn't Mean Accessible
Mainstream mapping apps and review platforms reduce physical accessibility to a single, unverified binary checkbox: *"Wheelchair Accessible: Yes"*. 

In the real world, that "Yes" often conceals unexpected hazards:
- A single **7 cm entrance step** that blocks a 180 kg power wheelchair.
- A **74 cm narrow bathroom doorway** that prevents a manual wheelchair from entering.
- A **broken station elevator** with zero notice before you arrive.
- High-glare direct lighting or deafening echo in spaces labeled "family-friendly".

For over 1.3 billion disabled people worldwide and their families, an unverified label isn't just an inconvenience—it's a canceled trip, stranded commute, or safety hazard.

### The Solution: Precision, Provenance & Observation Confidence
**AccessAble Atlas replaces vague checkboxes with verified physical specifications.** Every venue documents:
- **Exact Measurements:** Millimeter-accurate entrance threshold heights, laser-measured clear door widths, ramp slopes ($1:12$ ADA grade checks), and restroom turning circles.
- **Timestamped Observation Ledger:** Who checked the venue, when, with what tool, and under what perspective (lived experience, caregiver, operator, or certified auditor).
- **Deterministic Freshness Engine:** An automated decay state machine that flags stale data after 30 and 90 days, with instant **Active Barrier Alerts** when elevators break or ramps are blocked.
- **Google Maps & Google Earth 3D Exploration:** Instant transit directions, curb-level Street View 360° entrance panoramas, and aerial 3D flyovers with OGC KML 2.2 export.
- **Sage Circuit Accessible Design:** Built from the ground up for high-contrast accessibility (WCAG 2.1 AA, 13.8:1 contrast text, keyboard focus traps, 200% zoom reflow, and never relying on color alone for meaning).

---

## 🗺️ Google Maps Platform & Google Earth 3D Integration

AccessAble Atlas seamlessly integrates Google Maps Platform and Google Earth 3D into every venue profile:

1. **Google Maps Wheelchair Transit Routing:** Direct deep-link launching turn-by-turn public transit and accessible walking routes calculated for your exact mobility profile.
2. **Google Street View 360° Curb & Entrance Panoramas:** Direct camera positioning with pre-computed compass headings pointing straight at the primary entrance for pre-trip curb-cut inspections.
3. **ADA 1:12 Curb-to-Entrance Grade Analyzer:** Evaluates ramp slope ($\le 4.8^\circ$ / $8.33\%$ grade) and threshold lip ($\le 13\text{ mm}$ beveled limit) against ADA Standards and ISO 21542.
4. **Google Earth 3D Aerial Web Flyovers:** Direct `<LookAt>` camera positioning with $55^\circ$ tilt, calculated altitude, and 3D terrain exploration.
5. **OGC KML 2.2 3D Export:** Download native `.kml` files (`/api/venues/:id/earth.kml` and `/api/export/earth.kml`) embedding Sage Circuit semantic pins and structured accessibility ExtendedData for Google Earth desktop and mobile.

---

## 📦 Core Domain Modules (`modules/*`)

AccessAble Atlas is organized into 8 modular domain slices, each governed by Zod-style boundary schemas:

| Module | Purpose |
| :--- | :--- |
| **[`modules/venue-profiles`](modules/venue-profiles)** | Venue profiles, geospatial coordinates, operating hours, active barrier alerts, confirmed JSON import, and lifecycle states (`published`, `under_review`, `archived`). |
| **[`modules/structured-access-attributes`](modules/structured-access-attributes)** | 20 strongly-typed entrance, restroom, lift, and sensory attributes + personal accessibility fit evaluation. |
| **[`modules/timestamped-observations`](modules/timestamped-observations)** | Append-only community observations, confidence scoring ($95\%$ to $35\%$), doorway width updates, and barrier alert propagation. |
| **[`modules/consent-reviewed-photo-evidence`](modules/consent-reviewed-photo-evidence)** | Privacy-first photo uploads with mandatory consent checkboxes, descriptive `alt_text`, Pillow EXIF GPS removal, and moderator approval queue. |
| **[`modules/freshness-indicators`](modules/freshness-indicators)** | Deterministic 4-state freshness engine (`fresh_verified` `[✓]`, `aging_review_soon` `[◷]`, `stale_reverify` `[↻]`, `active_alert` `[!]`). |
| **[`modules/map-and-list-search`](modules/map-and-list-search)** | Synchronized vector map and list search with SQL predicate pushdown (2 SQL queries at any scale) and user-persisted Saved Views. |
| **[`modules/moderation`](modules/moderation)** | Inaccuracy and privacy flagging, moderator resolution workflows, and immutable workspace audit logs. |
| **[`modules/google-maps-earth-geospatial`](modules/google-maps-earth-geospatial)** | Google Maps Transit, Street View 360° curb view, Google Earth 3D flyovers, ADA grade checks, and KML export. |

---

## 🚀 Quickstart & Installation

### Prerequisites
- **Python:** `3.11`, `3.12`, or `3.13`
- **Git**

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/accessable-atlas.git
cd accessable-atlas
```

### 2. Set Up a Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
# Or use the Makefile:
make install
```

### 4. Configure Environment Variables
```bash
cp .env.example .env
```
*(Optional)* Add your `GOOGLE_MAPS_API_KEY` or `SUPABASE_URL` to `.env`. AccessAble Atlas operates with full functionality out of the box using its built-in ACID SQLite engine and deterministic geospatial/KML adapter even without external API keys.

### 5. Run Verification Suite
```bash
# Run linting, accessibility checks, and secret scan:
make lint
make secret-scan

# Run all 19 automated test suites:
make test
```

### 6. Launch the Application
```bash
make start
# Or directly:
python3 -m atlas
```

Open your browser to:
👉 **`http://127.0.0.1:8080`**

---

## 👥 Seeded Evaluation Personas

To test different roles immediately, use the quick-switcher bar at the top of the app or log in with password **`AtlasDemo!2026`**:

| Persona | Email | Role | Core Capabilities |
| :--- | :--- | :--- | :--- |
| **Maya Chen** | `maya.chen@atlas-demo.local` | `contributor` | Document venues, log observations, upload photos, flag issues, save views, export data. |
| **Alex Rivera** | `alex.rivera@atlas-demo.local` | `operator` | Document operator-verified venues, auto-approved facility diagrams. |
| **Samira Khan** | `samira.khan@atlas-demo.local` | `moderator` | Moderation queue, approve/reject photo evidence, resolve flags, view audit trail. |
| **Jordan Lee** | `jordan.lee@atlas-demo.local` | `viewer` | Explore directory, test personal accessibility filters, request consent-gated briefings. |

---

## 📊 Performance & Benchmarks

Run the reproducible benchmark anytime with `make benchmark`:

| Dataset Scale (`N` Venues) | SQL `SELECT`s (Optimized `LEFT JOIN`) | Legacy N+1 `SELECT`s ($1+4N+1$) | Query Reduction | `list_venues` Mean Latency | 6-Facet Filter Mean |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **10 venues** | **2** | 42 | **95.2%** | 1.14 ms | 0.90 ms |
| **50 venues** | **2** | 202 | **99.0%** | 2.65 ms | 1.37 ms |
| **100 venues** | **2** | 402 | **99.5%** | 4.87 ms | 1.89 ms |
| **250 venues** | **2** | 1002 | **99.8%** | 13.88 ms | 3.98 ms |

---

## 🔒 Security & Privacy Posture

- **100% EXIF Scrubbing:** Uploaded images are re-encoded through Pillow pixel data buffers to strip all embedded GPS coordinates and device metadata.
- **Double-Submit CSRF & HS256 JWTs:** Constant-time `hmac.compare_digest` verification and server-side JTI revocation store.
- **Zero Committed Secrets:** Verified via `make secret-scan` across both working tree and git history.
- **GDPR Self-Service Account Anonymization:** `POST /api/account/delete` scrubs personal PII while preserving public civic measurements as `"Anonymized Community Member"`.

---

## 📄 License & Documentation

- [DESIGN.md](DESIGN.md) — System Architecture, 5 Layers, and 7 Architecture Decision Records (ADRs).
- [CASE_STUDY.md](CASE_STUDY.md) — Technical case study, trade-offs, and lessons learned.
- [DEMO.md](DEMO.md) & [`scripts/run_demo.py`](scripts/run_demo.py) — 60-to-90 second presenter walkthrough script (`make demo`).
- [SECURITY_REPORT.md](SECURITY_REPORT.md) — Comprehensive defensive security audit.
- [LICENSE](LICENSE) — MIT License.
