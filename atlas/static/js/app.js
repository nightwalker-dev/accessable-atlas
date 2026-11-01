/**
 * AccessAble Atlas — Interactive Client Application (Sage Circuit Design System)
 * Connects all core workflows end-to-end with strict CSRF headers, safe DOM escaping,
 * keyboard accessibility, ARIA live announcements, and non-color-only freshness semantics.
 */

(function () {
  "use strict";

  const state = {
    user: null,
    csrfToken: "",
    authToken: "",
    taxonomies: {},
    venues: [],
    availableCities: [],
    selectedVenue: null,
    savedViews: [],
    settings: null,
    splitMapVisible: true,
    activeView: "directory",
    mapZoom: 1.0,
    lastFocusedElement: null,
  };

  function escapeHtml(value) {
    if (value === null || value === undefined) {
      return "";
    }
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function announce(message) {
    const live = document.getElementById("aria-live-announcer");
    if (live) {
      live.textContent = message;
    }
  }

  function showStatus(message, type) {
    const banner = document.getElementById("global-status-banner");
    const textEl = document.getElementById("global-status-text");
    if (!banner || !textEl) return;
    banner.className = "status-banner " + (type || "");
    textEl.textContent = message;
    banner.hidden = false;
    announce(message);
  }

  function hideStatus() {
    const banner = document.getElementById("global-status-banner");
    if (banner) banner.hidden = true;
  }

  async function apiRequest(path, options) {
    const opts = options || {};
    const method = (opts.method || "GET").toUpperCase();
    const headers = Object.assign({}, opts.headers || {});

    if (state.authToken) {
      headers["Authorization"] = "Bearer " + state.authToken;
    }
    if (method !== "GET" && method !== "HEAD" && state.csrfToken) {
      headers["X-CSRF-Token"] = state.csrfToken;
    }
    if (opts.idempotencyKey) {
      headers["X-Idempotency-Key"] = opts.idempotencyKey;
    }

    let body = opts.body;
    if (body && typeof body === "object" && !(body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }

    const resp = await fetch(path, {
      method: method,
      headers: headers,
      body: body,
      credentials: "same-origin",
    });

    let data = {};
    const contentType = resp.headers.get("Content-Type") || "";
    if (contentType.includes("application/json")) {
      data = await resp.json();
    }
    if (!resp.ok) {
      const err = new Error(data.message || "Request failed with status " + resp.status);
      err.status = resp.status;
      err.fieldErrors = data.field_errors || {};
      throw err;
    }
    return data;
  }

  function freshnessSymbol(freshnessState) {
    if (freshnessState === "fresh_verified") return "✓";
    if (freshnessState === "aging_review_soon") return "◷";
    if (freshnessState === "stale_reverify") return "↻";
    if (freshnessState === "active_alert") return "!";
    return "•";
  }

  // ==========================================================================
  // View Navigation
  // ==========================================================================

  function switchView(viewName) {
    state.activeView = viewName;
    const views = ["directory", "create-venue", "venue-detail", "insights", "moderation", "settings"];
    views.forEach(function (v) {
      const section = document.getElementById("view-" + v);
      if (section) {
        section.classList.toggle("active", v === viewName);
      }
      const tab = document.querySelector('.nav-tab[data-view="' + v + '"]');
      if (tab) {
        const isActive = v === viewName;
        tab.classList.toggle("active", isActive);
        if (isActive) {
          tab.setAttribute("aria-current", "page");
        } else {
          tab.removeAttribute("aria-current");
        }
      }
    });

    if (viewName === "insights") {
      loadInsights();
    } else if (viewName === "moderation") {
      loadModerationQueue();
    } else if (viewName === "settings") {
      loadSettingsAndHealth();
    }
  }

  // ==========================================================================
  // Taxonomies & Select Population
  // ==========================================================================

  function populateSelect(selectId, mapObj, includeAllOption) {
    const el = document.getElementById(selectId);
    if (!el || !mapObj) return;
    let html = "";
    if (includeAllOption) {
      html += '<option value="all">All Categories</option>';
    }
    Object.keys(mapObj).forEach(function (key) {
      html += '<option value="' + escapeHtml(key) + '">' + escapeHtml(mapObj[key]) + "</option>";
    });
    el.innerHTML = html;
  }

  async function initMetadata() {
    const meta = await apiRequest("/api/meta/taxonomies");
    state.taxonomies = meta;
    populateSelect("filter-category", meta.venue_categories, true);
    populateSelect("vf-category", meta.venue_categories, false);
    populateSelect("vf-door-opener", meta.door_opener_types, false);
    populateSelect("vf-restroom", meta.restroom_types, false);
    populateSelect("vf-grab-bars", meta.grab_bar_types, false);
    populateSelect("vf-elevator", meta.elevator_statuses, false);
    populateSelect("vf-surface", meta.pathway_surfaces, false);
    populateSelect("vf-lighting", meta.lighting_levels, false);
    populateSelect("vf-acoustics", meta.acoustic_profiles, false);

    const health = await apiRequest("/api/health");
    const dbIndicator = document.getElementById("db-mode-indicator");
    if (dbIndicator && health.canonical_database) {
      dbIndicator.textContent =
        "Supabase (" + health.canonical_database.mode + " · RLS migration ready)";
    }
  }

  // ==========================================================================
  // Session & Authentication
  // ==========================================================================

  function updateSessionUI() {
    const pill = document.getElementById("current-user-pill");
    const btnLogout = document.getElementById("btn-logout");
    const btnOpenAuth = document.getElementById("btn-open-auth");
    if (state.user) {
      pill.textContent =
        state.user.display_name + " [" + state.user.role.toUpperCase() + "]";
      btnLogout.hidden = false;
      btnOpenAuth.textContent = "Switch Account";
    } else {
      pill.textContent = "Guest Reader (Read-Only)";
      btnLogout.hidden = true;
      btnOpenAuth.textContent = "Sign In / Switch Role";
    }
    renderSavedViewsBar();
  }

  async function checkCurrentSession() {
    try {
      const data = await apiRequest("/api/auth/me");
      if (data.authenticated && data.user) {
        state.user = data.user;
        state.csrfToken = data.csrf_token || "";
        state.savedViews = data.saved_views || [];
        state.settings = data.settings || null;
      } else {
        // Auto-sign in as Maya Chen (Contributor) on first visit so interactive workflows work immediately
        await loginWithCredentials("maya.chen@atlas-demo.local", "AtlasDemo!2026", true);
      }
    } catch (_err) {
      state.user = null;
    }
    updateSessionUI();
  }

  async function loginWithCredentials(email, password, silent) {
    const data = await apiRequest("/api/auth/login", {
      method: "POST",
      body: { email: email, password: password },
    });
    state.user = data.user;
    state.csrfToken = data.csrf_token;
    state.authToken = data.token;
    state.savedViews = data.saved_views || [];
    state.settings = data.settings || null;
    updateSessionUI();
    closeAuthModal();
    if (!silent) {
      showStatus(
        "Signed in as " + data.user.display_name + " (" + data.user.role + ").",
        "success"
      );
    }
    await loadVenues();
    if (state.activeView === "moderation") {
      await loadModerationQueue();
    } else if (state.activeView === "venue-detail" && state.selectedVenue) {
      await openVenueDetail(state.selectedVenue.id);
    }
  }

  function openAuthModal() {
    const modal = document.getElementById("auth-modal");
    if (modal) {
      state.lastFocusedElement = document.activeElement;
      modal.hidden = false;
      const emailInput = document.getElementById("auth-email");
      if (emailInput) emailInput.focus();
    }
  }

  function closeAuthModal() {
    const modal = document.getElementById("auth-modal");
    if (modal && !modal.hidden) {
      modal.hidden = true;
      if (state.lastFocusedElement && typeof state.lastFocusedElement.focus === "function") {
        state.lastFocusedElement.focus();
      }
    }
  }

  // ==========================================================================
  // Directory Search, Filtering, Saved Views & Vector Map
  // ==========================================================================

  function collectFilterParams() {
    const q = (document.getElementById("filter-q").value || "").trim();
    const category = document.getElementById("filter-category").value || "all";
    const cityEl = document.getElementById("filter-city");
    const city = cityEl ? cityEl.value || "all" : "all";
    const freshness = document.getElementById("filter-freshness").value || "all";
    const minDoor = (document.getElementById("filter-min-door").value || "").trim();
    const stepFree = document.getElementById("filter-step-free").checked;
    const restroom = document.getElementById("filter-restroom").checked;
    const elevator = document.getElementById("filter-elevator").checked;
    const quiet = document.getElementById("filter-quiet").checked;
    const hearing = document.getElementById("filter-hearing").checked;
    const braille = document.getElementById("filter-braille").checked;
    const archivedEl = document.getElementById("filter-archived");
    const includeArchived = archivedEl ? archivedEl.checked : false;

    const params = {};
    if (q) params.q = q;
    if (category && category !== "all") params.category = category;
    if (city && city !== "all") params.city = city;
    if (freshness && freshness !== "all") params.freshness = freshness;
    if (minDoor) params.min_door_width_cm = parseInt(minDoor, 10);
    if (stepFree) params.step_free = true;
    if (restroom) params.accessible_restroom = true;
    if (elevator) params.elevator_operational = true;
    if (quiet) params.quiet_space = true;
    if (hearing) params.hearing_loop = true;
    if (braille) params.braille_signage = true;
    if (includeArchived) params.include_archived = true;
    return params;
  }

  function applyFilterParamsToForm(filters) {
    const f = filters || {};
    document.getElementById("filter-q").value = f.q || "";
    document.getElementById("filter-category").value = f.category || "all";
    const cityEl = document.getElementById("filter-city");
    if (cityEl) cityEl.value = f.city || "all";
    document.getElementById("filter-freshness").value = f.freshness || "all";
    document.getElementById("filter-min-door").value = f.min_door_width_cm || "";
    document.getElementById("filter-step-free").checked = Boolean(f.step_free);
    document.getElementById("filter-restroom").checked = Boolean(f.accessible_restroom);
    document.getElementById("filter-elevator").checked = Boolean(f.elevator_operational);
    document.getElementById("filter-quiet").checked = Boolean(f.quiet_space);
    document.getElementById("filter-hearing").checked = Boolean(f.hearing_loop);
    document.getElementById("filter-braille").checked = Boolean(f.braille_signage);
    const archivedEl = document.getElementById("filter-archived");
    if (archivedEl) archivedEl.checked = Boolean(f.include_archived);
  }

  function updateCitySelectOptions(cities) {
    const citySelect = document.getElementById("filter-city");
    if (!citySelect || !Array.isArray(cities)) return;
    const currentVal = citySelect.value || "all";
    let html = '<option value="all">All Cities</option>';
    cities.forEach(function (c) {
      html += '<option value="' + escapeHtml(c) + '">' + escapeHtml(c) + "</option>";
    });
    citySelect.innerHTML = html;
    if (cities.indexOf(currentVal) !== -1 || currentVal === "all") {
      citySelect.value = currentVal;
    }
  }

  async function loadVenues() {
    const params = collectFilterParams();
    const qs = new URLSearchParams();
    Object.keys(params).forEach(function (k) {
      qs.set(k, String(params[k]));
    });
    const url = "/api/venues" + (qs.toString() ? "?" + qs.toString() : "");
    const data = await apiRequest(url);
    state.venues = data.items || [];
    if (data.available_cities) {
      state.availableCities = data.available_cities;
      updateCitySelectOptions(data.available_cities);
    }
    renderVenuesList();
    renderVectorMap();
  }

  function renderSavedViewsBar() {
    const listEl = document.getElementById("saved-views-list");
    if (!listEl) return;
    if (!state.savedViews || state.savedViews.length === 0) {
      listEl.innerHTML = '<span style="font-size: 0.78rem; color: var(--text-secondary);">None saved yet</span>';
      return;
    }
    listEl.innerHTML = state.savedViews
      .map(function (sv) {
        return (
          '<span style="display: inline-flex; align-items: center; gap: 2px;">' +
          '<button type="button" class="btn btn-xs" data-load-view="' +
          escapeHtml(sv.id) +
          '">' +
          escapeHtml(sv.name) +
          "</button>" +
          '<button type="button" class="btn btn-xs btn-danger" data-delete-view="' +
          escapeHtml(sv.id) +
          '" aria-label="Delete saved view ' +
          escapeHtml(sv.name) +
          '">×</button>' +
          "</span>"
        );
      })
      .join("");
  }

  function applyMapZoom() {
    const svg = document.getElementById("atlas-vector-map");
    if (!svg) return;
    const z = Math.max(0.75, Math.min(2.25, state.mapZoom || 1.0));
    const w = Math.round(420 / z);
    const h = Math.round(340 / z);
    const x = Math.round((420 - w) / 2);
    const y = Math.round((340 - h) / 2);
    svg.setAttribute("viewBox", x + " " + y + " " + w + " " + h);
  }

  function renderVectorMap() {
    const svg = document.getElementById("atlas-vector-map");
    if (!svg) return;
    applyMapZoom();
    const venues = state.venues;

    let gridHtml =
      '<rect width="420" height="340" fill="#030407" />' +
      '<g stroke="rgba(165, 167, 155, 0.16)" stroke-width="1">' +
      '<line x1="0" y1="68" x2="420" y2="68" />' +
      '<line x1="0" y1="136" x2="420" y2="136" />' +
      '<line x1="0" y1="204" x2="420" y2="204" />' +
      '<line x1="0" y1="272" x2="420" y2="272" />' +
      '<line x1="84" y1="0" x2="84" y2="340" />' +
      '<line x1="168" y1="0" x2="168" y2="340" />' +
      '<line x1="252" y1="0" x2="252" y2="340" />' +
      '<line x1="336" y1="0" x2="336" y2="340" />' +
      "</g>" +
      '<path d="M 35 15 Q 95 140 70 330" stroke="rgba(21, 88, 201, 0.45)" stroke-width="14" fill="none" />' +
      '<text x="14" y="326" fill="#A5A79B" font-family="monospace" font-size="10">ELLIOTT BAY WATERFRONT</text>';

    if (venues.length === 0) {
      gridHtml +=
        '<text x="210" y="170" text-anchor="middle" fill="#E8D2B5" font-size="13">No matching venues in map bounds</text>';
      svg.innerHTML = gridHtml;
      return;
    }

    const lats = venues.map(function (v) { return v.latitude; });
    const lngs = venues.map(function (v) { return v.longitude; });
    const minLat = Math.min.apply(null, lats) - 0.008;
    const maxLat = Math.max.apply(null, lats) + 0.008;
    const minLng = Math.min.apply(null, lngs) - 0.008;
    const maxLng = Math.max.apply(null, lngs) + 0.008;

    venues.forEach(function (venue, idx) {
      const normX = (venue.longitude - minLng) / Math.max(0.0001, maxLng - minLng);
      const normY = 1 - (venue.latitude - minLat) / Math.max(0.0001, maxLat - minLat);
      const cx = Math.round(45 + normX * 330);
      const cy = Math.round(35 + normY * 265);
      const fState = venue.freshness.state;
      const sym = freshnessSymbol(fState);

      let shapeSvg = "";
      if (fState === "fresh_verified") {
        shapeSvg =
          '<circle cx="' + cx + '" cy="' + cy + '" r="13" fill="#030407" stroke="#D4FF24" stroke-width="2.5" />';
      } else if (fState === "aging_review_soon") {
        shapeSvg =
          '<rect x="' + (cx - 12) + '" y="' + (cy - 12) + '" width="24" height="24" rx="4" fill="#030407" stroke="#E8D2B5" stroke-width="2.5" />';
      } else if (fState === "stale_reverify") {
        shapeSvg =
          '<polygon points="' +
          cx + "," + (cy - 14) + " " +
          (cx + 14) + "," + cy + " " +
          cx + "," + (cy + 14) + " " +
          (cx - 14) + "," + cy +
          '" fill="#400849" stroke="#E7B0DE" stroke-width="2.2" />';
      } else {
        shapeSvg =
          '<polygon points="' +
          cx + "," + (cy - 15) + " " +
          (cx + 15) + "," + (cy + 12) + " " +
          (cx - 15) + "," + (cy + 12) +
          '" fill="#590907" stroke="#FF5A0A" stroke-width="2.5" />';
      }

      gridHtml +=
        '<g class="map-pin-group" tabindex="0" role="button" data-venue-id="' +
        escapeHtml(venue.id) +
        '" aria-label="' +
        escapeHtml(
          (idx + 1) + ". " + venue.name + " (" + venue.freshness.label + ", Door " + venue.access_attributes.entrance_door_width_cm + " cm)"
        ) +
        '" style="cursor: pointer;">' +
        shapeSvg +
        '<text x="' +
        cx +
        '" y="' +
        (cy + 4) +
        '" text-anchor="middle" fill="#F7EFE4" font-family="monospace" font-size="11" font-weight="bold">' +
        sym +
        "</text>" +
        '<text x="' +
        (cx + 17) +
        '" y="' +
        (cy + 4) +
        '" fill="#E8D2B5" font-size="10" font-weight="600">' +
        escapeHtml(venue.name.slice(0, 20)) +
        "</text>" +
        "</g>";
    });

    svg.innerHTML = gridHtml;
  }

  function renderVenuesList() {
    const container = document.getElementById("venue-list-container");
    const countSummary = document.getElementById("results-count-summary");
    if (!container || !countSummary) return;

    const total = state.venues.length;
    countSummary.textContent =
      total === 1
        ? "Showing 1 documented venue matching your accessibility criteria"
        : "Showing " + total + " documented venues matching your accessibility criteria";

    if (total === 0) {
      container.innerHTML =
        '<div class="spec-card" style="text-align: center;">' +
        '<h3 style="margin-top: 0; color: var(--color-warm-cream);">No venues match the current filter combination</h3>' +
        '<p style="color: var(--text-secondary); font-size: 0.9rem;">Try broadening minimum door width or resetting active filters, or document a new place in the directory.</p>' +
        '<div style="display: flex; gap: 0.75rem; justify-content: center; margin-top: 1rem;">' +
        '<button type="button" class="btn" id="btn-empty-reset">Reset All Filters</button>' +
        '<button type="button" class="btn btn-primary" id="btn-empty-create">+ Document a Venue</button>' +
        "</div>" +
        "</div>";
      return;
    }

    container.innerHTML = state.venues
      .map(function (v) {
        const f = v.freshness;
        const attrs = v.access_attributes;
        const sym = freshnessSymbol(f.state);
        const provClass = v.is_synthetic_sample ? "provenance-pill synthetic" : "provenance-pill";

        let alertHtml = "";
        if (v.active_barrier_alert || attrs.elevator_status === "out_of_service") {
          alertHtml =
            '<div class="barrier-alert-box" role="note">' +
            '<strong style="color: var(--color-signal-orange);">[!] BARRIER ALERT:</strong> ' +
            "<span>" +
            escapeHtml(v.active_barrier_alert || "Elevator / platform lift currently out of service.") +
            "</span>" +
            "</div>";
        }

        const chips = [];
        if (attrs.step_free_entrance) {
          chips.push(
            '<span class="attr-chip positive">✓ Step-Free (' +
              escapeHtml(attrs.entrance_door_width_cm) +
              " cm door · " +
              escapeHtml(attrs.threshold_height_mm) +
              " mm threshold)</span>"
          );
        } else {
          chips.push(
            '<span class="attr-chip barrier">! Stepped Entry (' +
              escapeHtml(attrs.threshold_height_mm) +
              " mm step · " +
              escapeHtml(attrs.entrance_door_width_cm) +
              " cm door)</span>"
          );
        }

        chips.push(
          '<span class="attr-chip">Restroom: ' +
            escapeHtml(
              (state.taxonomies.restroom_types || {})[attrs.accessible_restroom_type] ||
                attrs.accessible_restroom_type
            ) +
            " (" +
            escapeHtml(attrs.turning_circle_cm) +
            " cm turn)</span>"
        );

        if (attrs.elevator_status === "operational") {
          chips.push('<span class="attr-chip positive">✓ Elevator Operational</span>');
        } else if (attrs.elevator_status === "out_of_service") {
          chips.push('<span class="attr-chip barrier">! Elevator Out of Service</span>');
        }

        if (attrs.quiet_sensory_space) {
          chips.push('<span class="attr-chip">Quiet Sensory Space</span>');
        }
        if (attrs.hearing_loop_available) {
          chips.push('<span class="attr-chip">Hearing Loop</span>');
        }
        if (attrs.braille_tactile_signage) {
          chips.push('<span class="attr-chip">Braille Signage</span>');
        }

        return (
          '<article class="venue-card state-' +
          escapeHtml(f.state) +
          '" id="venue-card-' +
          escapeHtml(v.id) +
          '">' +
          '<div class="venue-card-header">' +
          "<div>" +
          '<h3 class="venue-card-title">' +
          escapeHtml(v.name) +
          "</h3>" +
          '<div class="venue-meta-line">' +
          "<span>" +
          escapeHtml(v.category_label) +
          "</span> · " +
          "<span>" +
          escapeHtml(v.address + ", " + v.city + " " + v.postal_code) +
          "</span> · " +
          '<span class="' +
          provClass +
          '">' +
          escapeHtml(v.provenance_badge) +
          "</span>" +
          "</div>" +
          "</div>" +
          '<div style="display: flex; flex-direction: column; align-items: flex-end; gap: 4px;">' +
          '<span class="freshness-badge state-' +
          escapeHtml(f.state) +
          '">' +
          "<span>[" +
          sym +
          "]</span> " +
          "<span>" +
          escapeHtml(f.label) +
          "</span>" +
          "</span>" +
          '<span style="font-family: var(--font-mono); font-size: 0.72rem; color: var(--text-secondary);">' +
          "Confidence: " +
          escapeHtml(f.confidence_score) +
          "% (" +
          escapeHtml(f.observation_count) +
          " obs)</span>" +
          "</div>" +
          "</div>" +
          alertHtml +
          '<p style="margin: 0.65rem 0 0 0; font-size: 0.9rem; color: var(--text-primary);">' +
          escapeHtml(v.summary) +
          "</p>" +
          '<div class="attribute-chips">' +
          chips.join("") +
          "</div>" +
          '<div class="venue-card-footer">' +
          '<span style="font-size: 0.78rem; color: var(--text-secondary);">Hours: ' +
          escapeHtml(v.operating_hours) +
          " · Photos: " +
          escapeHtml(v.approved_photo_count) +
          "</span>" +
          '<div style="display: flex; gap: 0.5rem;">' +
          '<button type="button" class="btn btn-xs btn-primary" data-inspect-venue="' +
          escapeHtml(v.id) +
          '">Inspect Details &amp; Evidence →</button>' +
          "</div>" +
          "</div>" +
          "</article>"
        );
      })
      .join("");
  }

  // ==========================================================================
  // Venue Detail View, Observations, Photos, Briefing & Moderation Flagging
  // ==========================================================================

  async function openVenueDetail(venueId) {
    const data = await apiRequest("/api/venues/" + encodeURIComponent(venueId));
    state.selectedVenue = data.venue;
    renderVenueDetail();
    switchView("venue-detail");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function renderVenueDetail() {
    const v = state.selectedVenue;
    const container = document.getElementById("venue-detail-content");
    const ownerActions = document.getElementById("detail-owner-actions");
    if (!v || !container || !ownerActions) return;

    const canEdit =
      state.user &&
      (state.user.id === v.created_by ||
        ["operator", "moderator", "admin"].includes(state.user.role));

    if (canEdit) {
      ownerActions.innerHTML =
        '<button type="button" class="btn btn-xs btn-cobalt" id="btn-edit-venue">Edit Venue Attributes</button>' +
        '<button type="button" class="btn btn-xs" id="btn-archive-venue">Archive Venue (Confirm)</button>' +
        '<button type="button" class="btn btn-xs btn-danger" id="btn-delete-venue">Delete Venue (Confirm)</button>';
    } else {
      ownerActions.innerHTML = "";
    }

    const f = v.freshness;
    const a = v.access_attributes;
    const sym = freshnessSymbol(f.state);
    const tax = state.taxonomies;
    const gme = v.google_maps_earth || null;
    const gLinks = (gme && gme.google_links) || {};
    const gRoute = (gme && gme.route_from_origin) || {};
    const gGrade = (gme && gme.curb_to_entrance_grade) || {};
    const gCoords = (gme && gme.coordinates) || {};

    const googleMapsEarthCardHtml = gme
      ? '<div class="spec-card" id="google-maps-earth-card">' +
        '<div class="spec-card-title">' +
        '<span>Google Maps Platform &amp; Google Earth 3D Curb-to-Entrance Explorer</span>' +
        '<span class="provenance-pill">' +
        escapeHtml(gme.adapter_mode || "deterministic_wgs84_and_earth_3d_kml") +
        "</span>" +
        "</div>" +
        '<div class="spec-columns" style="margin-bottom: 0.85rem;">' +
        '<dl class="spec-dl">' +
        '<div class="spec-pair"><dt>WGS84 Coordinates</dt><dd>' +
        escapeHtml(gCoords.wgs84_label || v.latitude + ", " + v.longitude) +
        "</dd></div>" +
        '<div class="spec-pair"><dt>ADA 1:12 Curb Grade</dt><dd>' +
        (gGrade.ada_1_to_12_compliant ? "✓ " : "! ") +
        escapeHtml(gGrade.grade_label || "Verified") +
        "</dd></div>" +
        '<div class="spec-pair"><dt>Elevation Baseline</dt><dd>' +
        escapeHtml(
          gCoords.elevation ? gCoords.elevation.elevation_meters + " m (" + gCoords.elevation.source + ")" : "18.5 m"
        ) +
        "</dd></div>" +
        "</dl>" +
        '<dl class="spec-dl" id="geospatial-route-readout">' +
        '<div class="spec-pair"><dt>Reference Origin</dt><dd>' +
        escapeHtml(gRoute.origin_label || "King Street Accessible Transit Hub") +
        "</dd></div>" +
        '<div class="spec-pair"><dt>Sidewalk Roll Distance</dt><dd>' +
        escapeHtml(gRoute.estimated_sidewalk_distance_meters || 0) +
        " m (" +
        escapeHtml(gRoute.compass_direction || "N") +
        " · " +
        escapeHtml(gRoute.bearing_degrees || 0) +
        "°)</dd></div>" +
        '<div class="spec-pair"><dt>Est. Wheelchair Time</dt><dd><strong>' +
        escapeHtml(gRoute.estimated_roll_minutes || 1) +
        " min</strong> (" +
        escapeHtml(gRoute.travel_mode || "wheelchair_manual") +
        ")</dd></div>" +
        "</dl>" +
        "</div>" +
        '<div style="display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.85rem;">' +
        '<a class="btn btn-xs btn-primary" href="' +
        escapeHtml(gLinks.google_maps_wheelchair_transit_url || "#") +
        '" target="_blank" rel="noopener noreferrer">Google Maps Wheelchair Transit ↗</a>' +
        '<a class="btn btn-xs btn-cobalt" href="' +
        escapeHtml(gLinks.google_street_view_curb_url || "#") +
        '" target="_blank" rel="noopener noreferrer">Street View 360° Curb &amp; Entrance ↗</a>' +
        '<a class="btn btn-xs" href="' +
        escapeHtml(gLinks.google_earth_3d_flyover_url || "#") +
        '" target="_blank" rel="noopener noreferrer">Google Earth 3D Web Flyover ↗</a>' +
        '<a class="btn btn-xs" href="' +
        escapeHtml(gLinks.google_earth_kml_download_url || "/api/venues/" + encodeURIComponent(v.id) + "/earth.kml") +
        '" download="' +
        escapeHtml(v.slug) +
        '-earth-3d.kml">Download Google Earth 3D (.kml) ↓</a>' +
        "</div>" +
        '<form id="geospatial-route-form" style="border-top: 1px solid var(--border-subtle); padding-top: 0.75rem;" novalidate>' +
        '<div class="spec-columns">' +
        "<div>" +
        '<label class="form-label" for="geo-origin-lat">Origin Latitude</label>' +
        '<input type="number" step="0.0001" id="geo-origin-lat" class="form-input" value="' +
        escapeHtml(gRoute.origin_latitude !== undefined ? gRoute.origin_latitude : 47.5984) +
        '" />' +
        "</div>" +
        "<div>" +
        '<label class="form-label" for="geo-origin-lng">Origin Longitude</label>' +
        '<input type="number" step="0.0001" id="geo-origin-lng" class="form-input" value="' +
        escapeHtml(gRoute.origin_longitude !== undefined ? gRoute.origin_longitude : -122.3301) +
        '" />' +
        "</div>" +
        "<div>" +
        '<label class="form-label" for="geo-travel-mode">Mobility Profile</label>' +
        '<select id="geo-travel-mode" class="form-select">' +
        '<option value="wheelchair_manual">Manual Wheelchair (1.1 m/s)</option>' +
        '<option value="wheelchair_power">Power Chair / Scooter (1.45 m/s)</option>' +
        '<option value="assisted_cane_walker">Cane / Walker / Assisted (0.85 m/s)</option>' +
        "</select>" +
        "</div>" +
        '<div style="display: flex; align-items: flex-end;">' +
        '<button type="submit" class="btn btn-xs btn-cobalt" style="width: 100%; padding: 0.55rem;">Calculate Accessible Route</button>' +
        "</div>" +
        "</div>" +
        "</form>" +
        "</div>"
      : "";

    const obsHtml = (v.observations || [])
      .map(function (o) {
        return (
          '<li class="timeline-item ' +
          (o.is_operational_alert ? "alert-obs" : "") +
          '">' +
          '<div style="display: flex; justify-content: space-between; gap: 0.5rem; flex-wrap: wrap; font-size: 0.78rem; color: var(--text-secondary);">' +
          "<span><strong>" +
          escapeHtml(o.author_name) +
          "</strong> · " +
          escapeHtml(o.observer_role_label) +
          "</span>" +
          "<span>" +
          escapeHtml(o.observed_at) +
          " · Confidence: <strong>" +
          escapeHtml(o.confidence_score) +
          "%</strong> (" +
          escapeHtml(o.confidence_label) +
          ")</span>" +
          "</div>" +
          '<p style="margin: 0.45rem 0; font-size: 0.9rem;">' +
          escapeHtml(o.summary) +
          "</p>" +
          '<div style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--color-acid-lime);">' +
          (o.measured_door_width_cm
            ? "Measured Door Width: " + escapeHtml(o.measured_door_width_cm) + " cm · "
            : "") +
          (o.elevator_operational_check
            ? "Elevator Check: " + escapeHtml(o.elevator_operational_check) + " · "
            : "") +
          (o.barriers_noted ? "Barrier Note: " + escapeHtml(o.barriers_noted) : "") +
          "</div>" +
          "</li>"
        );
      })
      .join("");

    const photosHtml =
      (v.photo_evidence || []).length === 0
        ? '<p style="font-size: 0.85rem; color: var(--text-secondary);">No public consent-approved photos attached yet. Upload one below.</p>'
        : '<div class="photo-grid">' +
          v.photo_evidence
            .map(function (p) {
              return (
                '<figure class="photo-card" style="margin: 0;">' +
                '<img src="' +
                escapeHtml(p.file_url) +
                '" alt="' +
                escapeHtml(p.alt_text) +
                '" loading="lazy" />' +
                '<figcaption class="photo-card-body">' +
                '<div style="display: flex; justify-content: space-between; align-items: center; gap: 4px; margin-bottom: 4px;">' +
                "<strong>" +
                escapeHtml(p.category_label) +
                "</strong>" +
                '<span class="provenance-pill">' +
                escapeHtml(p.consent_status) +
                "</span>" +
                "</div>" +
                '<div style="color: var(--text-primary); margin-bottom: 4px;"><strong>Alt:</strong> ' +
                escapeHtml(p.alt_text) +
                "</div>" +
                '<div style="font-family: var(--font-mono); font-size: 0.7rem; color: var(--text-secondary);">' +
                "EXIF Stripped: ✓ · " +
                escapeHtml(p.width_px + "×" + p.height_px) +
                "px" +
                "</div>" +
                "</figcaption>" +
                "</figure>"
              );
            })
            .join("") +
          "</div>";

    const historyHtml = (v.provenance_history || [])
      .map(function (h) {
        return (
          '<li style="font-size: 0.78rem; color: var(--text-secondary); padding: 4px 0; border-bottom: 1px dashed var(--border-subtle);">' +
          '<code style="color: var(--color-acid-lime);">' +
          escapeHtml(h.action) +
          "</code> by <strong>" +
          escapeHtml(h.actor_name) +
          "</strong> at " +
          escapeHtml(h.created_at) +
          "</li>"
        );
      })
      .join("");

    container.innerHTML =
      '<div class="spec-card">' +
      '<div class="venue-card-header">' +
      "<div>" +
      '<h2 id="detail-venue-name" style="margin: 0; font-size: 1.5rem; color: var(--text-high-contrast);">' +
      escapeHtml(v.name) +
      "</h2>" +
      '<div class="venue-meta-line">' +
      "<span>" +
      escapeHtml(v.category_label) +
      "</span> · <span>" +
      escapeHtml(v.address + ", " + v.city + " " + v.postal_code) +
      "</span> · <span>Coords: " +
      escapeHtml(v.latitude + ", " + v.longitude) +
      '</span> · <span class="provenance-pill ' +
      (v.is_synthetic_sample ? "synthetic" : "") +
      '">' +
      escapeHtml(v.provenance_badge) +
      "</span>" +
      "</div>" +
      "</div>" +
      '<div style="text-align: right;">' +
      '<span class="freshness-badge state-' +
      escapeHtml(f.state) +
      '">[' +
      sym +
      "] " +
      escapeHtml(f.label) +
      "</span>" +
      '<div style="font-size: 0.78rem; color: var(--text-secondary); margin-top: 4px;">' +
      escapeHtml(f.explanation) +
      "</div>" +
      "</div>" +
      "</div>" +
      (v.active_barrier_alert
        ? '<div class="barrier-alert-box" role="alert"><strong>[!] ACTIVE BARRIER ALERT:</strong> <span>' +
          escapeHtml(v.active_barrier_alert) +
          "</span></div>"
        : "") +
      '<p style="margin-top: 0.85rem; font-size: 0.95rem;">' +
      escapeHtml(v.summary) +
      "</p>" +
      '<div style="display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; margin-top: 0.75rem;">' +
      '<button type="button" class="btn btn-xs btn-cobalt" id="btn-generate-briefing">Synthesize Route Briefing (Consent-Checked)</button>' +
      '<span style="font-size: 0.76rem; color: var(--text-secondary);">Documented by ' +
      escapeHtml(v.creator_name) +
      " · Operating Hours: " +
      escapeHtml(v.operating_hours) +
      "</span>" +
      "</div>" +
      '<div id="venue-briefing-box" style="margin-top: 0.85rem;" hidden></div>' +
      "</div>" +
      /* Structured Access Attributes 3-Column Breakdown */
      '<div class="spec-card">' +
      '<h3 class="spec-card-title">Structured Physical &amp; Sensory Access Attributes</h3>' +
      '<div class="spec-columns">' +
      '<dl class="spec-dl">' +
      '<div class="spec-pair"><dt>Primary Entrance</dt><dd>' +
      (a.step_free_entrance ? "✓ Step-Free Entrance" : "! Stepped Entrance") +
      "</dd></div>" +
      '<div class="spec-pair"><dt>Door Clear Width</dt><dd>' +
      escapeHtml(a.entrance_door_width_cm) +
      " cm " +
      (a.entrance_door_width_cm >= 82 ? "(Meets >=82 cm Standard)" : "(Narrow <82 cm)") +
      "</dd></div>" +
      '<div class="spec-pair"><dt>Threshold Height</dt><dd>' +
      escapeHtml(a.threshold_height_mm) +
      " mm</dd></div>" +
      '<div class="spec-pair"><dt>Door Opener</dt><dd>' +
      escapeHtml((tax.door_opener_types || {})[a.door_opener_type] || a.door_opener_type) +
      "</dd></div>" +
      '<div class="spec-pair"><dt>Ramp &amp; Slope</dt><dd>' +
      (a.ramp_present
        ? "Ramp Installed (" + escapeHtml(a.ramp_slope_degrees || "level") + "°)"
        : "No Dedicated Ramp") +
      "</dd></div>" +
      '<div class="spec-pair"><dt>Entrance Notes</dt><dd>' +
      escapeHtml(a.entrance_notes || "None noted") +
      "</dd></div>" +
      "</dl>" +
      '<dl class="spec-dl">' +
      '<div class="spec-pair"><dt>Accessible Restroom</dt><dd>' +
      escapeHtml(
        (tax.restroom_types || {})[a.accessible_restroom_type] || a.accessible_restroom_type
      ) +
      "</dd></div>" +
      '<div class="spec-pair"><dt>Transfer Grab Bars</dt><dd>' +
      escapeHtml((tax.grab_bar_types || {})[a.grab_bars] || a.grab_bars) +
      "</dd></div>" +
      '<div class="spec-pair"><dt>Turning Circle Diameter</dt><dd>' +
      escapeHtml(a.turning_circle_cm) +
      " cm</dd></div>" +
      '<div class="spec-pair"><dt>Elevator / Lift Status</dt><dd>' +
      escapeHtml((tax.elevator_statuses || {})[a.elevator_status] || a.elevator_status) +
      "</dd></div>" +
      '<div class="spec-pair"><dt>Accessible Parking Bays</dt><dd>' +
      escapeHtml(a.accessible_parking_spaces) +
      " spaces</dd></div>" +
      '<div class="spec-pair"><dt>Signage &amp; Sensory</dt><dd>' +
      [
        a.braille_tactile_signage ? "Braille/Tactile" : null,
        a.hearing_loop_available ? "Hearing Loop" : null,
        a.quiet_sensory_space ? "Quiet Sensory Room" : null,
      ]
        .filter(Boolean)
        .join(" · ") || "Standard only" +
      "</dd></div>" +
      "</dl>" +
      '<dl class="spec-dl">' +
      '<div class="spec-pair"><dt>Pathway Surface</dt><dd>' +
      escapeHtml((tax.pathway_surfaces || {})[a.pathway_surface] || a.pathway_surface) +
      "</dd></div>" +
      '<div class="spec-pair"><dt>Min Corridor Width</dt><dd>' +
      escapeHtml(a.min_corridor_width_cm) +
      " cm</dd></div>" +
      '<div class="spec-pair"><dt>Lighting Profile</dt><dd>' +
      escapeHtml((tax.lighting_levels || {})[a.lighting_level] || a.lighting_level) +
      "</dd></div>" +
      '<div class="spec-pair"><dt>Acoustic Environment</dt><dd>' +
      escapeHtml((tax.acoustic_profiles || {})[a.acoustic_profile] || a.acoustic_profile) +
      "</dd></div>" +
      '<div class="spec-pair"><dt>Interior Route Notes</dt><dd>' +
      escapeHtml(a.route_notes || "None noted") +
      "</dd></div>" +
      "</dl>" +
      "</div>" +
      "</div>" +
      googleMapsEarthCardHtml +
      /* Two-column lower section: Left = Observations & Photos; Right = Submit Observation, Upload Photo, Flag Report */
      '<div class="detail-grid">' +
      "<div>" +
      '<div class="spec-card">' +
      '<h3 class="spec-card-title">Timestamped Observations (' +
      escapeHtml((v.observations || []).length) +
      ")</h3>" +
      '<ul class="timeline-list">' +
      obsHtml +
      "</ul>" +
      "</div>" +
      '<div class="spec-card">' +
      '<h3 class="spec-card-title">Consent-Reviewed Photo Evidence</h3>' +
      photosHtml +
      "</div>" +
      '<div class="spec-card">' +
      '<h3 class="spec-card-title">Provenance &amp; Audit History</h3>' +
      '<ul style="list-style: none; padding: 0; margin: 0;">' +
      historyHtml +
      "</ul>" +
      "</div>" +
      "</div>" +
      /* Right Action Forms */
      "<div>" +
      /* Form 1: Log Timestamped Observation */
      '<div class="spec-card">' +
      '<h3 class="spec-card-title">Log a Timestamped Observation</h3>' +
      '<form id="observation-form" novalidate>' +
      '<div style="margin-bottom: 0.75rem;">' +
      '<label class="form-label" for="obs-role">Your Perspective / Role *</label>' +
      '<select id="obs-role" class="form-select" required>' +
      Object.keys(tax.observer_roles || {})
        .map(function (k) {
          return '<option value="' + escapeHtml(k) + '">' + escapeHtml(tax.observer_roles[k]) + "</option>";
        })
        .join("") +
      "</select>" +
      "</div>" +
      '<div style="margin-bottom: 0.75rem;">' +
      '<label class="form-label" for="obs-confidence">Observation Method &amp; Confidence *</label>' +
      '<select id="obs-confidence" class="form-select" required>' +
      Object.keys(tax.confidence_labels || {})
        .map(function (k) {
          return '<option value="' + escapeHtml(k) + '">' + escapeHtml(tax.confidence_labels[k]) + "</option>";
        })
        .join("") +
      "</select>" +
      "</div>" +
      '<div class="spec-columns" style="margin-bottom: 0.75rem;">' +
      "<div>" +
      '<label class="form-label" for="obs-door-cm">Measured Door (cm)</label>' +
      '<input type="number" id="obs-door-cm" class="form-input" min="40" max="300" placeholder="Optional" />' +
      "</div>" +
      "<div>" +
      '<label class="form-label" for="obs-elevator">Elevator Check</label>' +
      '<select id="obs-elevator" class="form-select">' +
      '<option value="">No change</option>' +
      '<option value="operational">Operational</option>' +
      '<option value="out_of_service">Out of Service (Alert)</option>' +
      "</select>" +
      "</div>" +
      "</div>" +
      '<div style="margin-bottom: 0.75rem;">' +
      '<label class="form-label" for="obs-summary">Observation Summary (min 10 chars) *</label>' +
      '<textarea id="obs-summary" class="form-textarea" required placeholder="Document what you verified on site (door opener responsiveness, ramp clearance, restroom transfer space)..."></textarea>' +
      "</div>" +
      '<div style="margin-bottom: 0.75rem;">' +
      '<label class="form-label" for="obs-barriers">Barriers Noted (Optional)</label>' +
      '<input type="text" id="obs-barriers" class="form-input" placeholder="e.g., Temporary sandwich board narrowing ramp entry" />' +
      "</div>" +
      '<label class="facet-check" style="margin-bottom: 0.85rem;">' +
      '<input type="checkbox" id="obs-alert" />' +
      "<span>Flag as Active Operational Barrier Alert</span>" +
      "</label>" +
      '<div><button type="submit" class="btn btn-primary" style="width: 100%;">Submit Timestamped Observation</button></div>' +
      "</form>" +
      "</div>" +
      /* Form 2: Upload Consent-Reviewed Photo Evidence */
      '<div class="spec-card">' +
      '<h3 class="spec-card-title">Upload Consent-Reviewed Photo Evidence</h3>' +
      '<form id="photo-upload-form" novalidate>' +
      '<div style="margin-bottom: 0.75rem;">' +
      '<label class="form-label" for="photo-category">Access Feature Category *</label>' +
      '<select id="photo-category" class="form-select" required>' +
      Object.keys(tax.photo_categories || {})
        .map(function (k) {
          return '<option value="' + escapeHtml(k) + '">' + escapeHtml(tax.photo_categories[k]) + "</option>";
        })
        .join("") +
      "</select>" +
      "</div>" +
      '<div style="margin-bottom: 0.75rem;">' +
      '<label class="form-label" for="photo-alt">Screen-Reader Alt Text (min 10 chars) *</label>' +
      '<textarea id="photo-alt" class="form-textarea" style="min-height: 62px;" required placeholder="Describe the physical entrance, ramp slope, or grab bar placement clearly for blind and low-vision users..."></textarea>' +
      "</div>" +
      '<div style="margin-bottom: 0.75rem;">' +
      '<label class="form-label" for="photo-caption">Caption (Optional)</label>' +
      '<input type="text" id="photo-caption" class="form-input" placeholder="e.g., North entrance push-button bollard height" />' +
      "</div>" +
      '<div style="margin-bottom: 0.75rem;">' +
      '<label class="form-label" for="photo-file">Image File (PNG, JPEG, WEBP &le; 5 MB) *</label>' +
      '<input type="file" id="photo-file" class="form-input" accept="image/png,image/jpeg,image/webp" />' +
      '<span class="form-hint">Or leave file blank to generate a clean schematic diagram PNG for testing.</span>' +
      "</div>" +
      '<div style="display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 0.85rem;">' +
      '<label class="facet-check">' +
      '<input type="checkbox" id="photo-consent-faces" required />' +
      "<span>I confirm no identifiable faces or private license plates are visible *</span>" +
      "</label>" +
      '<label class="facet-check">' +
      '<input type="checkbox" id="photo-consent-area" required />' +
      "<span>Taken in a public access area or with venue operator consent *</span>" +
      "</label>" +
      "</div>" +
      '<button type="submit" class="btn btn-cobalt" style="width: 100%;">Scrub EXIF &amp; Upload Photo Evidence</button>' +
      "</form>" +
      "</div>" +
      /* Form 3: Flag / Report for Moderation */
      '<div class="spec-card">' +
      '<h3 class="spec-card-title">Flag Inaccuracy or Privacy Issue</h3>' +
      '<form id="moderation-report-form" novalidate>' +
      '<div style="margin-bottom: 0.75rem;">' +
      '<label class="form-label" for="mod-reason">Reason for Flag *</label>' +
      '<select id="mod-reason" class="form-select" required>' +
      Object.keys(tax.moderation_reasons || {})
        .map(function (k) {
          return '<option value="' + escapeHtml(k) + '">' + escapeHtml(tax.moderation_reasons[k]) + "</option>";
        })
        .join("") +
      "</select>" +
      "</div>" +
      '<div style="margin-bottom: 0.75rem;">' +
      '<label class="form-label" for="mod-details">Evidence &amp; Correction Details (min 10 chars) *</label>' +
      '<textarea id="mod-details" class="form-textarea" style="min-height: 62px;" required placeholder="Explain what measurement changed or needs moderator review..."></textarea>' +
      "</div>" +
      '<button type="submit" class="btn btn-danger" style="width: 100%;">Submit Flag to Moderation Queue</button>' +
      "</form>" +
      "</div>" +
      "</div>" +
      "</div>";
  }

  function generateClientSamplePngBase64() {
    const canvas = document.createElement("canvas");
    canvas.width = 320;
    canvas.height = 200;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#030407";
    ctx.fillRect(0, 0, 320, 200);
    ctx.strokeStyle = "#D4FF24";
    ctx.lineWidth = 3;
    ctx.strokeRect(12, 12, 296, 176);
    ctx.fillStyle = "#1558C9";
    ctx.fillRect(24, 24, 272, 42);
    ctx.fillStyle = "#E8D2B5";
    ctx.font = "bold 13px monospace";
    ctx.fillText("ACCESSABLE ATLAS SCHEMATIC", 34, 50);
    ctx.fillStyle = "#D4FF24";
    ctx.fillText("VERIFIED CLEARANCE DIAGRAM", 34, 115);
    return canvas.toDataURL("image/png");
  }

  // ==========================================================================
  // Insights View (Journey C)
  // ==========================================================================

  async function loadInsights() {
    const container = document.getElementById("insights-container");
    if (!container) return;
    const data = await apiRequest("/api/insights");
    const m = data.metrics;
    const meta = data.metadata;
    const fb = data.freshness_breakdown;
    const tb = data.tinybird_telemetry || {};

    const attentionRows =
      (data.records_requiring_attention || []).length === 0
        ? '<p style="color: var(--text-secondary);">All published venues are currently fresh and barrier-free.</p>'
        : '<div class="venue-list-grid">' +
          data.records_requiring_attention
            .map(function (r) {
              return (
                '<div class="timeline-item ' +
                (r.freshness_state === "active_alert" ? "alert-obs" : "") +
                '" style="display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap;">' +
                "<div>" +
                "<strong>" +
                escapeHtml(r.name) +
                "</strong> (" +
                escapeHtml(r.category_label) +
                " · " +
                escapeHtml(r.city) +
                ")" +
                '<div style="font-size: 0.82rem; color: var(--text-secondary);">' +
                escapeHtml(r.explanation) +
                "</div>" +
                "</div>" +
                '<div style="display: flex; gap: 0.5rem; align-items: center;">' +
                '<span class="freshness-badge state-' +
                escapeHtml(r.freshness_state) +
                '">' +
                escapeHtml(r.freshness_label) +
                "</span>" +
                '<button type="button" class="btn btn-xs btn-primary" data-inspect-venue="' +
                escapeHtml(r.venue_id) +
                '">Inspect Record →</button>' +
                "</div>" +
                "</div>"
              );
            })
            .join("") +
          "</div>";

    container.innerHTML =
      /* Provenance, Time Range, Units, Assumptions & Limitations Banner */
      '<div class="spec-card" style="background: var(--surface-panel); margin-bottom: var(--space-4);">' +
      '<h3 style="margin-top: 0; font-size: 0.95rem; color: var(--color-acid-lime);">Insight Provenance, Methodology &amp; Limitations</h3>' +
      '<div class="spec-columns" style="font-size: 0.82rem;">' +
      "<div><strong>Time Range:</strong> " +
      escapeHtml(meta.time_range) +
      "<br/><strong>Source:</strong> " +
      escapeHtml(meta.source) +
      "</div>" +
      "<div><strong>Units:</strong> " +
      escapeHtml(meta.units) +
      "<br/><strong>Assumptions:</strong> " +
      escapeHtml(meta.assumptions) +
      "</div>" +
      "<div><strong>Limitations:</strong> " +
      escapeHtml(meta.limitations) +
      "</div>" +
      "</div>" +
      "</div>" +
      /* Metrics Tiles */
      '<div class="metrics-grid">' +
      '<div class="metric-tile accent-lime"><div class="metric-value">' +
      escapeHtml(m.total_published_venues) +
      '</div><div class="metric-label">Total Published Venues (' +
      escapeHtml(m.user_documented_venues) +
      " User / " +
      escapeHtml(m.synthetic_sample_venues) +
      " Synthetic Sample)</div></div>" +
      '<div class="metric-tile accent-lime"><div class="metric-value">' +
      escapeHtml(m.step_free_venues) +
      '</div><div class="metric-label">Step-Free Primary Entrances</div></div>' +
      '<div class="metric-tile accent-cobalt"><div class="metric-value">' +
      escapeHtml(m.wheelchair_standard_venues) +
      '</div><div class="metric-label">Meet Full Wheelchair Clearance (&ge;82cm Door + &ge;150cm Turn)</div></div>' +
      '<div class="metric-tile accent-cobalt"><div class="metric-value">' +
      escapeHtml(m.average_entrance_door_width_cm) +
      ' cm</div><div class="metric-label">Mean Entrance Door Clear Width</div></div>' +
      '<div class="metric-tile accent-lime"><div class="metric-value">' +
      escapeHtml(fb.fresh_verified || 0) +
      '</div><div class="metric-label">Fresh Verified (&lt;30 Days)</div></div>' +
      '<div class="metric-tile accent-orange"><div class="metric-value">' +
      escapeHtml((fb.active_alert || 0) + (fb.stale_reverify || 0)) +
      '</div><div class="metric-label">Active Barrier Alerts or Stale (&gt;90 Days)</div></div>' +
      "</div>" +
      '<h3 class="spec-card-title">Underlying Records Requiring Re-Verification or Barrier Follow-Through</h3>' +
      attentionRows +
      '<div class="spec-card" style="margin-top: var(--space-4); background: var(--surface-panel);">' +
      '<h3 class="spec-card-title">Tinybird Privacy-Minimized Telemetry Stream (Non-Canonical)</h3>' +
      '<p style="font-size: 0.8rem; color: var(--text-secondary);">' +
      "Mode: <code>" +
      escapeHtml(tb.status && tb.status.configured ? "Tinybird Cloud HTTP" : "Local Minimized Ring Buffer") +
      "</code> · Total Emitted: <strong>" +
      escapeHtml(tb.status ? tb.status.total_emitted : 0) +
      "</strong> · Allowed Schema Fields: <code>" +
      escapeHtml(tb.status ? (tb.status.allowed_fields || []).join(", ") : "") +
      "</code></p>" +
      "</div>";
  }

  // ==========================================================================
  // Moderation & Audit View
  // ==========================================================================

  async function loadModerationQueue() {
    const container = document.getElementById("moderation-container");
    if (!container) return;
    try {
      const data = await apiRequest("/api/moderation/queue");
      const reports = data.reports || [];
      const pendingPhotos = data.pending_photos || [];
      const audits = data.audit_events || [];

      const reportsHtml =
        reports.length === 0
          ? '<p style="color: var(--text-secondary);">No moderation reports in queue.</p>'
          : reports
              .map(function (r) {
                const isOpen = r.status === "open" || r.status === "investigating";
                return (
                  '<div class="timeline-item" style="margin-bottom: 0.75rem;">' +
                  '<div style="display: flex; justify-content: space-between; gap: 0.5rem; flex-wrap: wrap;">' +
                  "<strong>" +
                  escapeHtml(r.venue_name) +
                  " — " +
                  escapeHtml(r.reason_label) +
                  "</strong>" +
                  '<span class="provenance-pill">Status: ' +
                  escapeHtml(r.status) +
                  "</span>" +
                  "</div>" +
                  '<p style="margin: 0.4rem 0; font-size: 0.88rem;">' +
                  escapeHtml(r.details) +
                  "</p>" +
                  '<div style="font-size: 0.76rem; color: var(--text-secondary);">Reported by ' +
                  escapeHtml(r.reporter_name) +
                  " at " +
                  escapeHtml(r.created_at) +
                  "</div>" +
                  (isOpen
                    ? '<div style="margin-top: 0.65rem; padding-top: 0.65rem; border-top: 1px solid var(--border-subtle); display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">' +
                      '<input type="text" class="form-input" id="mod-note-' +
                      escapeHtml(r.id) +
                      '" style="max-width: 320px; font-size: 0.8rem;" placeholder="Moderator resolution notes (min 8 chars)..." value="Verified with operator; entrance schedule updated." />' +
                      '<label class="facet-check"><input type="checkbox" id="mod-confirm-' +
                      escapeHtml(r.id) +
                      '" /><span>Confirm Action</span></label>' +
                      '<button type="button" class="btn btn-xs btn-primary" data-resolve-report="' +
                      escapeHtml(r.id) +
                      '" data-resolve-status="resolved_upheld">Uphold Flag</button>' +
                      '<button type="button" class="btn btn-xs" data-resolve-report="' +
                      escapeHtml(r.id) +
                      '" data-resolve-status="resolved_dismissed">Dismiss Flag</button>' +
                      "</div>"
                    : '<div style="margin-top: 0.4rem; font-size: 0.8rem; color: var(--color-acid-lime);">Resolution: ' +
                      escapeHtml(r.resolution_notes) +
                      "</div>") +
                  "</div>"
                );
              })
              .join("");

      const pendingPhotosHtml =
        pendingPhotos.length === 0
          ? '<p style="color: var(--text-secondary);">No pending photos awaiting consent review.</p>'
          : pendingPhotos
              .map(function (p) {
                return (
                  '<div class="timeline-item" style="margin-bottom: 0.75rem;">' +
                  "<strong>" +
                  escapeHtml(p.venue_name) +
                  " · " +
                  escapeHtml(p.category_label) +
                  "</strong>" +
                  '<div style="font-size: 0.84rem; margin: 0.3rem 0;">Alt text: ' +
                  escapeHtml(p.alt_text) +
                  "</div>" +
                  '<div style="display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; margin-top: 0.5rem;">' +
                  '<input type="text" class="form-input" id="photo-note-' +
                  escapeHtml(p.id) +
                  '" style="max-width: 280px; font-size: 0.8rem;" value="Verified no identifiable faces; clear schematic." />' +
                  '<label class="facet-check"><input type="checkbox" id="photo-confirm-' +
                  escapeHtml(p.id) +
                  '" /><span>Confirm Consent Decision</span></label>' +
                  '<button type="button" class="btn btn-xs btn-primary" data-review-photo="' +
                  escapeHtml(p.id) +
                  '" data-photo-status="approved_public">Approve Public</button>' +
                  '<button type="button" class="btn btn-xs btn-danger" data-review-photo="' +
                  escapeHtml(p.id) +
                  '" data-photo-status="rejected_privacy">Reject (Privacy)</button>' +
                  "</div>" +
                  "</div>"
                );
              })
              .join("");

      const auditHtml = audits
        .map(function (a) {
          return (
            '<li style="font-size: 0.78rem; padding: 5px 0; border-bottom: 1px dashed var(--border-subtle);">' +
            '<code style="color: var(--color-acid-lime);">' +
            escapeHtml(a.action) +
            "</code> · Actor: <strong>" +
            escapeHtml(a.actor_name) +
            "</strong> · Target: <code>" +
            escapeHtml(a.target_type + ":" + a.target_id.slice(0, 12)) +
            "</code> · " +
            escapeHtml(a.created_at) +
            "</li>"
          );
        })
        .join("");

      container.innerHTML =
        '<div class="detail-grid">' +
        "<div>" +
        '<h3 class="spec-card-title">Community &amp; Operator Moderation Reports (' +
        escapeHtml(reports.length) +
        ")</h3>" +
        reportsHtml +
        '<h3 class="spec-card-title" style="margin-top: 1.5rem;">Pending Photo Evidence Consent Queue (' +
        escapeHtml(pendingPhotos.length) +
        ")</h3>" +
        pendingPhotosHtml +
        "</div>" +
        "<div>" +
        '<h3 class="spec-card-title">Immutable Workspace Audit Trail</h3>' +
        '<ul style="list-style: none; padding: 0; margin: 0;">' +
        auditHtml +
        "</ul>" +
        "</div>" +
        "</div>";
    } catch (err) {
      container.innerHTML =
        '<div class="barrier-alert-box" role="alert">' +
        "<div><strong>Moderator Permission Required:</strong> " +
        escapeHtml(err.message) +
        '<div style="margin-top: 0.5rem;">Use the top <strong>Quick Role Switch: Moderator (Samira)</strong> button to inspect and resolve the moderation queue.</div>' +
        "</div></div>";
    }
  }

  // ==========================================================================
  // Settings, Privacy & Data Export View
  // ==========================================================================

  async function loadSettingsAndHealth() {
    try {
      const health = await apiRequest("/api/health");
      const box = document.getElementById("platform-health-box");
      if (box) {
        box.innerHTML =
          "<div><strong>Canonical DB:</strong> " +
          escapeHtml(health.canonical_database.platform) +
          " (" +
          escapeHtml(health.canonical_database.mode) +
          ")</div>" +
          "<div><strong>Competing DB Blocked:</strong> " +
          escapeHtml((health.canonical_database.competing_stores_disabled || []).join(", ")) +
          "</div>" +
          "<div><strong>Migration Artifact:</strong> <code>" +
          escapeHtml(health.canonical_database.migration_file || "") +
          "</code></div>" +
          "<div><strong>Analytics Adapter:</strong> Tinybird (" +
          escapeHtml(health.analytics_adapter.role) +
          ")</div>";
      }
      if (state.user) {
        const sData = await apiRequest("/api/settings");
        const s = sData.settings;
        document.getElementById("set-barrier-alerts").checked = Boolean(s.barrier_alerts_enabled);
        document.getElementById("set-stale-digest").checked = Boolean(s.stale_venue_digest_enabled);
        document.getElementById("set-mod-updates").checked = Boolean(s.moderation_updates_enabled);
        document.getElementById("set-ai-consent").checked = Boolean(s.ai_consent_granted);
        document.getElementById("set-telemetry-optin").checked = Boolean(s.telemetry_opt_in);
      }
    } catch (_err) {
      // Ignore if unauthenticated
    }
  }

  // ==========================================================================
  // Form Population for Editing a Venue
  // ==========================================================================

  function populateVenueFormForEdit(venue) {
    document.getElementById("venue-form-id").value = venue.id || "";
    const modeEl = document.getElementById("venue-form-mode");
    if (modeEl) modeEl.value = venue.id ? "edit" : "create";
    const importBanner = document.getElementById("import-confirmation-banner");
    if (importBanner) importBanner.hidden = true;
    document.getElementById("heading-create-venue").textContent =
      "Edit Venue Profile: " + venue.name;
    document.getElementById("btn-submit-venue").textContent = "Save Verified Changes";

    document.getElementById("vf-name").value = venue.name;
    document.getElementById("vf-category").value = venue.category;
    document.getElementById("vf-address").value = venue.address;
    document.getElementById("vf-city").value = venue.city;
    document.getElementById("vf-postal").value = venue.postal_code;
    document.getElementById("vf-hours").value = venue.operating_hours;
    document.getElementById("vf-lat").value = venue.latitude;
    document.getElementById("vf-lng").value = venue.longitude;
    document.getElementById("vf-summary").value = venue.summary;
    document.getElementById("vf-barrier-alert").value = venue.active_barrier_alert || "";

    const a = venue.access_attributes || {};
    document.getElementById("vf-step-free").checked = Boolean(a.step_free_entrance);
    document.getElementById("vf-door-width").value = a.entrance_door_width_cm || 90;
    document.getElementById("vf-threshold").value = a.threshold_height_mm || 0;
    document.getElementById("vf-door-opener").value = a.door_opener_type || "push_button";
    document.getElementById("vf-ramp-present").checked = Boolean(a.ramp_present);
    document.getElementById("vf-ramp-slope").value =
      a.ramp_slope_degrees !== null && a.ramp_slope_degrees !== undefined
        ? a.ramp_slope_degrees
        : "";
    document.getElementById("vf-entrance-notes").value = a.entrance_notes || "";
    document.getElementById("vf-restroom").value =
      a.accessible_restroom_type || "single_user_all_gender";
    document.getElementById("vf-grab-bars").value = a.grab_bars || "both_sides";
    document.getElementById("vf-turning-circle").value = a.turning_circle_cm || 160;
    document.getElementById("vf-elevator").value = a.elevator_status || "operational";
    document.getElementById("vf-parking").value = a.accessible_parking_spaces || 0;
    document.getElementById("vf-braille").checked = Boolean(a.braille_tactile_signage);
    document.getElementById("vf-hearing").checked = Boolean(a.hearing_loop_available);
    document.getElementById("vf-quiet").checked = Boolean(a.quiet_sensory_space);
    document.getElementById("vf-surface").value = a.pathway_surface || "smooth_paved";
    document.getElementById("vf-corridor").value = a.min_corridor_width_cm || 150;
    document.getElementById("vf-lighting").value = a.lighting_level || "bright_even";
    document.getElementById("vf-acoustics").value = a.acoustic_profile || "moderate";
    document.getElementById("vf-route-notes").value = a.route_notes || "";
  }

  function resetVenueFormToCreate() {
    document.getElementById("venue-form").reset();
    document.getElementById("venue-form-id").value = "";
    const modeEl = document.getElementById("venue-form-mode");
    if (modeEl) modeEl.value = "create";
    const importBanner = document.getElementById("import-confirmation-banner");
    if (importBanner) importBanner.hidden = true;
    const importCheck = document.getElementById("vf-import-confirmed");
    if (importCheck) importCheck.checked = false;
    document.getElementById("heading-create-venue").textContent =
      "Document a Venue Profile & Physical Access Attributes";
    document.getElementById("btn-submit-venue").textContent = "Publish Verified Venue Profile";
    document.querySelectorAll(".field-error-msg").forEach(function (el) {
      el.textContent = "";
    });
  }

  // ==========================================================================
  // Event Listeners & Delegation
  // ==========================================================================

  function bindEvents() {
    document.getElementById("btn-dismiss-status").addEventListener("click", hideStatus);

    // Offline / Online Banner Detection
    window.addEventListener("offline", function () {
      const ob = document.getElementById("offline-banner");
      if (ob) ob.hidden = false;
      announce("Network connection offline.");
    });
    window.addEventListener("online", function () {
      const ob = document.getElementById("offline-banner");
      if (ob) ob.hidden = true;
      announce("Network connection restored.");
    });

    // Primary navigation tabs
    document.querySelectorAll(".nav-tab").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const view = btn.getAttribute("data-view");
        if (view === "create-venue") {
          resetVenueFormToCreate();
        }
        switchView(view);
      });
    });

    // Quick demo role switcher
    document.getElementById("quick-role-switcher").addEventListener("click", function (e) {
      const btn = e.target.closest("[data-demo-email]");
      if (!btn) return;
      const email = btn.getAttribute("data-demo-email");
      loginWithCredentials(email, "AtlasDemo!2026", false).catch(function (err) {
        showStatus(err.message, "error");
      });
    });

    // Auth modal controls + focus trap
    document.getElementById("btn-open-auth").addEventListener("click", openAuthModal);
    document.getElementById("btn-close-auth").addEventListener("click", closeAuthModal);
    document.getElementById("btn-logout").addEventListener("click", async function () {
      await apiRequest("/api/auth/logout", { method: "POST" });
      state.user = null;
      state.csrfToken = "";
      state.authToken = "";
      updateSessionUI();
      showStatus("Signed out. Switched to Guest Read-Only mode.", "");
    });

    document.addEventListener("keydown", function (e) {
      const modal = document.getElementById("auth-modal");
      if (!modal || modal.hidden) return;
      if (e.key === "Escape") {
        e.preventDefault();
        closeAuthModal();
        return;
      }
      if (e.key === "Tab") {
        const focusables = modal.querySelectorAll(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (focusables.length === 0) return;
        const firstEl = focusables[0];
        const lastEl = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === firstEl) {
          e.preventDefault();
          lastEl.focus();
        } else if (!e.shiftKey && document.activeElement === lastEl) {
          e.preventDefault();
          firstEl.focus();
        }
      }
    });

    document.getElementById("auth-login-form").addEventListener("submit", function (e) {
      e.preventDefault();
      const email = document.getElementById("auth-email").value;
      const pw = document.getElementById("auth-password").value;
      loginWithCredentials(email, pw, false).catch(function (err) {
        showStatus(err.message, "error");
      });
    });

    document.getElementById("auth-register-form").addEventListener("submit", async function (e) {
      e.preventDefault();
      try {
        const data = await apiRequest("/api/auth/register", {
          method: "POST",
          body: {
            display_name: document.getElementById("reg-name").value,
            email: document.getElementById("reg-email").value,
            password: document.getElementById("reg-password").value,
            role: document.getElementById("reg-role").value,
            ai_consent_granted: true,
            telemetry_opt_in: true,
          },
        });
        state.user = data.user;
        state.csrfToken = data.csrf_token;
        state.authToken = data.token;
        updateSessionUI();
        closeAuthModal();
        showStatus("Account created! Welcome, " + data.user.display_name + ".", "success");
      } catch (err) {
        showStatus(err.message, "error");
      }
    });

    // Search & Filters
    document.getElementById("filter-form").addEventListener("submit", function (e) {
      e.preventDefault();
      loadVenues().catch(function (err) {
        showStatus(err.message, "error");
      });
    });

    document.getElementById("btn-reset-filters").addEventListener("click", function () {
      document.getElementById("filter-form").reset();
      loadVenues();
    });

    // Save Current View
    document.getElementById("btn-save-current-view").addEventListener("click", async function () {
      const nameInput = document.getElementById("save-view-name");
      const name = (nameInput.value || "").trim();
      if (!name) {
        showStatus("Enter a name for your saved search view first.", "error");
        nameInput.focus();
        return;
      }
      try {
        const data = await apiRequest("/api/saved-views", {
          method: "POST",
          body: { name: name, filters: collectFilterParams() },
        });
        state.savedViews.unshift(data.saved_view);
        nameInput.value = "";
        renderSavedViewsBar();
        showStatus("Saved view '" + data.saved_view.name + "'.", "success");
      } catch (err) {
        showStatus(err.message, "error");
      }
    });

    // Saved Views load/delete delegation
    document.getElementById("saved-views-container").addEventListener("click", async function (e) {
      const loadBtn = e.target.closest("[data-load-view]");
      if (loadBtn) {
        const id = loadBtn.getAttribute("data-load-view");
        const found = state.savedViews.find(function (v) { return v.id === id; });
        if (found) {
          applyFilterParamsToForm(found.filters);
          await loadVenues();
          showStatus("Applied saved view: " + found.name, "success");
        }
        return;
      }
      const delBtn = e.target.closest("[data-delete-view]");
      if (delBtn) {
        const id = delBtn.getAttribute("data-delete-view");
        try {
          await apiRequest("/api/saved-views/" + encodeURIComponent(id), { method: "DELETE" });
          state.savedViews = state.savedViews.filter(function (v) { return v.id !== id; });
          renderSavedViewsBar();
          showStatus("Deleted saved view.", "success");
        } catch (err) {
          showStatus(err.message, "error");
        }
      }
    });

    // Map + List toggle & CTA
    document.getElementById("btn-toggle-map-layout").addEventListener("click", function (e) {
      state.splitMapVisible = !state.splitMapVisible;
      const split = document.getElementById("directory-split-container");
      split.classList.toggle("layout-list-only", !state.splitMapVisible);
      e.currentTarget.setAttribute("aria-pressed", String(state.splitMapVisible));
      e.currentTarget.textContent = state.splitMapVisible
        ? "Map + List Split View"
        : "Show Coordinate Map";
    });

    document.getElementById("btn-cta-document-venue").addEventListener("click", function () {
      resetVenueFormToCreate();
      switchView("create-venue");
    });

    document.getElementById("btn-cancel-venue-form").addEventListener("click", function () {
      switchView("directory");
    });

    document.getElementById("btn-reset-venue-form").addEventListener("click", resetVenueFormToCreate);

    // Map Pin Click, Keyboard Enter & Zoom Controls
    const svgMap = document.getElementById("atlas-vector-map");
    svgMap.addEventListener("click", function (e) {
      const pin = e.target.closest("[data-venue-id]");
      if (pin) {
        openVenueDetail(pin.getAttribute("data-venue-id"));
      }
    });
    svgMap.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        const pin = e.target.closest("[data-venue-id]");
        if (pin) {
          e.preventDefault();
          openVenueDetail(pin.getAttribute("data-venue-id"));
        }
      }
    });

    const zoomInBtn = document.getElementById("btn-map-zoom-in");
    const zoomOutBtn = document.getElementById("btn-map-zoom-out");
    const zoomResetBtn = document.getElementById("btn-map-zoom-reset");
    if (zoomInBtn) {
      zoomInBtn.addEventListener("click", function () {
        state.mapZoom = Math.min(2.25, (state.mapZoom || 1.0) + 0.25);
        applyMapZoom();
        announce("Map zoom increased to " + Math.round(state.mapZoom * 100) + "%.");
      });
    }
    if (zoomOutBtn) {
      zoomOutBtn.addEventListener("click", function () {
        state.mapZoom = Math.max(0.75, (state.mapZoom || 1.0) - 0.25);
        applyMapZoom();
        announce("Map zoom decreased to " + Math.round(state.mapZoom * 100) + "%.");
      });
    }
    if (zoomResetBtn) {
      zoomResetBtn.addEventListener("click", function () {
        state.mapZoom = 1.0;
        applyMapZoom();
        announce("Map zoom reset to 100%.");
      });
    }

    // Structured JSON Import Workflow (Journey A.3 / B.1 / B.3)
    const sampleImportBtn = document.getElementById("btn-load-sample-import");
    const parseImportBtn = document.getElementById("btn-parse-import-to-form");
    if (sampleImportBtn) {
      sampleImportBtn.addEventListener("click", function () {
        const sample = {
          name: "Belltown Civic Makerspace & Ramp Annex",
          category: "community_center",
          address: "2314 1st Ave",
          city: "Seattle",
          postal_code: "98121",
          operating_hours: "Mon–Sat 09:00–20:00",
          latitude: 47.6144,
          longitude: -122.3456,
          summary:
            "Imported municipal audit record: ground-floor fabrication lab with automatic 96 cm sliding doors, 175 cm restroom turning circle, and induction loop.",
          active_barrier_alert: null,
          access_attributes: {
            step_free_entrance: true,
            entrance_door_width_cm: 96,
            threshold_height_mm: 0,
            door_opener_type: "motion_sensor",
            ramp_present: false,
            ramp_slope_degrees: null,
            entrance_notes: "Flush sidewalk entry at 1st Ave.",
            accessible_restroom_type: "single_user_all_gender",
            grab_bars: "both_sides",
            turning_circle_cm: 175,
            elevator_status: "none",
            accessible_parking_spaces: 2,
            braille_tactile_signage: true,
            hearing_loop_available: true,
            quiet_sensory_space: true,
            pathway_surface: "smooth_paved",
            min_corridor_width_cm: 165,
            lighting_level: "bright_even",
            acoustic_profile: "moderate",
            route_notes: "Wide 165 cm aisles between workbenches.",
          },
        };
        const ta = document.getElementById("import-json-textarea");
        if (ta) ta.value = JSON.stringify(sample, null, 2);
        showStatus("Loaded sample municipal accessibility audit JSON. Click 'Parse & Pre-Fill Form for Human Review' next.", "success");
      });
    }
    if (parseImportBtn) {
      parseImportBtn.addEventListener("click", function () {
        const ta = document.getElementById("import-json-textarea");
        if (!ta || !ta.value.trim()) {
          showStatus("Paste or load a structured JSON record before parsing.", "error");
          return;
        }
        try {
          const parsed = JSON.parse(ta.value);
          populateVenueFormForEdit(parsed);
          document.getElementById("venue-form-id").value = "";
          const modeEl = document.getElementById("venue-form-mode");
          if (modeEl) modeEl.value = "import";
          document.getElementById("heading-create-venue").textContent =
            "Review & Confirm Imported Venue: " + (parsed.name || "Untitled");
          document.getElementById("btn-submit-venue").textContent =
            "Confirm & Publish Imported Venue Profile";
          const importBanner = document.getElementById("import-confirmation-banner");
          if (importBanner) importBanner.hidden = false;
          const importCheck = document.getElementById("vf-import-confirmed");
          if (importCheck) importCheck.checked = false;
          showStatus(
            "Pre-filled form from imported JSON. Inspect fields and check the confirmation box below before publishing.",
            "success"
          );
        } catch (_err) {
          showStatus("Invalid JSON syntax in import box. Please check formatting.", "error");
        }
      });
    }

    // Venue List delegation
    document.getElementById("venue-list-container").addEventListener("click", function (e) {
      const inspectBtn = e.target.closest("[data-inspect-venue]");
      if (inspectBtn) {
        openVenueDetail(inspectBtn.getAttribute("data-inspect-venue"));
        return;
      }
      if (e.target.id === "btn-empty-reset") {
        document.getElementById("filter-form").reset();
        loadVenues();
      } else if (e.target.id === "btn-empty-create") {
        resetVenueFormToCreate();
        switchView("create-venue");
      }
    });

    // Create / Update / Import Venue Form submission
    document.getElementById("venue-form").addEventListener("submit", async function (e) {
      e.preventDefault();
      document.querySelectorAll(".field-error-msg").forEach(function (el) {
        el.textContent = "";
      });

      const editId = document.getElementById("venue-form-id").value;
      const modeEl = document.getElementById("venue-form-mode");
      const formMode = modeEl ? modeEl.value : "create";
      const slopeVal = document.getElementById("vf-ramp-slope").value;
      const payload = {
        name: document.getElementById("vf-name").value,
        category: document.getElementById("vf-category").value,
        address: document.getElementById("vf-address").value,
        city: document.getElementById("vf-city").value,
        postal_code: document.getElementById("vf-postal").value,
        operating_hours: document.getElementById("vf-hours").value,
        latitude: parseFloat(document.getElementById("vf-lat").value),
        longitude: parseFloat(document.getElementById("vf-lng").value),
        summary: document.getElementById("vf-summary").value,
        active_barrier_alert: document.getElementById("vf-barrier-alert").value || null,
        status: "published",
        access_attributes: {
          step_free_entrance: document.getElementById("vf-step-free").checked,
          entrance_door_width_cm: parseInt(document.getElementById("vf-door-width").value, 10),
          threshold_height_mm: parseInt(document.getElementById("vf-threshold").value, 10),
          door_opener_type: document.getElementById("vf-door-opener").value,
          ramp_present: document.getElementById("vf-ramp-present").checked,
          ramp_slope_degrees: slopeVal ? parseFloat(slopeVal) : null,
          entrance_notes: document.getElementById("vf-entrance-notes").value,
          accessible_restroom_type: document.getElementById("vf-restroom").value,
          grab_bars: document.getElementById("vf-grab-bars").value,
          turning_circle_cm: parseInt(document.getElementById("vf-turning-circle").value, 10),
          elevator_status: document.getElementById("vf-elevator").value,
          accessible_parking_spaces: parseInt(document.getElementById("vf-parking").value, 10),
          braille_tactile_signage: document.getElementById("vf-braille").checked,
          hearing_loop_available: document.getElementById("vf-hearing").checked,
          quiet_sensory_space: document.getElementById("vf-quiet").checked,
          pathway_surface: document.getElementById("vf-surface").value,
          min_corridor_width_cm: parseInt(document.getElementById("vf-corridor").value, 10),
          lighting_level: document.getElementById("vf-lighting").value,
          acoustic_profile: document.getElementById("vf-acoustics").value,
          route_notes: document.getElementById("vf-route-notes").value,
        },
      };

      try {
        let data;
        if (editId) {
          data = await apiRequest("/api/venues/" + encodeURIComponent(editId), {
            method: "PUT",
            body: payload,
          });
          showStatus("Updated venue profile: " + data.venue.name, "success");
        } else if (formMode === "import") {
          const importConfirmed = document.getElementById("vf-import-confirmed").checked;
          data = await apiRequest("/api/venues/import", {
            method: "POST",
            body: {
              venue_data: payload,
              import_source: "json_upload",
              user_confirmed_imported_values: importConfirmed,
            },
          });
          showStatus("Confirmed & published imported venue profile: " + data.venue.name, "success");
        } else {
          data = await apiRequest("/api/venues", {
            method: "POST",
            body: payload,
          });
          showStatus("Published new venue profile: " + data.venue.name, "success");
        }
        await loadVenues();
        await openVenueDetail(data.venue.id);
      } catch (err) {
        if (err.fieldErrors) {
          Object.keys(err.fieldErrors).forEach(function (fieldKey) {
            const errEl = document.getElementById("err-" + fieldKey);
            if (errEl) {
              errEl.textContent = err.fieldErrors[fieldKey];
            }
          });
        }
        showStatus(err.message, "error");
      }
    });

    // Back button & owner actions in Venue Detail
    document.getElementById("btn-back-to-directory").addEventListener("click", function () {
      switchView("directory");
    });

    document.getElementById("detail-owner-actions").addEventListener("click", async function (e) {
      const v = state.selectedVenue;
      if (!v) return;
      if (e.target.id === "btn-edit-venue") {
        populateVenueFormForEdit(v);
        switchView("create-venue");
      } else if (e.target.id === "btn-archive-venue") {
        try {
          await apiRequest("/api/venues/" + encodeURIComponent(v.id) + "/archive", {
            method: "POST",
            body: { confirm: true },
          });
          showStatus("Venue archived with audit trail entry.", "success");
          await loadVenues();
          switchView("directory");
        } catch (err) {
          showStatus(err.message, "error");
        }
      } else if (e.target.id === "btn-delete-venue") {
        try {
          await apiRequest("/api/venues/" + encodeURIComponent(v.id) + "?confirm=true", {
            method: "DELETE",
          });
          showStatus("Venue deleted permanently.", "success");
          await loadVenues();
          switchView("directory");
        } catch (err) {
          showStatus(err.message, "error");
        }
      }
    });

    // Dynamic forms inside Venue Detail View
    const detailContainer = document.getElementById("venue-detail-content");
    detailContainer.addEventListener("click", async function (e) {
      if (e.target.id === "btn-generate-briefing" && state.selectedVenue) {
        try {
          const data = await apiRequest(
            "/api/venues/" + encodeURIComponent(state.selectedVenue.id) + "/briefing",
            {
              method: "POST",
              body: { explicit_consent: true },
            }
          );
          const b = data.briefing;
          const box = document.getElementById("venue-briefing-box");
          if (box) {
            box.hidden = false;
            box.innerHTML =
              '<div style="background: var(--surface-panel); border: 1px solid var(--color-acid-lime); padding: 0.85rem; border-radius: var(--radius-sm);">' +
              '<div style="font-family: var(--font-mono); font-size: 0.74rem; color: var(--color-acid-lime); margin-bottom: 0.4rem;">' +
              "SYNTHESIZED ACCESSIBILITY BRIEFING · Provider: " +
              escapeHtml(b.provider) +
              "</div>" +
              '<ul style="margin: 0; padding-left: 1.2rem; font-size: 0.86rem;">' +
              (b.briefing_points || [])
                .map(function (pt) {
                  return "<li>" + escapeHtml(pt) + "</li>";
                })
                .join("") +
              "</ul>" +
              '<div style="font-size: 0.74rem; color: var(--text-secondary); margin-top: 0.4rem;">' +
              escapeHtml(b.disclaimer) +
              "</div>" +
              "</div>";
          }
        } catch (err) {
          showStatus(err.message, "error");
        }
      }
    });

    detailContainer.addEventListener("submit", async function (e) {
      const v = state.selectedVenue;
      if (!v) return;

      if (e.target.id === "geospatial-route-form") {
        e.preventDefault();
        try {
          const origLat = parseFloat(document.getElementById("geo-origin-lat").value);
          const origLng = parseFloat(document.getElementById("geo-origin-lng").value);
          const modeVal = document.getElementById("geo-travel-mode").value;
          const data = await apiRequest(
            "/api/venues/" + encodeURIComponent(v.id) + "/geospatial",
            {
              method: "POST",
              body: {
                origin_lat: origLat,
                origin_lng: origLng,
                origin_label: "Custom Origin (" + origLat.toFixed(4) + ", " + origLng.toFixed(4) + ")",
                travel_mode: modeVal,
              },
            }
          );
          state.selectedVenue.google_maps_earth = data.geospatial;
          renderVenueDetail();
          const modeSelect = document.getElementById("geo-travel-mode");
          if (modeSelect) modeSelect.value = modeVal;
          showStatus(
            "Updated Google Maps / Earth route: " +
              data.geospatial.route_from_origin.estimated_sidewalk_distance_meters +
              " m (" +
              data.geospatial.route_from_origin.estimated_roll_minutes +
              " min).",
            "success"
          );
        } catch (err) {
          showStatus(err.message, "error");
        }
        return;
      }

      if (e.target.id === "observation-form") {
        e.preventDefault();
        const doorVal = document.getElementById("obs-door-cm").value;
        const elevVal = document.getElementById("obs-elevator").value;
        try {
          const data = await apiRequest(
            "/api/venues/" + encodeURIComponent(v.id) + "/observations",
            {
              method: "POST",
              body: {
                observer_role: document.getElementById("obs-role").value,
                confidence_level: document.getElementById("obs-confidence").value,
                measured_door_width_cm: doorVal ? parseInt(doorVal, 10) : null,
                elevator_operational_check: elevVal || null,
                summary: document.getElementById("obs-summary").value,
                barriers_noted: document.getElementById("obs-barriers").value,
                is_operational_alert: document.getElementById("obs-alert").checked,
              },
            }
          );
          state.selectedVenue = data.venue;
          renderVenueDetail();
          await loadVenues();
          showStatus("Timestamped observation recorded & freshness updated.", "success");
        } catch (err) {
          showStatus(err.message, "error");
        }
      } else if (e.target.id === "photo-upload-form") {
        e.preventDefault();
        const fileInput = document.getElementById("photo-file");
        const facesOk = document.getElementById("photo-consent-faces").checked;
        const areaOk = document.getElementById("photo-consent-area").checked;

        try {
          let fileB64 = "";
          if (fileInput.files && fileInput.files[0]) {
            fileB64 = await new Promise(function (resolve, reject) {
              const reader = new FileReader();
              reader.onload = function () { resolve(reader.result); };
              reader.onerror = function () { reject(new Error("File read failed")); };
              reader.readAsDataURL(fileInput.files[0]);
            });
          } else {
            fileB64 = generateClientSamplePngBase64();
          }

          const data = await apiRequest(
            "/api/venues/" + encodeURIComponent(v.id) + "/photos",
            {
              method: "POST",
              body: {
                category: document.getElementById("photo-category").value,
                alt_text: document.getElementById("photo-alt").value,
                caption: document.getElementById("photo-caption").value,
                no_identifiable_faces_confirmed: facesOk,
                operator_or_public_area_consent: areaOk,
                file_base64: fileB64,
              },
            }
          );
          state.selectedVenue = data.venue;
          renderVenueDetail();
          showStatus(
            "Photo evidence validated, EXIF GPS stripped, and stored (" +
              data.photo.consent_status +
              ").",
            "success"
          );
        } catch (err) {
          showStatus(err.message, "error");
        }
      } else if (e.target.id === "moderation-report-form") {
        e.preventDefault();
        try {
          await apiRequest("/api/moderation/reports", {
            method: "POST",
            body: {
              venue_id: v.id,
              target_type: "venue",
              target_id: v.id,
              reason: document.getElementById("mod-reason").value,
              details: document.getElementById("mod-details").value,
            },
          });
          document.getElementById("mod-details").value = "";
          showStatus("Moderation flag submitted to workspace review queue.", "success");
        } catch (err) {
          showStatus(err.message, "error");
        }
      }
    });

    // Insights view delegation
    document.getElementById("btn-refresh-insights").addEventListener("click", loadInsights);
    document.getElementById("insights-container").addEventListener("click", function (e) {
      const btn = e.target.closest("[data-inspect-venue]");
      if (btn) {
        openVenueDetail(btn.getAttribute("data-inspect-venue"));
      }
    });

    // Moderation queue actions
    document.getElementById("btn-refresh-moderation").addEventListener("click", loadModerationQueue);
    document.getElementById("moderation-container").addEventListener("click", async function (e) {
      const resolveBtn = e.target.closest("[data-resolve-report]");
      if (resolveBtn) {
        const repId = resolveBtn.getAttribute("data-resolve-report");
        const status = resolveBtn.getAttribute("data-resolve-status");
        const notesEl = document.getElementById("mod-note-" + repId);
        const confirmEl = document.getElementById("mod-confirm-" + repId);
        try {
          await apiRequest("/api/moderation/reports/" + encodeURIComponent(repId) + "/resolve", {
            method: "POST",
            body: {
              status: status,
              resolution_notes: notesEl ? notesEl.value : "",
              confirm: confirmEl ? confirmEl.checked : false,
            },
          });
          showStatus("Moderation report resolved (" + status + ").", "success");
          await loadModerationQueue();
        } catch (err) {
          showStatus(err.message, "error");
        }
        return;
      }

      const photoBtn = e.target.closest("[data-review-photo]");
      if (photoBtn) {
        const photoId = photoBtn.getAttribute("data-review-photo");
        const cStatus = photoBtn.getAttribute("data-photo-status");
        const notesEl = document.getElementById("photo-note-" + photoId);
        const confirmEl = document.getElementById("photo-confirm-" + photoId);
        try {
          await apiRequest("/api/photos/" + encodeURIComponent(photoId) + "/review", {
            method: "POST",
            body: {
              consent_status: cStatus,
              review_notes: notesEl ? notesEl.value : "",
              confirm: confirmEl ? confirmEl.checked : false,
            },
          });
          showStatus("Photo consent status updated to " + cStatus + ".", "success");
          await loadModerationQueue();
          await loadVenues();
        } catch (err) {
          showStatus(err.message, "error");
        }
      }
    });

    // Settings & Data Portability Export
    document.getElementById("settings-form").addEventListener("submit", async function (e) {
      e.preventDefault();
      try {
        await apiRequest("/api/settings", {
          method: "PUT",
          body: {
            barrier_alerts_enabled: document.getElementById("set-barrier-alerts").checked,
            stale_venue_digest_enabled: document.getElementById("set-stale-digest").checked,
            moderation_updates_enabled: document.getElementById("set-mod-updates").checked,
            ai_consent_granted: document.getElementById("set-ai-consent").checked,
            telemetry_opt_in: document.getElementById("set-telemetry-optin").checked,
          },
        });
        showStatus("Privacy, consent, and notification preferences saved.", "success");
      } catch (err) {
        showStatus(err.message, "error");
      }
    });

    document.getElementById("btn-export-workspace").addEventListener("click", async function () {
      const confirmed = document.getElementById("export-confirm-check").checked;
      try {
        const bundle = await apiRequest("/api/export", {
          method: "POST",
          body: { confirm: confirmed },
        });
        const preview = document.getElementById("export-preview-box");
        preview.hidden = false;
        preview.textContent = JSON.stringify(bundle, null, 2);
        showStatus("Workspace data portability bundle exported with provenance.", "success");
      } catch (err) {
        showStatus(err.message, "error");
      }
    });

    const deleteAccountForm = document.getElementById("account-delete-form");
    if (deleteAccountForm) {
      deleteAccountForm.addEventListener("submit", async function (e) {
        e.preventDefault();
        const confirmChecked = document.getElementById("delete-account-confirm-check").checked;
        const phrase = (document.getElementById("delete-account-phrase").value || "").trim();
        try {
          await apiRequest("/api/account/delete", {
            method: "POST",
            body: {
              confirm: confirmChecked,
              confirmation_phrase: phrase,
            },
          });
          state.user = null;
          state.csrfToken = "";
          state.authToken = "";
          state.savedViews = [];
          updateSessionUI();
          deleteAccountForm.reset();
          showStatus(
            "Personal account data anonymized and session revoked. Public civic observations retained as Anonymized Contributor.",
            "success"
          );
          switchView("directory");
        } catch (err) {
          showStatus(err.message, "error");
        }
      });
    }
  }

  async function bootstrap() {
    bindEvents();
    await initMetadata();
    await checkCurrentSession();

    const urlParams = new URLSearchParams(window.location.search || "");
    const roleParam = urlParams.get("role");
    const roleEmails = {
      contributor: "maya.chen@atlas-demo.local",
      operator: "alex.rivera@atlas-demo.local",
      moderator: "samira.khan@atlas-demo.local",
      viewer: "jordan.lee@atlas-demo.local",
    };
    if (roleParam && roleEmails[roleParam]) {
      try {
        await loginWithCredentials(roleEmails[roleParam], "AtlasDemo!2026", true);
      } catch (_e) {
        // Fallback to default session
      }
    }

    await loadVenues();

    const viewParam = urlParams.get("view");
    const venueParam = urlParams.get("venue");
    if (venueParam) {
      await openVenueDetail(venueParam);
    } else if (viewParam === "venue-detail" && state.venues.length > 0) {
      await openVenueDetail(state.venues[0].id);
    } else if (
      viewParam &&
      ["directory", "create-venue", "insights", "moderation", "settings"].indexOf(viewParam) !== -1
    ) {
      switchView(viewParam);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap);
  } else {
    bootstrap();
  }
})();
