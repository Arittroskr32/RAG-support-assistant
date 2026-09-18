"""Browser accounts: email + password registration, cookie sessions, role assignment.

- Anyone can register (unless ALLOW_REGISTRATION=false) and starts with the RBAC default
  role ("public").
- config/role_assignments.json gives specific emails another role:
      {"alice@example.com": "employee", "bob@partner.com": {"role": "partner", "tenant_id": "acme"}}
  It's re-read whenever the file changes, and the role is resolved on every request, so an
  edit applies immediately, also to users who are already signed in. Entries with an
  unknown role are ignored (logged), so a typo can only ever *lower* someone's access.
- Passwords are stored only as scrypt hashes in config/users.json (gitignored).
- The session cookie is an HMAC-signed "email|expiry" token. The secret comes from
  SESSION_SECRET or config/session_secret (created on first use). The cookie is HttpOnly
  (page scripts can't read it) and SameSite=Strict (other sites can't send it).
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone

from api.auth import Identity
from config.settings import API_SETTINGS
from knowledge_bases.kb3_rbac import known_roles, load_policy

logger = logging.getLogger(__name__)

COOKIE_NAME = "rag_session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD, MAX_PASSWORD = 8, 128
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
# Failed sign-ins per (email, ip) within the window before further attempts get 429.
MAX_FAILED_LOGINS, FAILED_LOGIN_WINDOW_S = 5, 15 * 60

_lock = threading.Lock()
_assignments_cache: dict = {"mtime": None, "by_email": {}}
_failed: dict[tuple[str, str], list[float]] = {}


class AccountError(Exception):
    """Carries an HTTP status and a message that is safe to show the user."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise AccountError(422, "Enter a valid email address.")
    return email


# ------------------------------------------------------------------ passwords

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest)


# A real hash to check against when the email doesn't exist, so the response time doesn't
# reveal which emails are registered.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


# ------------------------------------------------------------------ user store

def _load_users(path=None) -> dict:
    path = path or API_SETTINGS.users_file
    if not path.exists():
        return {}
    return (json.loads(path.read_text() or "{}") or {}).get("users", {})


def _save_users(users: dict, path=None) -> None:
    path = path or API_SETTINGS.users_file
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"users": users}, indent=2))
    os.replace(tmp, path)   # atomic: a crash never leaves a half-written file


def register(email: str, password: str) -> str:
    if not API_SETTINGS.allow_registration:
        raise AccountError(403, "Registration is disabled.")
    email = normalize_email(email)
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise AccountError(422, f"Use a password of {MIN_PASSWORD}–{MAX_PASSWORD} characters.")
    with _lock:
        users = _load_users()
        if email in users:
            raise AccountError(409, "An account with this email already exists. Sign in instead.")
        users[email] = {"password": hash_password(password),
                        "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _save_users(users)
    return email


def login(email: str, password: str, ip: str) -> str:
    wrong = AccountError(401, "Wrong email or password.")
    try:
        email = normalize_email(email)
    except AccountError:
        raise wrong from None
    key, now = (email, ip), time.time()
    with _lock:
        recent = [t for t in _failed.get(key, []) if now - t < FAILED_LOGIN_WINDOW_S]
        _failed[key] = recent
        if len(recent) >= MAX_FAILED_LOGINS:
            raise AccountError(429, "Too many failed sign-ins. Try again in a few minutes.")
        user = _load_users().get(email)
    if not verify_password(password, user["password"] if user else _DUMMY_HASH) or not user:
        with _lock:
            _failed.setdefault(key, []).append(now)
        raise wrong
    with _lock:
        _failed.pop(key, None)
    return email


# ------------------------------------------------------------------ role assignments

def load_role_assignments(path=None) -> dict[str, tuple[str, str]]:
    """email -> (role, tenant_id). Reloads when the file changes; missing file = {}."""
    path = path or API_SETTINGS.role_assignments_file
    if not path.exists():
        return {}
    mtime = path.stat().st_mtime
    with _lock:
        if _assignments_cache["mtime"] != mtime:
            try:
                raw = json.loads(path.read_text() or "{}")
            except json.JSONDecodeError as e:
                logger.error("%s is not valid JSON (%s): every account falls back to the default role", path, e)
                raw = {}
            roles, by_email = set(known_roles()), {}
            for email, value in raw.items():
                if email.startswith("_"):          # "_comment" keys
                    continue
                role, tenant = (value, "default") if isinstance(value, str) else \
                    ((value or {}).get("role"), (value or {}).get("tenant_id", "default"))
                if role not in roles:
                    logger.error("%s: %r has unknown role %r (known: %s) — ignored",
                                 path, email, role, ", ".join(sorted(roles)))
                    continue
                by_email[email.strip().lower()] = (role, tenant)
            _assignments_cache.update(mtime=mtime, by_email=by_email)
        return _assignments_cache["by_email"]


def identity_for(email: str) -> Identity:
    role, tenant = load_role_assignments().get(email, (load_policy()["default_role"], "default"))
    return Identity(user_id=email, role=role, tenant_id=tenant, authenticated=True, via="session")


# ------------------------------------------------------------------ session cookie

def _secret() -> bytes:
    env = os.getenv("SESSION_SECRET")
    if env:
        return env.encode()
    path = API_SETTINGS.session_secret_file
    with _lock:
        if not path.exists():
            path.write_text(secrets.token_hex(32))
            path.chmod(0o600)
        return path.read_text().strip().encode()


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def make_session_token(email: str) -> str:
    payload = f"{base64.urlsafe_b64encode(email.encode()).decode()}|{int(time.time()) + API_SETTINGS.session_ttl_s}"
    return f"{payload}|{_sign(payload)}"


def email_from_session_token(token: str | None) -> str | None:
    """The signed-in email, or None for a missing, tampered, expired or deleted account."""
    try:
        b64, exp, sig = (token or "").split("|")
        if not hmac.compare_digest(sig, _sign(f"{b64}|{exp}")) or int(exp) < time.time():
            return None
        email = base64.urlsafe_b64decode(b64.encode()).decode()
    except (ValueError, UnicodeDecodeError):
        return None
    return email if email in _load_users() else None
