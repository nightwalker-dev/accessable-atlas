"""Authentication, session JWT lifecycle, CSRF protection, and deny-by-default authorization."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from typing import Any

import bcrypt
import jwt


class AuthenticationError(Exception):
    """Raised when credentials or session tokens are missing, expired, or invalid (HTTP 401)."""


class AuthorizationError(Exception):
    """Raised when an authenticated user lacks permission or workspace/ownership scope (HTTP 403)."""


class RevokedTokenStore:
    """Thread-safe JTI revocation store to invalidate JWTs immediately upon sign-out."""

    def __init__(self) -> None:
        self._revoked: dict[str, float] = {}
        self._lock = threading.Lock()

    def revoke(self, jti: str, expires_at: float) -> None:
        if not jti:
            return
        now = time.time()
        with self._lock:
            expired = [k for k, exp in self._revoked.items() if exp <= now]
            for k in expired:
                del self._revoked[k]
            self._revoked[jti] = max(now + 60, float(expires_at))

    def is_revoked(self, jti: str) -> bool:
        if not jti:
            return True
        now = time.time()
        with self._lock:
            exp = self._revoked.get(jti)
            if exp is None:
                return False
            if exp <= now:
                del self._revoked[jti]
                return False
            return True


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt(rounds=10)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time verification of a plaintext password against a bcrypt hash."""
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def generate_csrf_token(session_jti: str, secret: str) -> str:
    """Derive a deterministic HMAC-SHA256 CSRF token bound to the session JTI."""
    return hmac.new(
        secret.encode("utf-8"),
        msg=f"csrf:{session_jti}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def verify_csrf_token(expected_csrf: str, provided_csrf: str | None) -> bool:
    """Verify a provided CSRF token in constant time."""
    if not expected_csrf or not provided_csrf:
        return False
    return hmac.compare_digest(expected_csrf, str(provided_csrf).strip())


def create_session_token(
    user: dict[str, Any],
    secret: str,
    ttl_seconds: int = 28800,
) -> dict[str, Any]:
    """Create a signed JWT session token and paired CSRF token."""
    now = int(time.time())
    jti = secrets.token_hex(16)
    csrf_token = generate_csrf_token(jti, secret)
    payload = {
        "iss": "accessable-atlas",
        "sub": str(user["id"]),
        "email": str(user["email"]),
        "display_name": str(user["display_name"]),
        "role": str(user["role"]),
        "workspace_id": str(user["workspace_id"]),
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": jti,
        "csrf": csrf_token,
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    return {
        "token": token,
        "csrf_token": csrf_token,
        "expires_at": now + ttl_seconds,
        "jti": jti,
    }


def decode_session_token(token: str, secret: str) -> dict[str, Any]:
    """Decode and validate a signed HS256 JWT session token."""
    if not token:
        raise AuthenticationError("Authentication token is required.")
    try:
        decoded = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer="accessable-atlas",
            options={
                "require": ["sub", "role", "workspace_id", "iat", "exp", "jti", "csrf"]
            },
        )
        return dict(decoded)
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Session has expired. Please sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid authentication session token.") from exc


# ============================================================================
# Deny-by-Default Authorization Matrix
# ============================================================================

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset(
        {
            "venue.read",
            "observation.read",
            "photo.read_approved",
            "saved_view.manage_own",
            "settings.manage_own",
            "workspace.export_own",
            "account.delete_own",
            "ai.briefing",
        }
    ),
    "contributor": frozenset(
        {
            "venue.read",
            "venue.create",
            "venue.update_own",
            "venue.archive_own",
            "venue.delete_own",
            "observation.read",
            "observation.create",
            "photo.read_approved",
            "photo.read_own",
            "photo.upload",
            "moderation.report",
            "saved_view.manage_own",
            "settings.manage_own",
            "workspace.export_own",
            "account.delete_own",
            "ai.briefing",
        }
    ),
    "operator": frozenset(
        {
            "venue.read",
            "venue.create",
            "venue.update_own",
            "venue.update_workspace",
            "venue.archive_own",
            "venue.delete_own",
            "observation.read",
            "observation.create",
            "photo.read_approved",
            "photo.read_own",
            "photo.upload",
            "moderation.report",
            "saved_view.manage_own",
            "settings.manage_own",
            "workspace.export_own",
            "account.delete_own",
            "ai.briefing",
        }
    ),
    "moderator": frozenset(
        {
            "venue.read",
            "venue.read_archived",
            "venue.create",
            "venue.update_own",
            "venue.update_workspace",
            "venue.archive_workspace",
            "venue.delete_own",
            "observation.read",
            "observation.create",
            "photo.read_approved",
            "photo.read_own",
            "photo.read_pending",
            "photo.upload",
            "photo.review",
            "moderation.report",
            "moderation.read_queue",
            "moderation.resolve",
            "audit.read_workspace",
            "saved_view.manage_own",
            "settings.manage_own",
            "workspace.export_own",
            "account.delete_own",
            "ai.briefing",
        }
    ),
    "admin": frozenset(
        {
            "venue.read",
            "venue.read_archived",
            "venue.create",
            "venue.update_own",
            "venue.update_workspace",
            "venue.archive_workspace",
            "venue.delete_own",
            "venue.delete_workspace",
            "observation.read",
            "observation.create",
            "photo.read_approved",
            "photo.read_own",
            "photo.read_pending",
            "photo.upload",
            "photo.review",
            "moderation.report",
            "moderation.read_queue",
            "moderation.resolve",
            "audit.read_workspace",
            "saved_view.manage_own",
            "settings.manage_own",
            "workspace.export_own",
            "account.delete_own",
            "ai.briefing",
        }
    ),
}

