# 60-to-90 Second Live Demo Script — AccessAble Atlas

**Target Duration:** `60–90 seconds`  
**Interactive Browser Entry:** `make start` → open `http://127.0.0.1:8080`  
**Automated Live HTTP Demo Runner:** `make demo` (or `python3 scripts/run_demo.py`)

---

## Timed Walkthrough Script (Browser + Terminal)

### `0:00 – 0:15` · Problem & First Impression (Journey A: Directory & Non-Color Freshness)
- **Open:** `http://127.0.0.1:8080/?view=directory`
- **What to show:**
  1. Point out the **Sage Circuit** Midnight Black (`#030407`) interface and the synchronized **SVG Coordinate Map + Venue Cards**.
  2. Highlight how every venue displays a **non-color-only freshness badge** (`[✓] Fresh · Verified`, `[◷] Aging`, `[↻] Stale`, `[!] Active Barrier Alert`) paired with distinct geometric map pin shapes (circle, square, diamond, triangle) and explicit `Synthetic Sample · For Evaluation` provenance pills.
  3. Toggle the **Step-Free Entrance** checkbox and set **Min Door Width (`cm`)** to `95` → click **Apply Filters** to filter the map and list in `<3 ms`.

### `0:15 – 0:40` · Inspecting Physical Specs & Submitting a Live Barrier Observation (Journey B)
- **Open:** `http://127.0.0.1:8080/?view=venue-detail` (or click **Inspect Details & Evidence →** on *Central Civic Library & Archive*).
- **What to show:**
  1. Walk through the **3-Column Structured Access Specification Sheet**: `112 cm` clear doorway width, `0 mm` threshold bevel, automatic motion-sensor door, Changing Places hoist restroom (`210 cm` turning circle), and tactile paving.
  2. In **Log a Timestamped Observation**, select `Person with Lived Access Need` and `Tape/Laser Measured on Site (95%)`, set **Elevator Check** to `Out of Service (Alert)`, check **Flag as Active Operational Barrier Alert**, and click **Submit Timestamped Observation**.
  3. Point out the immediate transition of the venue's freshness badge to **`[!] Active Barrier Alert`** and the new entry in **Provenance & Audit History**.

### `0:40 – 1:00` · Human-Confirmed JSON Import & EXIF-Scrubbed Photo Upload (Journey B.3)
- **Open:** `http://127.0.0.1:8080/?view=create-venue`
- **What to show:**
  1. Expand **Import Venue Profile from Structured JSON (Requires Human Review & Confirmation)** → click **Load Sample Municipal JSON** → click **Parse & Pre-Fill Form for Human Review**.
  2. Show the mandatory human confirmation checkbox (`I have inspected the imported measurements above and confirm their accuracy before publishing`) enforced by `POST /api/venues/import`, check it, and click **Confirm & Publish Imported Venue Profile**.
  3. On the newly created venue detail page, click **Scrub EXIF & Upload Photo Evidence** to demonstrate automatic Pillow pixel re-encoding (`EXIF Stripped: ✓`) and `pending_review` privacy gating.

### `1:00 – 1:25` · Moderator Queue Resolution, Freshness Insights & Data Portability (Journey C)
- **Open:** `http://127.0.0.1:8080/?view=moderation&role=moderator` (or click **Moderator (Samira)** in the top Quick Role Switcher).
- **What to show:**
  1. In **Moderation & Audit**, check **Confirm Consent Decision** on the pending photo upload and click **Approve Public**, then resolve the open moderation report (`Uphold Flag`) while inspecting the **Immutable Workspace Audit Trail**.
  2. Click **3. Freshness & Insights** (`/?view=insights`) to show the **Insight Provenance, Methodology & Limitations** banner, the 6 clearance metric tiles, and the list of records requiring re-verification.
  3. Click **5. Privacy & Export** (`/?view=settings`) to show **Workspace Data Portability Export (`POST /api/export`)** and **Self-Service Account & Personal Data Deletion/Anonymization (`POST /api/account/delete`)**.

---

## Reproducible Terminal Demo (`make demo`)

To run the entire 5-stage journey programmatically against an in-process Tornado HTTP server and inspect real HTTP status codes, JSON responses, and latencies:

```bash
python3 scripts/run_demo.py
```

