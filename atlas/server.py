"""Tornado HTTP server, security middleware, and REST API handlers for AccessAble Atlas."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
import tornado.httpserver
import tornado.ioloop
import tornado.web

from atlas.adapters.ai_summary_adapter import AISummaryAdapter
from atlas.adapters.google_maps_adapter import GoogleMapsEarthAdapter
from atlas.adapters.supabase_adapter import SupabaseAdapter
from atlas.adapters.tinybird_adapter import TinybirdAdapter
from atlas.auth import (
    AuthenticationError,
    AuthorizationError,
    RevokedTokenStore,
    authorize_action,
    create_session_token,
    decode_session_token,
    verify_csrf_token,
)
from atlas.background_jobs import BackgroundJobRunner
from atlas.config import AtlasConfig, load_config
from atlas.db.database import AtlasDatabase
from atlas.db.seed import seed_if_empty
from atlas.domain import (
    ACOUSTIC_PROFILES,
    CONFIDENCE_LABELS,
    DOOR_OPENER_TYPES,
    ELEVATOR_STATUSES,
    GRAB_BAR_TYPES,
    LIGHTING_LEVELS,
    MODERATION_REASONS,
    OBSERVER_ROLES,
    PATHWAY_SURFACES,
    PHOTO_CATEGORIES,
    RESTROOM_TYPES,
    VENUE_CATEGORIES,
)
from atlas.feature_flags import FeatureFlagRegistry
from atlas.logging_utils import StructuredLogger
from atlas.modules import DomainModulesContainer
from atlas.rate_limit import IdempotencyStore, RateLimitExceededError, SlidingWindowRateLimiter
from atlas.schemas import BOUNDARY_SCHEMA_REGISTRY
from atlas.validation import (
    ValidationError,
    validate_account_deletion_payload,
    validate_and_scrub_photo_upload,
    validate_auth_payload,
    validate_moderation_report_payload,
    validate_moderation_resolution_payload,
    validate_observation_payload,
    validate_photo_review_payload,
    validate_saved_view_payload,
    validate_settings_payload,
    validate_venue_import_payload,
    validate_venue_payload,
)

STATIC_ROOT = Path(__file__).resolve().parent / "static"


class BaseAPIHandler(tornado.web.RequestHandler):
    """Base request handler enforcing security headers, CORS, rate limits, auth, and CSRF."""

    @property
    def app_config(self) -> AtlasConfig:
        return self.settings["atlas_config"]

    @property
    def db(self) -> AtlasDatabase:
        return self.settings["atlas_db"]

    @property
    def rate_limiter(self) -> SlidingWindowRateLimiter:
        return self.settings["rate_limiter"]

    @property
    def idempotency_store(self) -> IdempotencyStore:
        return self.settings["idempotency_store"]

    @property
    def revoked_tokens(self) -> RevokedTokenStore:
        return self.settings["revoked_tokens"]

    @property
    def supabase_adapter(self) -> SupabaseAdapter:
        return self.settings["supabase_adapter"]

    @property
    def tinybird_adapter(self) -> TinybirdAdapter:
        return self.settings["tinybird_adapter"]

    @property
    def ai_adapter(self) -> AISummaryAdapter:
        return self.settings["ai_adapter"]

    @property
    def google_maps_adapter(self) -> GoogleMapsEarthAdapter:
        return self.settings["google_maps_adapter"]

    @property
    def domain_modules(self) -> DomainModulesContainer:
        return self.settings["domain_modules"]

    @property
    def feature_flags(self) -> FeatureFlagRegistry:
        return self.settings["feature_flags"]

    @property
    def structured_logger(self) -> StructuredLogger:
        return self.settings["structured_logger"]

    @property
    def background_jobs(self) -> BackgroundJobRunner:
        return self.settings["background_jobs"]

    def set_default_headers(self) -> None:
        self.set_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("X-Frame-Options", "DENY")
        self.set_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.set_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        self.set_header("Cross-Origin-Opener-Policy", "same-origin")
        self.set_header("Cross-Origin-Resource-Policy", "same-origin")
        self.set_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.set_header("Cache-Control", "no-store")

        origin = self.request.headers.get("Origin")
        if origin and origin in self.app_config.allowed_origins:
            self.set_header("Access-Control-Allow-Origin", origin)
            self.set_header("Access-Control-Allow-Credentials", "true")
            self.set_header(
                "Access-Control-Allow-Headers",
                "Content-Type, Authorization, X-CSRF-Token, X-Idempotency-Key",
            )
            self.set_header(
                "Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS"
            )
            self.set_header("Vary", "Origin")

    def options(self, *args: Any, **kwargs: Any) -> None:
        origin = self.request.headers.get("Origin")
        if origin and origin not in self.app_config.allowed_origins:
            self.set_status(403)
            self.finish(json.dumps({"error": "cors_origin_denied"}))
            return
        self.set_status(204)
        self.finish()

    def prepare(self) -> None:
        if self.request.method == "OPTIONS":
            return

        # Strict CORS check on state-changing requests with an Origin header
        origin = self.request.headers.get("Origin")
        if (
            origin
            and self.request.method in ("POST", "PUT", "PATCH", "DELETE")
            and origin not in self.app_config.allowed_origins
        ):
            self.write_json(
                403,
                {
                    "error": "forbidden_origin",
                    "message": "Cross-origin write request blocked by strict CORS policy.",
                },
            )
            self.finish()
            return

        # Enforce payload size bounds before parsing
        content_len = len(self.request.body or b"")
        is_upload_route = self.request.path.endswith("/photos")
        max_allowed = (
            self.app_config.max_upload_bytes + 65536
            if is_upload_route
            else self.app_config.max_json_body_bytes
        )
        if content_len > max_allowed:
            self.write_json(
                413,
                {
                    "error": "payload_too_large",
                    "message": f"Request payload ({content_len} bytes) exceeds maximum limit ({max_allowed} bytes).",
                },
            )
            self.finish()
            return

        # Sliding-window rate limiting
        client_ip = self.request.remote_ip or "127.0.0.1"
        is_write = self.request.method in ("POST", "PUT", "PATCH", "DELETE")
        bucket_type = "write" if is_write else "read"
        limit = (
            self.app_config.rate_limit_write_per_min
            if is_write
            else self.app_config.rate_limit_read_per_min
        )
        try:
            rl_info = self.rate_limiter.check_and_record(f"{bucket_type}:{client_ip}", limit)
            self.set_header("X-RateLimit-Limit", str(rl_info["limit"]))
            self.set_header("X-RateLimit-Remaining", str(rl_info["remaining"]))
        except RateLimitExceededError as exc:
            self.set_header("Retry-After", str(exc.retry_after_seconds))
            self.write_json(
                429,
                {
                    "error": "rate_limit_exceeded",
                    "message": str(exc),
                    "retry_after_seconds": exc.retry_after_seconds,
                },
            )
            self.finish()
            return

    def get_session_claims_and_user(
        self, require_csrf: bool = False
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        token = ""
        auth_header = self.request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        if not token:
            cookie_val = self.get_cookie("atlas_session")
            if cookie_val:
                token = cookie_val.strip()

        if not token:
            return None, None

        claims = decode_session_token(token, self.app_config.jwt_secret)
        if self.revoked_tokens.is_revoked(str(claims.get("jti") or "")):
            raise AuthenticationError("Session token has been revoked by sign-out.")
        user = self.db.get_user_by_id(str(claims["sub"]))
        if not user:
            raise AuthenticationError("User account for this session no longer exists.")

        if require_csrf:
            provided_csrf = self.request.headers.get("X-CSRF-Token")
            if not verify_csrf_token(str(claims.get("csrf") or ""), provided_csrf):
                raise AuthorizationError(
                    "Invalid or missing X-CSRF-Token header for state-changing request."
                )

        return claims, user

    def parse_json_body(self) -> dict[str, Any]:
        if not self.request.body:
            raise ValidationError("Request body is empty; expected a JSON object.")
        try:
            parsed = json.loads(self.request.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(f"Malformed JSON request body: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValidationError("JSON body must be an object.")
        return parsed

    def write_json(self, status_code: int, payload: dict[str, Any]) -> None:
        self.set_status(status_code)
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.write(json.dumps(payload, ensure_ascii=False))

    def handle_domain_exception(self, exc: Exception) -> None:
        if isinstance(exc, ValidationError):
            self.write_json(400, exc.to_dict())
        elif isinstance(exc, AuthenticationError):
            self.write_json(401, {"error": "unauthorized", "message": str(exc)})
        elif isinstance(exc, (AuthorizationError, PermissionError)):
            self.write_json(403, {"error": "forbidden", "message": str(exc)})
        elif isinstance(exc, LookupError):
            self.write_json(404, {"error": "not_found", "message": str(exc)})
        elif isinstance(exc, ValueError):
            self.write_json(400, {"error": "bad_request", "message": str(exc)})
        else:
            # Redact internal stack traces from client responses
            self.write_json(
                500,
                {
                    "error": "internal_server_error",
                    "message": "An unexpected server error occurred. Details have been safely redacted.",
                },
            )


class HealthHandler(BaseAPIHandler):
    def get(self) -> None:
        self.write_json(
            200,
            {
                "status": "ok",
                "product": "AccessAble Atlas",
                "tagline": "Find places through the details that matter.",
                "design_system": "Sage Circuit",
                "architecture_layers": [
                    "UI (responsive, accessible)",
                    "API/server actions (validation, authz)",
                    "domain modules",
                    "Supabase",
                    "background jobs",
                ],
                "domain_modules": self.domain_modules.describe_all(),
                "feature_flags": self.feature_flags.to_dict(),
                "background_jobs": self.background_jobs.get_status(),
                "canonical_database": self.supabase_adapter.get_status(),
                "analytics_adapter": self.tinybird_adapter.get_status(),
                "google_maps_earth_adapter": self.google_maps_adapter.get_status(),
                "ai_adapter": {
                    "enabled": self.app_config.ai_enabled,
                    "provider": self.app_config.ai_provider,
                    "mvp_requires_llm": False,
                },
            },
        )


class TaxonomiesHandler(BaseAPIHandler):
    def get(self) -> None:
        self.write_json(
            200,
            {
                "venue_categories": VENUE_CATEGORIES,
                "door_opener_types": DOOR_OPENER_TYPES,
                "restroom_types": RESTROOM_TYPES,
                "grab_bar_types": GRAB_BAR_TYPES,
                "elevator_statuses": ELEVATOR_STATUSES,
                "pathway_surfaces": PATHWAY_SURFACES,
                "lighting_levels": LIGHTING_LEVELS,
                "acoustic_profiles": ACOUSTIC_PROFILES,
                "observer_roles": OBSERVER_ROLES,
                "confidence_labels": CONFIDENCE_LABELS,
                "photo_categories": PHOTO_CATEGORIES,
                "moderation_reasons": MODERATION_REASONS,
                "boundary_schemas": list(BOUNDARY_SCHEMA_REGISTRY.keys()),
                "feature_flags": self.feature_flags.to_dict(),
                "demo_accounts": self.db.list_demo_accounts(),
            },
        )


class AuthLoginHandler(BaseAPIHandler):
    def post(self) -> None:
        try:
            body = self.parse_json_body()
            validated = validate_auth_payload(body, is_register=False)
            client_ip = self.request.remote_ip or "127.0.0.1"
            user = self.db.authenticate_user(validated["email"], validated["password"])
            if not user:
                try:
                    self.rate_limiter.check_and_record(
                        f"auth_fail:{client_ip}:{validated['email']}", limit=5
                    )
                except RateLimitExceededError as rl_exc:
                    self.set_header("Retry-After", str(rl_exc.retry_after_seconds))
                    self.write_json(
                        429,
                        {
                            "error": "rate_limit_exceeded",
                            "message": "Too many failed sign-in attempts. Please wait before retrying.",
                            "retry_after_seconds": rl_exc.retry_after_seconds,
                        },
                    )
                    return
                raise AuthenticationError("Invalid email or password.")
            session = create_session_token(
                user=user,
                secret=self.app_config.jwt_secret,
                ttl_seconds=self.app_config.session_ttl_seconds,
            )
            self.set_cookie(
                "atlas_session",
                session["token"],
                httponly=True,
                samesite="Lax",
                secure=(self.app_config.env == "production"),
                max_age=self.app_config.session_ttl_seconds,
                path="/",
            )
            self.write_json(
                200,
                {
                    "user": user,
                    "csrf_token": session["csrf_token"],
                    "token": session["token"],
                    "expires_at": session["expires_at"],
                    "settings": self.db.get_user_settings(str(user["id"])),
                    "saved_views": self.db.list_saved_views(str(user["id"])),
                },
            )
        except Exception as exc:
            self.handle_domain_exception(exc)


class AuthRegisterHandler(BaseAPIHandler):
    def post(self) -> None:
        try:
            body = self.parse_json_body()
            validated = validate_auth_payload(body, is_register=True)
            user = self.db.register_user(
                email=validated["email"],
                password=validated["password"],
                display_name=validated["display_name"],
                role=validated["role"],
                ai_consent_granted=validated["ai_consent_granted"],
                telemetry_opt_in=validated["telemetry_opt_in"],
            )
            session = create_session_token(
                user=user,
                secret=self.app_config.jwt_secret,
                ttl_seconds=self.app_config.session_ttl_seconds,
            )
            self.set_cookie(
                "atlas_session",
                session["token"],
                httponly=True,
                samesite="Lax",
                secure=(self.app_config.env == "production"),
                max_age=self.app_config.session_ttl_seconds,
                path="/",
            )
            self.write_json(
                201,
                {
                    "user": user,
                    "csrf_token": session["csrf_token"],
                    "token": session["token"],
                    "expires_at": session["expires_at"],
                    "settings": self.db.get_user_settings(str(user["id"])),
                    "saved_views": [],
                },
            )
        except Exception as exc:
            self.handle_domain_exception(exc)


class AuthLogoutHandler(BaseAPIHandler):
    def post(self) -> None:
        try:
            claims, _ = self.get_session_claims_and_user(require_csrf=False)
            if claims and claims.get("jti"):
                self.revoked_tokens.revoke(
                    str(claims["jti"]), float(claims.get("exp") or 0)
                )
        except Exception:
            pass
        self.clear_cookie("atlas_session", path="/")
        self.write_json(200, {"logged_out": True})


class AuthMeHandler(BaseAPIHandler):
    def get(self) -> None:
        try:
            claims, user = self.get_session_claims_and_user(require_csrf=False)
            if not user or not claims:
                self.write_json(200, {"authenticated": False, "user": None})
                return
            self.write_json(
                200,
                {
                    "authenticated": True,
                    "user": user,
                    "csrf_token": claims["csrf"],
                    "settings": self.db.get_user_settings(str(user["id"])),
                    "saved_views": self.db.list_saved_views(str(user["id"])),
                },
            )
        except Exception as exc:
            self.clear_cookie("atlas_session", path="/")
            self.handle_domain_exception(exc)


class VenuesCollectionHandler(BaseAPIHandler):
    def get(self) -> None:
        try:
            try:
                _, user = self.get_session_claims_and_user(require_csrf=False)
            except AuthenticationError:
                user = None

            def bool_arg(name: str) -> bool:
                return self.get_query_argument(name, "false").lower() in ("1", "true", "yes")

            min_door_raw = self.get_query_argument("min_door_width_cm", "")
            min_door_cm = 0
            if min_door_raw.strip():
                try:
                    min_door_cm = max(0, min(300, int(min_door_raw)))
                except ValueError:
                    raise ValidationError(
                        "Invalid min_door_width_cm filter parameter.",
                        {"min_door_width_cm": "Must be an integer between 0 and 300."},
                    )

            filters = {
                "q": self.get_query_argument("q", "").strip(),
                "category": self.get_query_argument("category", "all").strip(),
                "city": self.get_query_argument("city", "all").strip(),
                "freshness": self.get_query_argument("freshness", "all").strip(),
                "step_free": bool_arg("step_free"),
                "min_door_width_cm": min_door_cm,
                "accessible_restroom": bool_arg("accessible_restroom"),
                "elevator_operational": bool_arg("elevator_operational"),
                "quiet_space": bool_arg("quiet_space"),
                "hearing_loop": bool_arg("hearing_loop"),
                "braille_signage": bool_arg("braille_signage"),
                "include_archived": bool_arg("include_archived"),
            }
            try:
                limit = int(self.get_query_argument("limit", "50"))
                if limit < 1 or limit > 100:
                    raise ValueError()
            except ValueError as exc:
                raise ValidationError(
                    "Invalid pagination limit.",
                    {"limit": "limit must be an integer between 1 and 100."},
                ) from exc

            try:
                offset = int(self.get_query_argument("offset", "0"))
                if offset < 0 or offset > 10000:
                    raise ValueError()
            except ValueError as exc:
                raise ValidationError(
                    "Invalid pagination offset.",
                    {"offset": "offset must be an integer between 0 and 10000."},
                ) from exc

            result = self.db.list_venues(
                filters=filters,
                viewer_user=user,
                limit=limit,
                offset=offset,
            )

            self.tinybird_adapter.emit_event(
                event_type="venue_searched",
                workspace_slug=str(user.get("workspace_slug", "metro-civic-access"))
                if user
                else "metro-civic-access",
                category=filters["category"] or "all",
                freshness_state=filters["freshness"] or "all",
                confidence_bucket="search",
                metric_value=result["total"],
                user_opted_in=bool(user.get("telemetry_opt_in", True)) if user else True,
            )
            self.write_json(200, result)
        except Exception as exc:
            self.handle_domain_exception(exc)

    def post(self) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            authorize_action(user, "venue.create")
            assert user is not None

            idem_key = self.request.headers.get("X-Idempotency-Key", "").strip()
            composite_idem = f"{user['id']}:venue.create:{idem_key}" if idem_key else ""
            if composite_idem:
                cached = self.idempotency_store.get(composite_idem)
                if cached:
                    self.write_json(cached[0], cached[1])
                    return

            body = self.parse_json_body()
            validated = validate_venue_payload(body, is_update=False)
            venue = self.db.create_venue(
                validated_data=validated,
                actor_user=user,
                is_synthetic_sample=False,
            )
            self.tinybird_adapter.emit_event(
                event_type="venue_created",
                workspace_slug=str(user.get("workspace_slug", "metro-civic-access")),
                category=venue["category"],
                freshness_state=venue["freshness"]["state"],
                confidence_bucket=venue["freshness"]["confidence_band"],
                metric_value=1,
                user_opted_in=bool(user.get("telemetry_opt_in", True)),
            )
            resp_payload = {"venue": venue}
            if composite_idem:
                self.idempotency_store.put(composite_idem, 201, resp_payload)
            self.write_json(201, resp_payload)
        except Exception as exc:
            self.handle_domain_exception(exc)


class VenueDetailHandler(BaseAPIHandler):
    def get(self, venue_id: str) -> None:
        try:
            try:
                _, user = self.get_session_claims_and_user(require_csrf=False)
            except AuthenticationError:
                user = None

            venue = self.db.get_venue_by_id(venue_id, viewer_user=user, include_details=True)
            if not venue:
                raise LookupError("Venue profile not found or access restricted.")
            venue["google_maps_earth"] = (
                self.google_maps_adapter.build_venue_geospatial_profile(venue)
            )
            self.write_json(200, {"venue": venue})
        except Exception as exc:
            self.handle_domain_exception(exc)

    def put(self, venue_id: str) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            existing = self.db.get_venue_by_id(venue_id, viewer_user=user, include_details=False)
            if not existing:
                raise LookupError("Venue profile not found.")
            authorize_action(user, "venue.update", resource=existing)
            assert user is not None

            body = self.parse_json_body()
            validated = validate_venue_payload(body, is_update=True)
            updated = self.db.update_venue(venue_id, validated, actor_user=user)
            self.write_json(200, {"venue": updated})
        except Exception as exc:
            self.handle_domain_exception(exc)

    def delete(self, venue_id: str) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            existing = self.db.get_venue_by_id(venue_id, viewer_user=user, include_details=False)
            if not existing:
                raise LookupError("Venue profile not found.")
            body = self.parse_json_body() if self.request.body else {}
            confirm = (
                bool(body.get("confirm"))
                or self.get_query_argument("confirm", "false").lower() == "true"
                or self.request.headers.get("X-Confirm-Action", "").lower() == "true"
            )
            authorize_action(user, "venue.delete", resource=existing, confirm=confirm)
            assert user is not None

            self.db.delete_venue(venue_id, actor_user=user)
            self.write_json(200, {"deleted": True, "venue_id": venue_id})
        except Exception as exc:
            self.handle_domain_exception(exc)


class VenueArchiveHandler(BaseAPIHandler):
    def post(self, venue_id: str) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            existing = self.db.get_venue_by_id(venue_id, viewer_user=user, include_details=False)
            if not existing:
                raise LookupError("Venue profile not found.")
            body = self.parse_json_body()
            confirm = bool(body.get("confirm"))
            authorize_action(user, "venue.archive", resource=existing, confirm=confirm)
            assert user is not None

            archived = self.db.archive_venue(venue_id, actor_user=user)
            self.write_json(200, {"venue": archived})
        except Exception as exc:
            self.handle_domain_exception(exc)


class VenueObservationsHandler(BaseAPIHandler):
    def post(self, venue_id: str) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            existing = self.db.get_venue_by_id(venue_id, viewer_user=user, include_details=False)
            if not existing:
                raise LookupError("Target venue profile not found.")
            authorize_action(user, "observation.create", resource=existing)
            assert user is not None

            idem_key = self.request.headers.get("X-Idempotency-Key", "").strip()
            composite_idem = f"{user['id']}:obs:{venue_id}:{idem_key}" if idem_key else ""
            if composite_idem:
                cached = self.idempotency_store.get(composite_idem)
                if cached:
                    self.write_json(cached[0], cached[1])
                    return

            body = self.parse_json_body()
            validated = validate_observation_payload(body)
            observation = self.db.create_observation(
                venue_id=venue_id,
                validated_obs=validated,
                actor_user=user,
                is_synthetic_sample=False,
            )
            refreshed_venue = self.db.get_venue_by_id(
                venue_id, viewer_user=user, include_details=True
            )
            assert refreshed_venue is not None
            self.tinybird_adapter.emit_event(
                event_type="observation_submitted",
                workspace_slug=str(user.get("workspace_slug", "metro-civic-access")),
                category=refreshed_venue["category"],
                freshness_state=refreshed_venue["freshness"]["state"],
                confidence_bucket=validated["confidence_level"],
                metric_value=validated["confidence_score"],
                user_opted_in=bool(user.get("telemetry_opt_in", True)),
            )
            resp_payload = {"observation": observation, "venue": refreshed_venue}
            if composite_idem:
                self.idempotency_store.put(composite_idem, 201, resp_payload)
            self.write_json(201, resp_payload)
        except Exception as exc:
            self.handle_domain_exception(exc)


class VenuePhotosHandler(BaseAPIHandler):
    def post(self, venue_id: str) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            existing = self.db.get_venue_by_id(venue_id, viewer_user=user, include_details=False)
            if not existing:
                raise LookupError("Target venue profile not found.")
            authorize_action(user, "photo.upload", resource=existing)
            assert user is not None

            content_type = self.request.headers.get("Content-Type", "").lower()
            if "multipart/form-data" in content_type:
                files = self.request.files.get("file", [])
                file_bytes = files[0]["body"] if files else b""
                metadata = {
                    "category": self.get_body_argument("category", ""),
                    "alt_text": self.get_body_argument("alt_text", ""),
                    "caption": self.get_body_argument("caption", ""),
                    "no_identifiable_faces_confirmed": self.get_body_argument(
                        "no_identifiable_faces_confirmed", "false"
                    ),
                    "operator_or_public_area_consent": self.get_body_argument(
                        "operator_or_public_area_consent", "false"
                    ),
                }
            else:
                body = self.parse_json_body()
                b64_data = str(body.get("file_base64") or "")
                if "," in b64_data:
                    b64_data = b64_data.split(",", 1)[1]
                try:
                    file_bytes = base64.b64decode(b64_data, validate=True) if b64_data else b""
                except Exception as exc:
                    raise ValidationError(
                        "Invalid base64 image payload.", {"file": "Base64 decoding failed."}
                    ) from exc
                metadata = body

            validated_photo = validate_and_scrub_photo_upload(
                metadata=metadata,
                file_bytes=file_bytes,
                max_bytes=self.app_config.max_upload_bytes,
            )
            photo = self.db.create_photo_evidence(
                venue_id=venue_id,
                validated_photo=validated_photo,
                actor_user=user,
                is_synthetic_sample=False,
            )
            refreshed_venue = self.db.get_venue_by_id(
                venue_id, viewer_user=user, include_details=True
            )
            self.write_json(201, {"photo": photo, "venue": refreshed_venue})
        except Exception as exc:
            self.handle_domain_exception(exc)


class PhotoFileHandler(BaseAPIHandler):
    def get(self, photo_id: str) -> None:
        try:
            try:
                _, user = self.get_session_claims_and_user(require_csrf=False)
            except AuthenticationError:
                user = None

            found = self.db.get_photo_record_and_bytes(photo_id)
            if not found:
                raise LookupError("Photo evidence file not found.")
            record, raw_bytes = found

            if record["consent_status"] != "approved_public":
                authorize_action(user, "photo.read", resource=record)

            self.set_status(200)
            self.set_header("Content-Type", str(record["mime_type"]))
            self.set_header("X-Content-Type-Options", "nosniff")
            self.set_header(
                "Content-Disposition", f'inline; filename="{photo_id}.img"'
            )
            self.write(raw_bytes)
        except Exception as exc:
            self.handle_domain_exception(exc)


class PhotoReviewHandler(BaseAPIHandler):
    def post(self, photo_id: str) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            body = self.parse_json_body()
            validated = validate_photo_review_payload(body)
            authorize_action(user, "photo.review", confirm=validated["confirm"])
            assert user is not None

            reviewed = self.db.review_photo_consent(
                photo_id=photo_id,
                consent_status=validated["consent_status"],
                review_notes=validated["review_notes"],
                moderator_user=user,
            )
            self.write_json(200, {"photo": reviewed})
        except Exception as exc:
            self.handle_domain_exception(exc)


class VenueBriefingHandler(BaseAPIHandler):
    def post(self, venue_id: str) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            authorize_action(user, "ai.briefing")
            assert user is not None

            venue = self.db.get_venue_by_id(venue_id, viewer_user=user, include_details=True)
            if not venue:
                raise LookupError("Venue profile not found.")
            body = self.parse_json_body() if self.request.body else {}
            explicit_consent = bool(body.get("explicit_consent")) or bool(
                user.get("ai_consent_granted")
            )
            briefing = self.ai_adapter.generate_venue_briefing(
                venue=venue,
                user_consent_granted=explicit_consent,
            )
            self.write_json(200, {"briefing": briefing})
        except Exception as exc:
            self.handle_domain_exception(exc)


class VenueGeospatialHandler(BaseAPIHandler):
    def get(self, venue_id: str) -> None:
        try:
            try:
                _, user = self.get_session_claims_and_user(require_csrf=False)
            except AuthenticationError:
                user = None

            raw_params = {
                "origin_lat": self.get_query_argument("origin_lat", ""),
                "origin_lng": self.get_query_argument("origin_lng", ""),
                "origin_label": self.get_query_argument("origin_label", ""),
                "travel_mode": self.get_query_argument("travel_mode", "wheelchair_manual"),
            }
            profile = self.domain_modules.google_maps_earth_geospatial.get_venue_geospatial_profile(
                venue_id=venue_id,
                raw_params=raw_params,
                viewer_user=user,
            )
            self.write_json(200, {"geospatial": profile})
        except Exception as exc:
            self.handle_domain_exception(exc)

    def post(self, venue_id: str) -> None:
        try:
            try:
                _, user = self.get_session_claims_and_user(require_csrf=False)
            except AuthenticationError:
                user = None

            body = self.parse_json_body() if self.request.body else {}
            profile = self.domain_modules.google_maps_earth_geospatial.get_venue_geospatial_profile(
                venue_id=venue_id,
                raw_params=body,
                viewer_user=user,
            )
            self.write_json(200, {"geospatial": profile})
        except Exception as exc:
            self.handle_domain_exception(exc)


class VenueEarthKMLHandler(BaseAPIHandler):
    def get(self, venue_id: str) -> None:
        try:
            try:
                _, user = self.get_session_claims_and_user(require_csrf=False)
            except AuthenticationError:
                user = None

            filename, kml_xml = (
                self.domain_modules.google_maps_earth_geospatial.export_venue_earth_kml(
                    venue_id=venue_id,
                    viewer_user=user,
                )
            )
            self.set_status(200)
            self.set_header(
                "Content-Type", "application/vnd.google-earth.kml+xml; charset=utf-8"
            )
            self.set_header("X-Content-Type-Options", "nosniff")
            self.set_header(
                "Content-Disposition", f'attachment; filename="{filename}"'
            )
            self.write(kml_xml)
        except Exception as exc:
            self.handle_domain_exception(exc)


class WorkspaceEarthKMLHandler(BaseAPIHandler):
    def get(self) -> None:
        try:
            try:
                _, user = self.get_session_claims_and_user(require_csrf=False)
            except AuthenticationError:
                user = None

            filename, kml_xml = (
                self.domain_modules.google_maps_earth_geospatial.export_workspace_earth_kml(
                    filters={},
                    viewer_user=user,
                )
            )
            self.set_status(200)
            self.set_header(
                "Content-Type", "application/vnd.google-earth.kml+xml; charset=utf-8"
            )
            self.set_header("X-Content-Type-Options", "nosniff")
            self.set_header(
                "Content-Disposition", f'attachment; filename="{filename}"'
            )
            self.write(kml_xml)
        except Exception as exc:
            self.handle_domain_exception(exc)


class ModerationQueueHandler(BaseAPIHandler):
    def get(self) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=False)
            authorize_action(user, "moderation.read_queue")
            assert user is not None
            queue = self.db.list_moderation_queue(str(user["workspace_id"]))
            self.write_json(200, queue)
        except Exception as exc:
            self.handle_domain_exception(exc)


class ModerationReportsHandler(BaseAPIHandler):
    def post(self) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            authorize_action(user, "moderation.report")
            assert user is not None

            body = self.parse_json_body()
            validated = validate_moderation_report_payload(body)
            report = self.db.create_moderation_report(validated, reporter_user=user)
            self.write_json(201, {"report": report})
        except Exception as exc:
            self.handle_domain_exception(exc)


class ModerationResolveHandler(BaseAPIHandler):
    def post(self, report_id: str) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            body = self.parse_json_body()
            validated = validate_moderation_resolution_payload(body)
            authorize_action(user, "moderation.resolve", confirm=validated["confirm"])
            assert user is not None

            resolved = self.db.resolve_moderation_report(
                report_id=report_id,
                status=validated["status"],
                resolution_notes=validated["resolution_notes"],
                moderator_user=user,
            )
            self.tinybird_adapter.emit_event(
                event_type="moderation_resolved",
                workspace_slug=str(user.get("workspace_slug", "metro-civic-access")),
                category="moderation",
                freshness_state=validated["status"],
                confidence_bucket="moderator_verified",
                metric_value=1,
                user_opted_in=bool(user.get("telemetry_opt_in", True)),
            )
            self.write_json(200, {"report": resolved})
        except Exception as exc:
            self.handle_domain_exception(exc)


class InsightsHandler(BaseAPIHandler):
    def get(self) -> None:
        try:
            try:
                _, user = self.get_session_claims_and_user(require_csrf=False)
            except AuthenticationError:
                user = None
            ws_id = str(user["workspace_id"]) if user else None
            insights = self.db.get_workspace_insights(workspace_id=ws_id)
            insights["tinybird_telemetry"] = {
                "status": self.tinybird_adapter.get_status(),
                "recent_minimized_events": self.tinybird_adapter.get_recent_events(limit=10),
            }
            self.write_json(200, insights)
        except Exception as exc:
            self.handle_domain_exception(exc)


class SavedViewsHandler(BaseAPIHandler):
    def get(self) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=False)
            authorize_action(user, "saved_view.manage")
            assert user is not None
            views = self.db.list_saved_views(str(user["id"]))
            self.write_json(200, {"saved_views": views})
        except Exception as exc:
            self.handle_domain_exception(exc)

    def post(self) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            authorize_action(user, "saved_view.manage")
            assert user is not None
            body = self.parse_json_body()
            validated = validate_saved_view_payload(body)
            created = self.db.create_saved_view(
                user=user,
                name=validated["name"],
                filters=validated["filters"],
            )
            self.write_json(201, {"saved_view": created})
        except Exception as exc:
            self.handle_domain_exception(exc)


class SavedViewDetailHandler(BaseAPIHandler):
    def delete(self, view_id: str) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            existing = self.db.get_saved_view_by_id(view_id)
            if not existing:
                raise LookupError("Saved view not found.")
            authorize_action(user, "saved_view.manage", resource=existing)
            self.db.delete_saved_view(view_id)
            self.write_json(200, {"deleted": True, "id": view_id})
        except Exception as exc:
            self.handle_domain_exception(exc)


class SettingsHandler(BaseAPIHandler):
    def get(self) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=False)
            authorize_action(user, "settings.manage")
            assert user is not None
            self.write_json(200, {"settings": self.db.get_user_settings(str(user["id"]))})
        except Exception as exc:
            self.handle_domain_exception(exc)

    def put(self) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            authorize_action(user, "settings.manage")
            assert user is not None
            body = self.parse_json_body()
            validated = validate_settings_payload(body)
            updated = self.db.update_user_settings(
                user_id=str(user["id"]),
                workspace_id=str(user["workspace_id"]),
                settings=validated,
            )
            self.write_json(200, {"settings": updated})
        except Exception as exc:
            self.handle_domain_exception(exc)


class WorkspaceExportHandler(BaseAPIHandler):
    def post(self) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            body = self.parse_json_body() if self.request.body else {}
            confirm = bool(body.get("confirm"))
            authorize_action(user, "workspace.export", confirm=confirm)
            assert user is not None
            bundle = self.db.export_workspace_bundle(actor_user=user)
            self.write_json(200, bundle)
        except Exception as exc:
            self.handle_domain_exception(exc)


class VenueImportHandler(BaseAPIHandler):
    def post(self) -> None:
        try:
            _, user = self.get_session_claims_and_user(require_csrf=True)
            authorize_action(user, "venue.create")
            assert user is not None

            body = self.parse_json_body()
            validated = validate_venue_import_payload(body)
            venue = self.db.import_venue(validated_data=validated, actor_user=user)
            self.tinybird_adapter.emit_event(
                event_type="venue_created",
                workspace_slug=str(user.get("workspace_slug", "metro-civic-access")),
                category=venue["category"],
                freshness_state=venue["freshness"]["state"],
                confidence_bucket="imported_confirmed",
                metric_value=1,
                user_opted_in=bool(user.get("telemetry_opt_in", True)),
            )
            self.write_json(201, {"venue": venue, "imported": True})
        except Exception as exc:
            self.handle_domain_exception(exc)


class AccountDeleteHandler(BaseAPIHandler):
    def post(self) -> None:
        try:
            claims, user = self.get_session_claims_and_user(require_csrf=True)
            body = self.parse_json_body() if self.request.body else {}
            validated = validate_account_deletion_payload(body)
            authorize_action(user, "account.delete", confirm=validated["confirm"])
            assert user is not None

            result = self.db.delete_user_account(actor_user=user)
            if claims and claims.get("jti"):
                self.revoked_tokens.revoke(
                    str(claims["jti"]), float(claims.get("exp") or 0)
                )
            self.clear_cookie("atlas_session", path="/")
            self.write_json(200, result)
        except Exception as exc:
            self.handle_domain_exception(exc)


class IndexHTMLHandler(BaseAPIHandler):
    def get(self) -> None:
        index_path = STATIC_ROOT / "index.html"
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.write(index_path.read_text(encoding="utf-8"))


class SecureStaticFileHandler(tornado.web.StaticFileHandler):
    def set_default_headers(self) -> None:
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("X-Frame-Options", "DENY")
        self.set_header("Referrer-Policy", "strict-origin-when-cross-origin")


def create_app(config: AtlasConfig | None = None) -> tornado.web.Application:
    """Create and configure the AccessAble Atlas Tornado web application."""
    cfg = config or load_config()
    db = AtlasDatabase(db_path=cfg.db_path, private_storage_dir=cfg.private_storage_dir)
    if cfg.seed_synthetic_data:
        seed_if_empty(db)

    rate_limiter = SlidingWindowRateLimiter(window_seconds=60)
    idempotency_store = IdempotencyStore(ttl_seconds=600)
    revoked_tokens = RevokedTokenStore()
    supabase_adapter = SupabaseAdapter(cfg)
    tinybird_adapter = TinybirdAdapter(cfg)
    ai_adapter = AISummaryAdapter(cfg)
    google_maps_adapter = GoogleMapsEarthAdapter(cfg)
    domain_modules = DomainModulesContainer(db, google_maps_adapter=google_maps_adapter)
    feature_flags = FeatureFlagRegistry(cfg)
    structured_logger = StructuredLogger()
    background_jobs = BackgroundJobRunner(
        db=db,
        revoked_tokens=revoked_tokens,
        idempotency_store=idempotency_store,
        tinybird_adapter=tinybird_adapter,
        logger=structured_logger,
    )
    background_jobs.run_all_maintenance_jobs()

    routes: list[Any] = [
        (r"/api/health", HealthHandler),
        (r"/api/meta/taxonomies", TaxonomiesHandler),
        (r"/api/auth/login", AuthLoginHandler),
        (r"/api/auth/register", AuthRegisterHandler),
        (r"/api/auth/logout", AuthLogoutHandler),
        (r"/api/auth/me", AuthMeHandler),
        (r"/api/venues", VenuesCollectionHandler),
        (r"/api/venues/import", VenueImportHandler),
        (r"/api/venues/([A-Za-z0-9-]+)", VenueDetailHandler),
        (r"/api/venues/([A-Za-z0-9-]+)/archive", VenueArchiveHandler),
        (r"/api/venues/([A-Za-z0-9-]+)/observations", VenueObservationsHandler),
        (r"/api/venues/([A-Za-z0-9-]+)/photos", VenuePhotosHandler),
        (r"/api/venues/([A-Za-z0-9-]+)/briefing", VenueBriefingHandler),
        (r"/api/venues/([A-Za-z0-9-]+)/geospatial", VenueGeospatialHandler),
        (r"/api/venues/([A-Za-z0-9-]+)/earth\.kml", VenueEarthKMLHandler),
        (r"/api/photos/([A-Za-z0-9-]+)/file", PhotoFileHandler),
        (r"/api/photos/([A-Za-z0-9-]+)/review", PhotoReviewHandler),
        (r"/api/moderation/queue", ModerationQueueHandler),
        (r"/api/moderation/reports", ModerationReportsHandler),
        (r"/api/moderation/reports/([A-Za-z0-9-]+)/resolve", ModerationResolveHandler),
        (r"/api/insights", InsightsHandler),
        (r"/api/saved-views", SavedViewsHandler),
        (r"/api/saved-views/([A-Za-z0-9-]+)", SavedViewDetailHandler),
        (r"/api/settings", SettingsHandler),
        (r"/api/export/earth\.kml", WorkspaceEarthKMLHandler),
        (r"/api/export", WorkspaceExportHandler),
        (r"/api/account/delete", AccountDeleteHandler),
        (r"/static/(.*)", SecureStaticFileHandler, {"path": str(STATIC_ROOT)}),
        (r"/", IndexHTMLHandler),
    ]

    return tornado.web.Application(
        routes,
        atlas_config=cfg,
        atlas_db=db,
        rate_limiter=rate_limiter,
        idempotency_store=idempotency_store,
        revoked_tokens=revoked_tokens,
        supabase_adapter=supabase_adapter,
        tinybird_adapter=tinybird_adapter,
        ai_adapter=ai_adapter,
        google_maps_adapter=google_maps_adapter,
        domain_modules=domain_modules,
        feature_flags=feature_flags,
        structured_logger=structured_logger,
        background_jobs=background_jobs,
    )


def run_server() -> None:
    """Start the AccessAble Atlas HTTP server."""
    cfg = load_config()
    app = create_app(cfg)
    server = tornado.httpserver.HTTPServer(app, max_buffer_size=cfg.max_upload_bytes + 524288)
    server.listen(cfg.port, address=cfg.host)
    print(
        f"AccessAble Atlas (Sage Circuit) listening on http://{cfg.host}:{cfg.port} "
        f"[env={cfg.env}, db={cfg.db_path}]"
    )
    tornado.ioloop.IOLoop.current().start()