CONSEQUENTIAL_ACTIONS = frozenset(
    {
        "venue.delete",
        "venue.archive",
        "photo.review",
        "moderation.resolve",
        "workspace.export",
        "account.delete",
    }
)


def authorize_action(
    user: dict[str, Any] | None,
    action: str,
    resource: dict[str, Any] | None = None,
    confirm: bool = False,
) -> None:
    """
    Enforce server-side deny-by-default authorization, workspace tenant isolation,
    resource ownership, and explicit confirmation for destructive/consequential actions.
    """
    if not user:
        raise AuthenticationError("Sign in is required to perform this action.")

    role = str(user.get("role") or "")
    perms = ROLE_PERMISSIONS.get(role, frozenset())
    user_id = str(user.get("id") or "")
    user_workspace = str(user.get("workspace_id") or "")

    if action in CONSEQUENTIAL_ACTIONS and not confirm:
        raise AuthorizationError(
            f"Action '{action}' requires explicit confirmation (confirm=true)."
        )

    # Workspace boundary check whenever a resource carries workspace_id
    if resource and resource.get("workspace_id"):
        res_workspace = str(resource["workspace_id"])
        if res_workspace != user_workspace:
            raise AuthorizationError(
                "Cross-workspace access denied: resource belongs to another workspace."
            )

    if action == "venue.create":
        if "venue.create" not in perms:
            raise AuthorizationError("Your role does not permit creating venue profiles.")
        return

    if action == "venue.update":
        if not resource:
            raise AuthorizationError("Target venue is required.")
        is_owner = str(resource.get("created_by")) == user_id
        if is_owner and "venue.update_own" in perms:
            return
        if "venue.update_workspace" in perms:
            return
        raise AuthorizationError("You may only edit venues you created or manage as an operator/moderator.")

    if action == "venue.archive":
        if not resource:
            raise AuthorizationError("Target venue is required.")
        is_owner = str(resource.get("created_by")) == user_id
        if is_owner and "venue.archive_own" in perms:
            return
        if "venue.archive_workspace" in perms:
            return
        raise AuthorizationError("You do not have permission to archive this venue.")

    if action == "venue.delete":
        if not resource:
            raise AuthorizationError("Target venue is required.")
        is_owner = str(resource.get("created_by")) == user_id
        if is_owner and "venue.delete_own" in perms:
            return
        if "venue.delete_workspace" in perms:
            return
        raise AuthorizationError("You may only delete venues you own or administer.")

    if action == "observation.create":
        if "observation.create" not in perms:
            raise AuthorizationError("Your role does not permit logging observations.")
        return

    if action == "photo.upload":
        if "photo.upload" not in perms:
            raise AuthorizationError("Your role does not permit uploading photo evidence.")
        return

    if action == "photo.read":
        if not resource:
            raise AuthorizationError("Target photo record is required.")
        status = str(resource.get("consent_status") or "pending_review")
        if status == "approved_public":
            return
        is_uploader = str(resource.get("uploaded_by")) == user_id
        if is_uploader and "photo.read_own" in perms:
            return
        if "photo.read_pending" in perms:
            return
        raise AuthorizationError("Unapproved or rejected photo evidence is restricted to the uploader and moderators.")

    if action == "photo.review":
        if "photo.review" not in perms:
            raise AuthorizationError("Only moderators or administrators can approve or reject photo consent.")
        return

    if action == "moderation.report":
        if "moderation.report" not in perms:
            raise AuthorizationError("Sign in as a contributor, operator, or moderator to submit a flag.")
        return

    if action == "moderation.read_queue":
        if "moderation.read_queue" not in perms:
            raise AuthorizationError("Only moderators and administrators can view the moderation queue.")
        return

    if action == "moderation.resolve":
        if "moderation.resolve" not in perms:
            raise AuthorizationError("Only moderators and administrators can resolve moderation flags.")
        return

    if action == "audit.read_workspace":
        if "audit.read_workspace" not in perms:
            raise AuthorizationError("Only moderators and administrators can inspect full workspace audit logs.")
        return

    if action == "saved_view.manage":
        if "saved_view.manage_own" not in perms:
            raise AuthorizationError("Permission denied for saved views.")
        if resource and str(resource.get("user_id")) != user_id:
            raise AuthorizationError("You can only access or delete your own saved views.")
        return

    if action in ("settings.manage", "workspace.export", "account.delete"):
        if resource and str(resource.get("user_id", user_id)) != user_id:
            raise AuthorizationError("You may only manage, export, or delete your own account data.")
        return

    if action == "ai.briefing":
        if "ai.briefing" not in perms:
            raise AuthorizationError("Sign in to request an accessibility briefing.")
        return

    raise AuthorizationError(f"Action '{action}' is denied by default policy.")
