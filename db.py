"""
db.py — ADEPR Paruwasi ya Ruhango MIS
JSON-file persistence layer with TTL cache (mirrors the Google Sheets
strategy used in the reference system_db.py, but works offline).

Each entity lives in its own JSON file under data/. Reads are cached
for CACHE_TTL seconds; writes invalidate immediately. The cache keeps
stale data on read failure so the app degrades gracefully.

Entities:
  users.json            — System_Users (PARISH_PASTOR / CHURCH_PASTOR / MINISTRY_LEADER)
  churches.json         — System_Churches (amatorero)
  members.json          — System_Members (abakristo by category)
  ministries.json       — System_Ministries (ministeur)
  member_ministries.json— System_MemberMinistries (assignments)
  offerings.json        — System_Offerings (weekly offering records)
  offerings_items.json  — System_OfferingItems (line items per offering)
  announcements.json    — System_Announcements (SMS broadcasts)
  signatures.json       — {user_id: {png_base64, name, signed_at}}
  parish_profile.json   — parish info (single object, not a list)
  sessions.json         — {token: {user_id, expires_at}}
  translations.json     — UI strings (single object)
"""

import os
import json
import uuid
import threading
import hashlib
import hmac
import secrets
import base64
from datetime import datetime, timedelta

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

REPORTS_DIR = os.path.join(BASE_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

# ------------------------------------------------------------------
# Cache (60s TTL, thread-safe, stale-but-keep on failure)
# ------------------------------------------------------------------
_CACHE_TTL = 60
_cache = {}            # {file_key: (timestamp, records)}
_cache_lock = threading.Lock()


def _path(name):
    return os.path.join(DATA_DIR, name + ".json")


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _new_id(prefix=""):
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def _to_float(v, default=0.0):
    if v is None or v == "":
        return default
    try:
        return float(str(v).replace(",", "").replace("RWF", "").strip())
    except (ValueError, TypeError):
        return default


def _to_int(v, default=0):
    if v is None or v == "":
        return default
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (ValueError, TypeError):
        return default


def _to_bool(v, default=True):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().upper() in ("TRUE", "1", "YES", "ACTIVE")


# ------------------------------------------------------------------
# Credential hashing (V1.11)
# Passwords and security answers are never stored in plaintext. We use
# PBKDF2-HMAC-SHA256 from the stdlib (no extra dependency) with a
# per-record random salt. The stored string is self-describing:
#   "pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>"
# so the iteration count can be raised later without a migration.
# verify_password() also accepts legacy plaintext strings (pre-V1.11
# users.json) so existing deployments keep working until each record
# is re-hashed by _migrate_legacy_credentials() on first boot.
# ------------------------------------------------------------------
HASH_ALGO = "pbkdf2_sha256"
HASH_ITERATIONS = 200_000
HASH_SALT_BYTES = 16

# Field names that hold secret material — never expose these via the API.
SECRET_FIELDS = (
    "password", "password_hash", "password_algo",
    "security_answer", "security_answer_hash",
)


def hash_password(plain):
    """Return a self-describing PBKDF2 hash of a plaintext password."""
    if not isinstance(plain, str) or plain == "":
        return ""
    salt = secrets.token_bytes(HASH_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"),
                             salt, HASH_ITERATIONS)
    return "{}${}${}${}".format(
        HASH_ALGO, HASH_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"))


def verify_password(plain, stored):
    """Verify a plaintext password against the stored hash.

    Returns True for a match. Accepts the new pbkdf2_sha256 format and
    legacy plaintext (compared in constant time) for migration safety.
    """
    if not isinstance(plain, str) or plain == "" or not stored:
        return False
    stored = str(stored)
    if stored.startswith(HASH_ALGO + "$"):
        try:
            _, iters_s, salt_b64, hash_b64 = stored.split("$", 3)
            iters = int(iters_s)
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(hash_b64)
            dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"),
                                     salt, iters)
            return hmac.compare_digest(dk, expected)
        except (ValueError, TypeError):
            return False
    # Legacy plaintext (pre-V1.11) — constant-time compare.
    return hmac.compare_digest(plain, stored)


# Security answers use the same scheme but a separate helper so the
# intent is explicit at the call site.
def hash_secret(plain):
    if not isinstance(plain, str) or plain == "":
        return ""
    plain = plain.strip().lower()
    return hash_password(plain)


def verify_secret(plain, stored):
    if not isinstance(plain, str) or plain == "":
        return False
    return verify_password(plain.strip().lower(), stored)


# ------------------------------------------------------------------
# Low-level read / write
# ------------------------------------------------------------------
def _read_tab(name, use_cache=True):
    """Return list[dict] for the given entity. Cache-aware."""
    with _cache_lock:
        if use_cache and name in _cache:
            ts, records = _cache[name]
            if (datetime.now() - ts).total_seconds() < _CACHE_TTL:
                return records
    path = _path(name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
        if not isinstance(records, list):
            records = []
    except FileNotFoundError:
        records = []
    except (json.JSONDecodeError, OSError):
        # Stale-but-keep: return cached entry if available
        with _cache_lock:
            if name in _cache:
                return _cache[name][1]
        records = []
    with _cache_lock:
        _cache[name] = (datetime.now(), records)
    return records


def _write_tab(name, records):
    """Persist list[dict] to disk and refresh cache."""
    path = _path(name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    with _cache_lock:
        _cache[name] = (datetime.now(), records)


def _invalidate(name=None):
    """Mark one or all caches as stale (kept until next successful read)."""
    with _cache_lock:
        if name is None:
            for k in _cache:
                _cache[k] = (datetime.fromtimestamp(0), _cache[k][1])
        elif name in _cache:
            _cache[name] = (datetime.fromtimestamp(0), _cache[name][1])


def _read_singleton(name, default):
    """Read a single-object JSON file (e.g. parish_profile)."""
    path = _path(name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict):
            merged = dict(default)
            merged.update(obj)
            return merged
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return dict(default)


def _write_singleton(name, obj):
    path = _path(name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _prewarm_cache():
    """Force-refresh all entity caches (called on startup and after reset)."""
    for name in ("users", "churches", "members", "ministries",
                 "member_ministries", "offerings", "offerings_items",
                 "announcements"):
        _read_tab(name, use_cache=False)
    print("[db] cache pre-warmed")


# ==================================================================
# USERS — System_Users
# ==================================================================
USERS_TAB = "users"


def _migrate_legacy_credentials():
    """One-time V1.11 upgrade: re-hash any plaintext credentials in
    users.json. Idempotent — skips records already hashed.

    For each user:
      * legacy `password` (plaintext)        → `password_hash` (PBKDF2)
      * legacy `security_answer` (plaintext) → `security_answer_hash` (PBKDF2)
    The plaintext fields are dropped after re-hashing. Safe to call on
    every boot: once migrated, no row has the legacy fields, so it's a
    no-op.
    """
    rows = _read_tab(USERS_TAB)
    changed = False
    for r in rows:
        if not isinstance(r, dict):
            continue
        legacy_pw = r.get("password")
        # A legacy plaintext password is a non-empty string that is NOT
        # already a pbkdf2_sha256$... hash.
        if (isinstance(legacy_pw, str) and legacy_pw
                and not legacy_pw.startswith(HASH_ALGO + "$")
                and "password_hash" not in r):
            r["password_hash"] = hash_password(legacy_pw)
            r["password_algo"] = HASH_ALGO
            r.pop("password", None)
            changed = True
        elif (isinstance(legacy_pw, str) and legacy_pw
                and legacy_pw.startswith(HASH_ALGO + "$")
                and "password_hash" not in r):
            # Already-hashed value sitting in the old field name — just move it.
            r["password_hash"] = legacy_pw
            r["password_algo"] = HASH_ALGO
            r.pop("password", None)
            changed = True
        legacy_ans = r.get("security_answer")
        if (isinstance(legacy_ans, str) and legacy_ans
                and not legacy_ans.startswith(HASH_ALGO + "$")
                and "security_answer_hash" not in r):
            r["security_answer_hash"] = hash_secret(legacy_ans)
            r.pop("security_answer", None)
            changed = True
        elif (isinstance(legacy_ans, str) and legacy_ans
                and legacy_ans.startswith(HASH_ALGO + "$")
                and "security_answer_hash" not in r):
            r["security_answer_hash"] = legacy_ans
            r.pop("security_answer", None)
            changed = True
    if changed:
        _write_tab(USERS_TAB, rows)
    return changed


def list_users(active_only=False):
    rows = _read_tab(USERS_TAB)
    out = []
    for r in rows:
        rec = dict(r)
        rec["active"] = _to_bool(rec.get("active"), True)
        if active_only and not rec["active"]:
            continue
        out.append(rec)
    return out


def find_user_by_credentials(username, password):
    """Login: only users whose status is 'active' may sign in.
    (Self-registered users stay 'pending' until the church shepherd
    approves them.) Password is verified against the stored PBKDF2 hash
    (legacy plaintext is also accepted during migration)."""
    for u in list_users(active_only=True):
        if _user_status(u) != "active":
            continue
        if (u.get("username", "")).lower() != username.lower():
            continue
        stored = u.get("password_hash") or u.get("password") or ""
        if verify_password(password, stored):
            return u
    return None


def find_user_by_id(user_id):
    for u in list_users():
        if u.get("id") == user_id:
            return u
    return None


def find_user_by_username(username):
    for u in list_users():
        if (u.get("username", "")).lower() == username.lower():
            return u
    return None


def insert_user(data):
    """Create a user. The plaintext `password` (if any) is hashed into
    `password_hash` before storage — it is never persisted in clear."""
    username = (data.get("username") or "").strip()
    if not username:
        return None
    if find_user_by_username(username):
        return None  # duplicate
    plain_pw = (data.get("password") or "").strip() or "1234"
    rec = {
        "id": data.get("id") or _new_id("U"),
        "username": username,
        "password_hash": hash_password(plain_pw),
        "password_algo": HASH_ALGO,
        "password_changed_at": _now_iso(),
        "name": (data.get("name") or "").strip(),
        "role": (data.get("role") or "CHURCH_PASTOR").upper(),
        "phone": (data.get("phone") or "").strip(),
        "email": (data.get("email") or "").strip(),
        "church_id": data.get("church_id", ""),
        "ministry_id": data.get("ministry_id", ""),
        # V1.25 — zone a ZONE_READER leads (empty for other roles).
        "zone_id": data.get("zone_id", ""),
        # V1.20 — leader/shepherd who supervises this account.
        "leader_name": (data.get("leader_name") or "").strip(),
        "active": _to_bool(data.get("active", True)),
        "created_at": _now_iso(),
    }
    rows = _read_tab(USERS_TAB)
    rows.append(rec)
    _write_tab(USERS_TAB, rows)
    return rec


def update_user(user_id, updates):
    """Patch a user. Credential fields are intercepted and hashed:
      * `password`        → hashed into `password_hash`
      * `security_answer` → hashed into `security_answer_hash`
    so callers can keep passing plaintext (the API contract is
    unchanged) while storage stays hash-only."""
    rows = _read_tab(USERS_TAB)
    found = False
    for r in rows:
        if r.get("id") != user_id:
            continue
        for k, v in updates.items():
            if k == "active":
                r["active"] = _to_bool(v, True)
            elif k == "role":
                r["role"] = str(v).upper()
            elif k == "password":
                # Plaintext from caller → hashed hash.
                if isinstance(v, str) and v:
                    r["password_hash"] = hash_password(v)
                    r["password_algo"] = HASH_ALGO
                    r["password_changed_at"] = _now_iso()
                r.pop("password", None)
            elif k == "security_answer":
                if isinstance(v, str) and v:
                    r["security_answer_hash"] = hash_secret(v)
                r.pop("security_answer", None)
            elif k in ("password_hash", "security_answer_hash"):
                # Direct hash assignment (internal) — store as-is.
                r[k] = v
            else:
                r[k] = v
        found = True
        break
    if found:
        _write_tab(USERS_TAB, rows)
    return found


def delete_user_hard(user_id):
    rows = _read_tab(USERS_TAB)
    new_rows = [r for r in rows if r.get("id") != user_id]
    if len(new_rows) == len(rows):
        return False
    _write_tab(USERS_TAB, new_rows)
    # Cascade: drop assignments
    mm = _read_tab("member_ministries")
    _write_tab("member_ministries", [m for m in mm if m.get("member_id") != user_id])
    return True


# ------------------------------------------------------------------
# Self-service registration + church-pastor approval + password reset
# ------------------------------------------------------------------
USER_STATUSES = ["active", "pending", "rejected"]
# Roles a person can self-register for (church shepherd approves them):
SELF_REGISTER_ROLES = ["CHURCH_FINANCE", "MINISTRY_LEADER", "ZONE_READER"]
SECURITY_QUESTIONS = [
    "Izina rya sekuru wawe ni ryande?",
    "Amazina y'umukobwa w'itangiriro ni ayande?",
    "Umuryango wawe uvukiyemo witwa iki?",
    "Icyitonderwa cyawe cyangwa ijambo bakoresha cyane ni iki?",
]


def _user_status(u, default="active"):
    s = (u.get("status") or default).lower()
    return s if s in USER_STATUSES else default


def register_user(data):
    """Public self-registration → status='pending' until church shepherd
    approves. Returns (rec, error)."""
    username = (data.get("username") or "").strip()
    if not username:
        return None, "Username irakenewe."
    if find_user_by_username(username):
        return None, "Username yamaze gukoresha. Hitamo inyandiko."
    role = (data.get("role") or "").upper()
    if role not in SELF_REGISTER_ROLES:
        return None, "Role yemewe: CHURCH_FINANCE, MINISTRY_LEADER, cyangwa ZONE_READER."
    church_id = (data.get("church_id") or "").strip()
    if not church_id:
        return None, "Hitamo itorero ryawe."
    church = find_church(church_id)
    if not church:
        return None, "Itorero watoranyije ntibonetse."
    name = (data.get("name") or "").strip()
    if not name:
        return None, "Andika amazina yawe."
    password = (data.get("password") or "").strip()
    if len(password) < 4:
        return None, "Ijambo ry'ibanga rigomba kuba rifite inyuguti 4+."
    security_question = (data.get("security_question") or "").strip()
    security_answer = (data.get("security_answer") or "").strip().lower()
    if not security_question or not security_answer:
        return None, "Icyibazo cyo kubaza n'igisubizo birakenewe (kuri password)."
    rec = {
        "id": _new_id("U"),
        "username": username,
        "password_hash": hash_password(password),
        "password_algo": HASH_ALGO,
        "password_changed_at": _now_iso(),
        "name": name,
        "role": role,
        "phone": (data.get("phone") or "").strip(),
        "email": (data.get("email") or "").strip(),
        "church_id": church_id,
        "ministry_id": (data.get("ministry_id") or ""),
        "zone_id": (data.get("zone_id") or ""),
        "active": True,
        "status": "pending",
        "security_question": security_question,
        "security_answer_hash": hash_secret(security_answer),
        "approved_by": "",
        "approved_by_name": "",
        "approved_at": "",
        "registration_note": (data.get("registration_note") or "").strip(),
        "created_at": _now_iso(),
    }
    rows = _read_tab(USERS_TAB)
    rows.append(rec)
    _write_tab(USERS_TAB, rows)
    return rec, None


def list_pending_users(church_id=None):
    rows = _read_tab(USERS_TAB)
    out = []
    for r in rows:
        if _user_status(r) != "pending":
            continue
        if church_id and r.get("church_id") != church_id:
            continue
        out.append(dict(r))
    out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return out


def approve_user(user_id, approver):
    rows = _read_tab(USERS_TAB)
    for r in rows:
        if r.get("id") == user_id:
            if _user_status(r) != "pending":
                return None
            r["status"] = "active"
            r["active"] = True
            r["approved_by"] = approver.get("id", "")
            r["approved_by_name"] = approver.get("name", "")
            r["approved_at"] = _now_iso()
            _write_tab(USERS_TAB, rows)
            return r
    return None


def reject_user(user_id, approver, reason=""):
    rows = _read_tab(USERS_TAB)
    for r in rows:
        if r.get("id") == user_id:
            if _user_status(r) != "pending":
                return None
            r["status"] = "rejected"
            r["approved_by"] = approver.get("id", "")
            r["approved_by_name"] = approver.get("name", "")
            r["approved_at"] = _now_iso()
            r["registration_note"] = (r.get("registration_note", "") +
                                       " | REJECTED: " + reason)
            _write_tab(USERS_TAB, rows)
            return r
    return None


def get_security_question(username):
    u = find_user_by_username(username)
    if not u:
        return None
    q = u.get("security_question", "")
    if not q:
        return None
    return {"username": u.get("username", ""), "security_question": q}


def reset_password(username, security_answer, new_password):
    """Self-service: verify the security answer, then set a new password."""
    u = find_user_by_username(username)
    if not u:
        return None, "Username ntabonetse."
    stored = u.get("security_answer_hash") or u.get("security_answer") or ""
    if not stored:
        return None, "Nta cyibazo cyo kubaza cyabitswe kuri iyi konti."
    if not verify_secret(security_answer or "", stored):
        return None, "Igisubizo si cyo. Ongera ugerageze."
    if len(new_password) < 4:
        return None, "Ijambo ry'ibanga rigomba kuba rifite inyuguti 4+."
    update_user(u["id"], {"password": new_password})
    return u, None


def change_password(user_id, old_password, new_password):
    u = find_user_by_id(user_id)
    if not u:
        return None, "Konti ntabonetse."
    stored = u.get("password_hash") or u.get("password") or ""
    if not verify_password(old_password or "", stored):
        return None, "Ijambo ry'ibanga rya kale si ryo."
    if len(new_password) < 4:
        return None, "Ijambo ry'ibanga rishya rigomba kuba rifite inyuguti 4+."
    update_user(user_id, {"password": new_password})
    return u, None


# Run the V1.11 credential migration once on import. Idempotent: if the
# data file does not yet exist (fresh install) or is already migrated,
# this is a no-op. Wrapped so an I/O hiccup never blocks app startup.
try:
    _migrate_legacy_credentials()
except Exception:
    pass


# ==================================================================
# CHURCHES — System_Churches (amatorero)
# ==================================================================
CHURCHES_TAB = "churches"


def list_churches(parish=None):
    rows = _read_tab(CHURCHES_TAB)
    if parish:
        rows = [r for r in rows if (r.get("parish", "")).lower() == parish.lower()]
    return rows


def find_church(church_id):
    for c in _read_tab(CHURCHES_TAB):
        if c.get("id") == church_id:
            return c
    return None


def insert_church(data):
    if not data.get("name"):
        return None
    rec = {
        "id": data.get("id") or _new_id("C"),
        "name": (data.get("name") or "").strip(),
        "parish": (data.get("parish") or "RUHANGO").strip().upper(),
        "leader_name": (data.get("leader_name") or "").strip(),
        "leader_phone": (data.get("leader_phone") or "").strip(),
        "leader_email": (data.get("leader_email") or "").strip(),
        "location": (data.get("location") or "").strip(),
        "active": _to_bool(data.get("active", True)),
        "created_at": _now_iso(),
    }
    rows = _read_tab(CHURCHES_TAB)
    rows.append(rec)
    _write_tab(CHURCHES_TAB, rows)
    return rec


def update_church(church_id, updates):
    rows = _read_tab(CHURCHES_TAB)
    found = False
    for r in rows:
        if r.get("id") == church_id:
            for k, v in updates.items():
                if k == "active":
                    r[k] = _to_bool(v, True)
                else:
                    r[k] = v
            found = True
            break
    if found:
        _write_tab(CHURCHES_TAB, rows)
    return found


def delete_church(church_id):
    rows = _read_tab(CHURCHES_TAB)
    new_rows = [r for r in rows if r.get("id") != church_id]
    if len(new_rows) == len(rows):
        return False
    _write_tab(CHURCHES_TAB, new_rows)
    # Cascade: drop members of this church
    members = _read_tab("members")
    _write_tab("members", [m for m in members if m.get("church_id") != church_id])
    # Cascade: orphan the church pastor account
    users = _read_tab(USERS_TAB)
    for u in users:
        if u.get("church_id") == church_id:
            u["church_id"] = ""
            u["active"] = False
    _write_tab(USERS_TAB, users)
    return True


# ==================================================================
# MEMBERS — System_Members (abakristo)
# ==================================================================
MEMBERS_TAB = "members"

# Categories from the instruction
MEMBER_CATEGORIES = [
    "ABAKRISTO_BOSE",        # all believers
    "ABIGIRA_UMUBATIZO",     # baptism candidates
    "ABARINYUMA_Y_ITORERO",  # backsliders
    "ABASHYINGIWE",          # married
    "ABATASHYE_GUPFA",       # widowed
    "USHINZWE_IMALI",        # treasurer
    "UMUYOBOZI_MINISTEUR",   # ministry leader
    "ABAKRISTO_BASHYA",      # new believers
]


def list_members(church_id=None, category=None, include_deceased=False):
    rows = _read_tab(MEMBERS_TAB)
    if not include_deceased:
        rows = [r for r in rows if not r.get("deceased")]
    if church_id:
        rows = [r for r in rows if r.get("church_id") == church_id]
    if category:
        rows = [r for r in rows if r.get("category") == category]
    return rows


def find_member(member_id):
    for m in _read_tab(MEMBERS_TAB):
        if m.get("id") == member_id:
            return m
    return None


def insert_member(data):
    if not data.get("name") or not data.get("church_id"):
        return None
    rec = {
        "id": data.get("id") or _new_id("M"),
        "church_id": data["church_id"],
        "name": (data.get("name") or "").strip(),
        "gender": (data.get("gender") or "").upper(),
        "phone": (data.get("phone") or "").strip(),
        "category": (data.get("category") or "ABAKRISTO_BOSE").upper(),
        "dob": data.get("dob", ""),
        "baptism_date": data.get("baptism_date", ""),
        "ministry_id": data.get("ministry_id", ""),
        "zone_id": data.get("zone_id", ""),
        "address": data.get("address", ""),
        "active": _to_bool(data.get("active", True)),
        # V1.8 full profile fields
        "national_id": (data.get("national_id") or "").strip(),
        "marital_status": (data.get("marital_status") or "").upper(),
        "education_level": (data.get("education_level") or "").upper(),
        "field_of_study": (data.get("field_of_study") or "").strip(),
        "occupation": (data.get("occupation") or "").strip(),
        "photo": data.get("photo", ""),
        "baptism_certificate": data.get("baptism_certificate", ""),
        "documents": data.get("documents", []) if isinstance(data.get("documents"), list) else [],
        "emergency_contact": (data.get("emergency_contact") or "").strip(),
        "created_at": _now_iso(),
    }
    rows = _read_tab(MEMBERS_TAB)
    rows.append(rec)
    _write_tab(MEMBERS_TAB, rows)
    # Refresh church's member_count via read (computed in dashboard)
    return rec


def update_member(member_id, updates):
    rows = _read_tab(MEMBERS_TAB)
    found = False
    for r in rows:
        if r.get("id") == member_id:
            for k, v in updates.items():
                if k == "active":
                    r[k] = _to_bool(v, True)
                elif k in ("category", "gender"):
                    r[k] = str(v).upper()
                else:
                    r[k] = v
            found = True
            break
    if found:
        _write_tab(MEMBERS_TAB, rows)
    return found


def delete_member(member_id):
    rows = _read_tab(MEMBERS_TAB)
    new_rows = [r for r in rows if r.get("id") != member_id]
    if len(new_rows) == len(rows):
        return False
    _write_tab(MEMBERS_TAB, new_rows)
    mm = _read_tab("member_ministries")
    _write_tab("member_ministries", [m for m in mm if m.get("member_id") != member_id])
    return True


def member_count_by_category(church_id=None):
    rows = list_members(church_id=church_id)
    counts = {c: 0 for c in MEMBER_CATEGORIES}
    for m in rows:
        cat = m.get("category", "ABAKRISTO_BOSE")
        counts[cat] = counts.get(cat, 0) + 1
    return counts


# ==================================================================
# MINISTRIES — System_Ministries (ministeur)
# ==================================================================
MINISTRIES_TAB = "ministries"


def list_ministries(active_only=False, church_id=None, include_parish_wide=True):
    rows = _read_tab(MINISTRIES_TAB)
    if active_only:
        rows = [r for r in rows if _to_bool(r.get("active"), True)]
    if church_id:
        # V1.27 — church-scoped ministries. Parish-wide ones (no church_id)
        # are shared across all churches unless explicitly excluded.
        if include_parish_wide:
            rows = [r for r in rows if not r.get("church_id") or r.get("church_id") == church_id]
        else:
            rows = [r for r in rows if r.get("church_id") == church_id]
    return rows


def find_ministry(ministry_id):
    for m in _read_tab(MINISTRIES_TAB):
        if m.get("id") == ministry_id:
            return m
    return None


def insert_ministry(data):
    if not data.get("name"):
        return None
    rec = {
        "id": data.get("id") or _new_id("MN"),
        "name": (data.get("name") or "").strip(),
        "description": data.get("description", ""),
        "leader_name": (data.get("leader_name") or "").strip(),
        "leader_phone": (data.get("leader_phone") or "").strip(),
        "leader_id": data.get("leader_id", ""),
        # V1.27 — empty = parish-wide ministry (shared by all churches),
        # set = ministry belongs to that specific church only.
        "church_id": (data.get("church_id") or "").strip(),
        "active": _to_bool(data.get("active", True)),
        "created_at": _now_iso(),
    }
    rows = _read_tab(MINISTRIES_TAB)
    rows.append(rec)
    _write_tab(MINISTRIES_TAB, rows)
    return rec


def update_ministry(ministry_id, updates):
    rows = _read_tab(MINISTRIES_TAB)
    found = False
    for r in rows:
        if r.get("id") == ministry_id:
            for k, v in updates.items():
                if k == "active":
                    r[k] = _to_bool(v, True)
                else:
                    r[k] = v
            found = True
            break
    if found:
        _write_tab(MINISTRIES_TAB, rows)
    return found


def delete_ministry(ministry_id):
    rows = _read_tab(MINISTRIES_TAB)
    new_rows = [r for r in rows if r.get("id") != ministry_id]
    if len(new_rows) == len(rows):
        return False
    _write_tab(MINISTRIES_TAB, new_rows)
    # Cascade: orphan ministry leader account + member assignments
    users = _read_tab(USERS_TAB)
    for u in users:
        if u.get("ministry_id") == ministry_id:
            u["ministry_id"] = ""
            u["active"] = False
    _write_tab(USERS_TAB, users)
    mm = _read_tab("member_ministries")
    _write_tab("member_ministries", [m for m in mm if m.get("ministry_id") != ministry_id])
    return True


# ==================================================================
# MEMBER ↔ MINISTRY assignments
# ==================================================================
MM_TAB = "member_ministries"


def list_member_ministries(member_id=None, ministry_id=None):
    rows = _read_tab(MM_TAB)
    if member_id:
        rows = [r for r in rows if r.get("member_id") == member_id]
    if ministry_id:
        rows = [r for r in rows if r.get("ministry_id") == ministry_id]
    return rows


def assign_member_ministries(member_id, ministry_ids):
    rows = _read_tab(MM_TAB)
    rows = [r for r in rows if r.get("member_id") != member_id]
    for mid in ministry_ids:
        rows.append({
            "id": _new_id("MM"),
            "member_id": member_id,
            "ministry_id": mid,
            "assigned_at": _now_iso(),
        })
    _write_tab(MM_TAB, rows)
    return True


# ==================================================================
# OFFERINGS — System_Offerings (weekly offering records)
# ==================================================================
OFFERINGS_TAB = "offerings"
ITEMS_TAB = "offerings_items"

OFFERING_CATEGORIES = [
    "ICYACUMI_IBITURISHO",
    "ICYACUMI_MOMO",
    "ICYACUMI_BANK",
    "ICYACUMI_AGASANDUKA",
    "AMATURO",
    "AMASHIMWE",
    "BURACYEYE",
    "IMISARURO",
]

# Categories that make up the "Igiteranyo" (gross total) used for the
# 7% / 2% / 2% / 89% distribution, matching the Ruhango Parish sheet.
GROSS_CATEGORIES = [
    "ICYACUMI_IBITURISHO", "ICYACUMI_MOMO", "ICYACUMI_BANK",
    "ICYACUMI_AGASANDUKA", "AMATURO", "AMASHIMWE", "BURACYEYE", "IMISARURO",
]
ICYACUMI_CATEGORIES = [
    "ICYACUMI_IBITURISHO", "ICYACUMI_MOMO",
    "ICYACUMI_BANK", "ICYACUMI_AGASANDUKA",
]

# Distribution rates from the ADEPR Ruhango Parish sheet
RATE_CHURCH_7  = 0.07   # 7% asigara ku itorero
RATE_PARISH_2  = 0.02   # 2% Paruwasi
RATE_REGION_2  = 0.02   # 2% Ururembo (Southern Region)
RATE_HQ_89     = 0.89   # 89% azamuka kuri HQ
RATE_CHILDREN  = 0.50   # 50% of HQ share goes to Abana ministry


def compute_distribution(items, abana_amount=0.0, budget=0.0):
    """Return the Ruhango Parish weekly distribution from offering items.

    Mirrors the Excel columns:
      Icyacumi (Ibiturisho/Momo/Banki/Agasanduka/Igiteranyo), Amaturo,
      Amashimwe, Buracyeye/Nibature, Imisaruro, Igiteranyo,
      7% asigara ku itorero, 2% Paruwasi, 2% Ururembo, 89% azamuka kuri HQ,
      Abana (50% share), Igiteranyo 89% + 50% Abana, Budget - icyumweru, %.

    Budget is the church's planned weekly budget (separately entered);
    % = Igiteranyo / Budget * 100 (achievement vs. plan).
    """
    by_cat = {}
    for it in items or []:
        cat = (it.get("category") or "").upper()
        by_cat[cat] = by_cat.get(cat, 0.0) + _to_float(it.get("amount"))

    icyacumi_ibiturisho = by_cat.get("ICYACUMI_IBITURISHO", 0.0)
    icyacumi_momo = by_cat.get("ICYACUMI_MOMO", 0.0)
    icyacumi_bank = by_cat.get("ICYACUMI_BANK", 0.0)
    icyacumi_agasanduka = by_cat.get("ICYACUMI_AGASANDUKA", 0.0)
    icyacumi = (icyacumi_ibiturisho + icyacumi_momo
                + icyacumi_bank + icyacumi_agasanduka)
    igiteranyo = sum(by_cat.get(c, 0.0) for c in GROSS_CATEGORIES)
    abana = _to_float(abana_amount)
    budget_plan = _to_float(budget)

    church_7 = round(igiteranyo * RATE_CHURCH_7, 2)
    parish_2 = round(igiteranyo * RATE_PARISH_2, 2)
    region_2 = round(igiteranyo * RATE_REGION_2, 2)
    hq_89 = round(igiteranyo * RATE_HQ_89, 2)
    children_share = round(abana * RATE_CHILDREN, 2)
    hq_plus_children = round(hq_89 + children_share, 2)
    pct = round((igiteranyo / budget_plan * 100) if budget_plan > 0 else 0.0, 2)

    return {
        "icyacumi_ibiturisho": icyacumi_ibiturisho,
        "icyacumi_momo": icyacumi_momo,
        "icyacumi_bank": icyacumi_bank,
        "icyacumi_agasanduka": icyacumi_agasanduka,
        "icyacumi": icyacumi,
        "amaturo": by_cat.get("AMATURO", 0.0),
        "amashimwe": by_cat.get("AMASHIMWE", 0.0),
        "buracyeye": by_cat.get("BURACYEYE", 0.0),
        "imisaruro": by_cat.get("IMISARURO", 0.0),
        "igiteranyo": igiteranyo,
        "church_7": church_7,
        "parish_2": parish_2,
        "region_2": region_2,
        "hq_89": hq_89,
        "abana_amount": abana,
        "children_share": children_share,
        "hq_plus_children": hq_plus_children,
        "budget_icyumweru": budget_plan,
        "percent": pct,
    }


def list_offerings(church_id=None, start_date=None, end_date=None):
    rows = _read_tab(OFFERINGS_TAB)
    if church_id:
        rows = [r for r in rows if r.get("church_id") == church_id]
    if start_date:
        rows = [r for r in rows if r.get("week_date", "") >= start_date]
    if end_date:
        rows = [r for r in rows if r.get("week_date", "") <= end_date]
    # attach items
    items = _read_tab(ITEMS_TAB)
    by_off = {}
    for it in items:
        by_off.setdefault(it.get("offering_id"), []).append(it)
    for r in rows:
        its = by_off.get(r.get("id"), [])
        r["items"] = its
        # Budget comes from what the parish pastor assigned to this church for
        # that week; fall back to a budget stored on the offering (legacy).
        budget = get_church_budget(r.get("church_id"), r.get("week_date"))
        if not budget:
            budget = _to_float(r.get("budget", 0.0))
        r["budget"] = budget
        r["distribution"] = compute_distribution(
            its, r.get("abana_amount", 0.0), budget)
    return rows


def insert_offering(payload):
    """payload = {church_id, week_date, recorded_by, items:[{category, amount, note}],
                  abihannye, abana, abagarutse, abana_amount, budget, notes}"""
    if not payload.get("church_id") or not payload.get("week_date"):
        return None
    items = payload.get("items") or []
    total = sum(_to_float(it.get("amount")) for it in items)
    abana_amount = _to_float(payload.get("abana_amount", 0.0))
    budget = _to_float(payload.get("budget", 0.0))
    off_id = _new_id("O")
    rec = {
        "id": off_id,
        "church_id": payload["church_id"],
        "week_date": payload["week_date"],
        "recorded_by": payload.get("recorded_by", ""),
        "recorder_name": payload.get("recorder_name", ""),
        "recorder_role": payload.get("recorder_role", ""),
        "total": total,
        "abihannye": _to_int(payload.get("abihannye", 0)),
        "abana": _to_int(payload.get("abana", 0)),
        "abagarutse": _to_int(payload.get("abagarutse", 0)),
        "abana_amount": abana_amount,
        "budget": budget,
        "notes": payload.get("notes", ""),
        "created_at": _now_iso(),
    }
    offs = _read_tab(OFFERINGS_TAB)
    offs.append(rec)
    _write_tab(OFFERINGS_TAB, offs)
    # write items
    items_rows = _read_tab(ITEMS_TAB)
    for it in items:
        amt = _to_float(it.get("amount"))
        if amt <= 0:
            continue
        # Proof-file attachments (MoMo SMS, bank slip, ...).
        # Each attachment is normalized to {path, original_name, kind, size, uploaded_at}.
        # `kind` defaults from the item category so a finance officer just uploads
        # the file under the right row and the parish pastor can tell them apart.
        cat = (it.get("category") or "").upper()
        atts = []
        for a in (it.get("attachments") or []):
            if isinstance(a, str):
                a = {"path": a}
            if not isinstance(a, dict) or not a.get("path"):
                continue
            kind = (a.get("kind") or "").lower()
            if kind not in ("momo_sms", "bank_slip", "other"):
                kind = ("momo_sms" if cat == "ICYACUMI_MOMO"
                        else "bank_slip" if cat == "ICYACUMI_BANK"
                        else "other")
            atts.append({
                "path": a.get("path"),
                "original_name": a.get("original_name") or a.get("path", ""),
                "kind": kind,
                "size": _to_int(a.get("size", 0)),
                "uploaded_at": a.get("uploaded_at") or _now_iso(),
            })
        items_rows.append({
            "id": _new_id("OI"),
            "offering_id": off_id,
            "category": cat,
            "amount": amt,
            "note": it.get("note", ""),
            "attachments": atts,
            # V1.15: flag set by the client when the user accepted to save
            # a MoMo/Bank amount WITHOUT a proof attachment. The parish
            # auditor sees these flagged rows so they can chase the proof.
            "no_proof": bool(it.get("no_proof", False)),
        })
    _write_tab(ITEMS_TAB, items_rows)
    _invalidate(OFFERINGS_TAB)
    _invalidate(ITEMS_TAB)
    rec["items"] = [r for r in items_rows if r.get("offering_id") == off_id]
    rec["distribution"] = compute_distribution(
        rec["items"], rec.get("abana_amount", 0.0),
        get_church_budget(rec.get("church_id"), rec.get("week_date"))
        or _to_float(rec.get("budget", 0.0)))
    return rec


def list_offering_attachments(church_id=None, start_date=None, end_date=None):
    """Flatten every proof-file attachment across offerings, newest first.

    Lets the parish pastor audit MoMo SMS / bank slip uploads from all
    churches in one place. Each entry carries the offering + church context
    so the UI can show who uploaded what and when.
    """
    rows = list_offerings(church_id=church_id, start_date=start_date,
                          end_date=end_date)
    churches = {c["id"]: c for c in list_churches()}
    out = []
    for o in rows:
        c = churches.get(o.get("church_id"))
        church_name = (c.get("name") if c else "") or o.get("church_name", "")
        for it in o.get("items", []) or []:
            for a in it.get("attachments", []) or []:
                out.append({
                    "offering_id": o.get("id", ""),
                    "week_date": o.get("week_date", ""),
                    "church_id": o.get("church_id", ""),
                    "church_name": church_name,
                    "recorder_name": o.get("recorder_name", ""),
                    "category": it.get("category", ""),
                    "amount": it.get("amount", 0),
                    "path": a.get("path", ""),
                    "original_name": a.get("original_name", ""),
                    "kind": a.get("kind", "other"),
                    "size": a.get("size", 0),
                    "uploaded_at": a.get("uploaded_at", ""),
                })
    out.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
    return out


# ==================================================================
# ANNOUNCEMENTS — System_Announcements (SMS broadcasts)
# ==================================================================
ANN_TAB = "announcements"


def list_announcements():
    return _read_tab(ANN_TAB)


def insert_announcement(data):
    rec = {
        "id": _new_id("A"),
        "title": (data.get("title") or "").strip(),
        "message": data.get("message", ""),
        "target_role": (data.get("target_role") or "ALL").upper(),
        "sent_by": data.get("sent_by", ""),
        "sender_name": data.get("sender_name", ""),
        "dry_run": _to_bool(data.get("dry_run", True), True),
        "recipients_count": _to_int(data.get("recipients_count", 0)),
        "sent_count": _to_int(data.get("sent_count", 0)),
        "failed_count": _to_int(data.get("failed_count", 0)),
        "status": data.get("status", "SENT"),
        "created_at": _now_iso(),
    }
    rows = _read_tab(ANN_TAB)
    rows.append(rec)
    _write_tab(ANN_TAB, rows)
    return rec


# ==================================================================
# SIGNATURES — single JSON object {user_id: {...}}
# ==================================================================
SIG_FILE = "signatures"


def load_signatures():
    return _read_singleton(SIG_FILE, {})


def get_signature(user_id):
    sigs = load_signatures()
    return sigs.get(user_id, {})


def save_signature(user_id, png_base64, name=""):
    sigs = load_signatures()
    sigs[user_id] = {
        "png_base64": png_base64,
        "name": name,
        "signed_at": _now_iso(),
    }
    _write_singleton(SIG_FILE, sigs)
    return True


# ==================================================================
# PARISH PROFILE — single object
# ==================================================================
PROFILE_FILE = "parish_profile"

PROFILE_DEFAULTS = {
    "parish_name": "ADEPR PARUWASI YA RUHANGO",
    "region": "SOUTHERN REGION",
    "pastor_name": "Pasteur Muyobozi wa Paruwasi",
    "pastor_title": "Umushumba wa Paruwasi",
    "pastor_phone": "0780000000",
    "pastor_email": "paruwasi@adepr.rw",
    "address": "Ruhango, Rwanda",
    "drive_link": "",
    "tin": "",
}


def load_parish_profile():
    return _read_singleton(PROFILE_FILE, PROFILE_DEFAULTS)


def save_parish_profile(data):
    current = load_parish_profile()
    for k in PROFILE_DEFAULTS:
        if k in data:
            current[k] = data[k]
    _write_singleton(PROFILE_FILE, current)
    return current


# ==================================================================
# TRANSLATIONS — UI strings
# ==================================================================
TRANS_FILE = "translations"


def load_translations():
    return _read_singleton(TRANS_FILE, {})


def save_translations(data):
    current = load_translations()
    for k, v in data.items():
        if k.startswith("_"):
            continue
        current[k] = v
    _write_singleton(TRANS_FILE, current)
    return current


# ==================================================================
# DASHBOARD aggregates
# ==================================================================
def dashboard_kpis(parish_pastor=False, church_id=None, ministry_id=None):
    """KPIs tailored to the viewer's role."""
    users = list_users()
    churches = list_churches()
    members = list_members(church_id=church_id)
    ministries = list_ministries()
    offerings = list_offerings(church_id=church_id)

    active_pastors = len([u for u in users if _to_bool(u.get("active"), True)
                          and u.get("role") == "CHURCH_PASTOR"])
    active_finance = len([u for u in users if _to_bool(u.get("active"), True)
                          and u.get("role") == "CHURCH_FINANCE"])
    active_leaders = len([u for u in users if _to_bool(u.get("active"), True)
                          and u.get("role") == "MINISTRY_LEADER"])

    total_offerings = sum(_to_float(o.get("total")) for o in offerings)
    # this week's offerings
    today = datetime.now().date()
    start_of_week = today - timedelta(days=today.weekday())
    week_str = start_of_week.isoformat()
    this_week = sum(_to_float(o.get("total")) for o in offerings
                    if (o.get("week_date") or "") >= week_str)

    # distribution totals (7% / 2% / 2% / 89%) for the parish
    parish_share = sum(_to_float((o.get("distribution") or {}).get("parish_2", 0.0))
                       for o in offerings)
    region_share = sum(_to_float((o.get("distribution") or {}).get("region_2", 0.0))
                       for o in offerings)

    kpis = {
        "total_churches": len(churches),
        "total_members": len(members),
        "total_ministries": len(ministries),
        "active_church_pastors": active_pastors,
        "active_church_finance": active_finance,
        "active_ministry_leaders": active_leaders,
        "total_offerings": total_offerings,
        "this_week_offerings": this_week,
        "offerings_count": len(offerings),
        "parish_share": parish_share,
        "region_share": region_share,
    }
    if parish_pastor:
        kpis["total_announcements"] = len(list_announcements())
    return kpis


def dashboard_charts(church_id=None):
    """Chart series: offerings last 8 weeks + top churches by offerings."""
    offerings = list_offerings(church_id=church_id)
    today = datetime.now().date()
    # last 8 weeks buckets
    weeks = []
    for i in range(7, -1, -1):
        ws = today - timedelta(days=today.weekday() + i * 7)
        weeks.append(ws.isoformat())
    weekly_totals = {w: 0.0 for w in weeks}
    for o in offerings:
        wd = o.get("week_date", "")
        # snap to that week's Monday
        if wd:
            for w in weeks:
                if wd >= w:
                    weekly_totals[w] = weekly_totals.get(w, 0) + _to_float(o.get("total"))
                    break
    offerings_last_8_weeks = [
        {"date": datetime.fromisoformat(w).strftime("%d/%m"), "value": weekly_totals[w]}
        for w in weeks
    ]
    # top churches by total offerings
    by_church = {}
    church_names = {c["id"]: c.get("name", c["id"]) for c in list_churches()}
    for o in offerings:
        cid = o.get("church_id", "")
        by_church[cid] = by_church.get(cid, 0) + _to_float(o.get("total"))
    top_churches = sorted(
        [{"name": church_names.get(cid, cid), "value": v} for cid, v in by_church.items()],
        key=lambda x: x["value"], reverse=True
    )[:8]
    # members by category
    cat_counts = member_count_by_category(church_id=church_id)
    members_by_category = [
        {"name": k.replace("_", " ").title(), "value": v}
        for k, v in cat_counts.items() if v > 0
    ]
    return {
        "offerings_last_8_weeks": offerings_last_8_weeks,
        "top_churches": top_churches,
        "members_by_category": members_by_category,
    }


def rankings(parish=None, start_date=None, end_date=None):
    """Rank churches by total offerings in the period (Igiteranyo).

    Includes the full distribution (7%/2%/2%/89%) per church plus the
    Icyacumi sub-category breakdown (Ibiturisho/Momo/Banki/Agasanduka)
    and the planned Budget, matching the Ruhango Parish
    'incamake y'icyumweru' Excel sheet.
    """
    offerings = list_offerings(start_date=start_date, end_date=end_date)
    churches = list_churches(parish=parish)
    church_names = {c["id"]: c for c in churches}
    by_church = {}
    for o in offerings:
        cid = o.get("church_id", "")
        if cid not in church_names:
            continue
        dist = o.get("distribution") or compute_distribution(
            o.get("items", []), o.get("abana_amount", 0.0), o.get("budget", 0.0))
        agg = by_church.setdefault(cid, {
            "church_id": cid, "total": 0.0,
            "icyacumi_ibiturisho": 0.0, "icyacumi_momo": 0.0,
            "icyacumi_bank": 0.0, "icyacumi_agasanduka": 0.0,
            "icyacumi": 0.0,
            "igiteranyo": 0.0, "amaturo": 0.0, "amashimwe": 0.0,
            "buracyeye": 0.0, "imisaruro": 0.0,
            "church_7": 0.0, "parish_2": 0.0, "region_2": 0.0, "hq_89": 0.0,
            "abana_amount": 0.0, "children_share": 0.0,
            "hq_plus_children": 0.0, "budget_icyumweru": 0.0,
            "abihannye": 0, "abana": 0, "abagarutse": 0,
            "offerings_count": 0,
        })
        agg["total"] += _to_float(o.get("total"))
        agg["icyacumi_ibiturisho"] += dist["icyacumi_ibiturisho"]
        agg["icyacumi_momo"] += dist["icyacumi_momo"]
        agg["icyacumi_bank"] += dist["icyacumi_bank"]
        agg["icyacumi_agasanduka"] += dist["icyacumi_agasanduka"]
        agg["icyacumi"] += dist["icyacumi"]
        agg["igiteranyo"] += dist["igiteranyo"]
        agg["amaturo"] += dist["amaturo"]
        agg["amashimwe"] += dist["amashimwe"]
        agg["buracyeye"] += dist["buracyeye"]
        agg["imisaruro"] += dist["imisaruro"]
        agg["church_7"] += dist["church_7"]
        agg["parish_2"] += dist["parish_2"]
        agg["region_2"] += dist["region_2"]
        agg["hq_89"] += dist["hq_89"]
        agg["abana_amount"] += dist["abana_amount"]
        agg["children_share"] += dist["children_share"]
        agg["hq_plus_children"] += dist["hq_plus_children"]
        agg["budget_icyumweru"] += dist["budget_icyumweru"]
        agg["abihannye"] += _to_int(o.get("abihannye"))
        agg["abana"] += _to_int(o.get("abana"))
        agg["abagarutse"] += _to_int(o.get("abagarutse"))
        agg["offerings_count"] += 1
    ranked = []
    for cid, agg in by_church.items():
        c = church_names[cid]
        row = {
            "church_id": cid,
            "name": c.get("name", cid),
            "parish": c.get("parish", ""),
            "leader_name": c.get("leader_name", ""),
            "leader_phone": c.get("leader_phone", ""),
        }
        row.update(agg)
        # achievement % = Igiteranyo / Budget * 100
        budget = agg.get("budget_icyumweru", 0.0)
        igit = agg.get("igiteranyo", 0.0)
        row["percent"] = round((igit / budget * 100) if budget > 0 else 0.0, 2)
        ranked.append(row)
    ranked.sort(key=lambda x: x["total"], reverse=True)
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    return ranked


def parish_weekly_summary(start_date=None, end_date=None):
    """Aggregate the whole parish (Ruhango) for the period — the
    'incamake y'icyumweru' totals row of the Excel sheet.

    Returns the summed distribution across all 38 churches plus the
    number of churches that reported.
    """
    ranked = rankings(start_date=start_date, end_date=end_date)
    keys = ["total", "icyacumi_ibiturisho", "icyacumi_momo", "icyacumi_bank",
            "icyacumi_agasanduka", "icyacumi",
            "igiteranyo", "amaturo", "amashimwe", "buracyeye",
            "imisaruro", "church_7", "parish_2", "region_2",
            "hq_89", "abana_amount", "children_share", "hq_plus_children",
            "budget_icyumweru", "abihannye", "abana", "abagarutse",
            "offerings_count"]
    summary = {k: 0.0 for k in keys}
    for r in ranked:
        for k in keys:
            v = r.get(k, 0)
            if isinstance(v, bool):
                continue
            summary[k] += float(v) if v is not None else 0.0
    summary["churches_reporting"] = len(ranked)
    summary["total_churches"] = len(list_churches())
    # parish-level achievement %
    igit = summary.get("igiteranyo", 0.0)
    budget = summary.get("budget_icyumweru", 0.0)
    summary["percent"] = round((igit / budget * 100) if budget > 0 else 0.0, 2)
    return summary


def church_comparison(church_id):
    """Where this church stands relative to the others: rank by offerings,
    by Abihannye count, and by member count, plus parish average / top / bottom.

    Mirrors the 'my_rank' page benchmark cards.
    """
    ranked = rankings()
    churches = list_churches()
    total_churches = len(churches)
    mine = next((r for r in ranked if r.get("church_id") == church_id), None)
    if not mine:
        return None

    # rank by abihannye
    by_abihannye = sorted(ranked, key=lambda x: x.get("abihannye", 0), reverse=True)
    abihannye_rank = next((i + 1 for i, r in enumerate(by_abihannye)
                          if r.get("church_id") == church_id), 0)
    # rank by members
    member_counts = []
    for c in churches:
        member_counts.append({
            "church_id": c["id"], "name": c.get("name", ""),
            "members": len(list_members(church_id=c["id"])),
        })
    member_counts.sort(key=lambda x: x["members"], reverse=True)
    members_rank = next((i + 1 for i, r in enumerate(member_counts)
                         if r.get("church_id") == church_id), 0)
    my_members = next((r.get("members", 0) for r in member_counts
                       if r.get("church_id") == church_id), 0)

    igiteranyo_values = [r.get("igiteranyo", 0.0) for r in ranked]
    avg_igit = (sum(igiteranyo_values) / len(igiteranyo_values)) if igiteranyo_values else 0
    top_igit = max(igiteranyo_values) if igiteranyo_values else 0
    bottom_igit = min(igiteranyo_values) if igiteranyo_values else 0

    abihannye_values = [r.get("abihannye", 0) for r in ranked]
    avg_abih = (sum(abihannye_values) / len(abihannye_values)) if abihannye_values else 0

    member_values = [r["members"] for r in member_counts]
    avg_members = (sum(member_values) / len(member_values)) if member_values else 0

    return {
        "church_id": church_id,
        "church_name": mine.get("name", ""),
        "rank_offerings": mine.get("rank", 0),
        "rank_abihannye": abihannye_rank,
        "rank_members": members_rank,
        "total_churches": total_churches,
        "my_igiteranyo": mine.get("igiteranyo", 0.0),
        "my_abihannye": mine.get("abihannye", 0),
        "my_members": my_members,
        "my_budget": mine.get("budget_icyumweru", 0.0),
        "my_percent": mine.get("percent", 0.0),
        "avg_igiteranyo": round(avg_igit, 2),
        "top_igiteranyo": round(top_igit, 2),
        "bottom_igiteranyo": round(bottom_igit, 2),
        "avg_abihannye": round(avg_abih, 1),
        "avg_members": round(avg_members, 1),
    }


# ==================================================================
# CHURCH WEEKLY BUDGETS  (set by the Parish Pastor)
# ==================================================================
CHURCH_BUDGETS_TAB = "church_budgets"


def set_church_budget(church_id, week_date, amount, set_by=""):
    """Upsert the weekly budget a parish pastor assigns to a church."""
    if not church_id or not week_date:
        return None
    rows = _read_tab(CHURCH_BUDGETS_TAB)
    amt = _to_float(amount)
    existing = next((r for r in rows if r.get("church_id") == church_id
                     and r.get("week_date") == week_date), None)
    if existing:
        existing["amount"] = amt
        existing["set_by"] = set_by
        existing["updated_at"] = _now_iso()
    else:
        existing = {
            "id": _new_id("B"),
            "church_id": church_id,
            "week_date": week_date,
            "amount": amt,
            "set_by": set_by,
            "created_at": _now_iso(),
        }
        rows.append(existing)
    _write_tab(CHURCH_BUDGETS_TAB, rows)
    return existing


def get_church_budget(church_id, week_date):
    """Return the budget amount for a church on a given week (0 if never set).

    V1.19 — budgets now persist across weeks. If no budget was recorded for
    the exact `week_date`, fall back to the most recent budget the parish
    pastor previously set for this church (any earlier week). This means a
    parish pastor sets a budget ONCE and it carries forward to every
    following week until they explicitly change it. Offerings still roll
    weekly (each week has its own offering rows); only the budget plan
    carries forward.
    """
    rows = _read_tab(CHURCH_BUDGETS_TAB)
    # 1) Exact week match.
    for r in rows:
        if r.get("church_id") == church_id and r.get("week_date") == week_date:
            return _to_float(r.get("amount"))
    # 2) Fall back to the most recent earlier budget for this church.
    candidates = [r for r in rows
                  if r.get("church_id") == church_id
                  and r.get("week_date")
                  and r.get("week_date") <= week_date]
    if candidates:
        candidates.sort(key=lambda x: x.get("week_date", ""), reverse=True)
        return _to_float(candidates[0].get("amount"))
    # 3) Last resort: any budget ever set for this church (even a future
    #    one) — better than 0 so the dashboard % doesn't read 0.
    any_for_church = [r for r in rows if r.get("church_id") == church_id]
    if any_for_church:
        any_for_church.sort(key=lambda x: x.get("updated_at") or x.get("created_at") or "", reverse=True)
        return _to_float(any_for_church[0].get("amount"))
    return 0.0


def list_church_budgets(week_date=None, church_id=None):
    """List budget rows. With a `week_date`, returns one row per church for
    that week — and if a church has no budget set for that exact week, the
    most recent earlier budget carries forward (V1.19: budgets persist
    across weeks). Without `week_date`, returns every stored row."""
    rows = _read_tab(CHURCH_BUDGETS_TAB)
    if church_id:
        rows = [r for r in rows if r.get("church_id") == church_id]
    if not week_date:
        return rows
    # With week_date: build one effective budget per church for that week.
    # Group all rows for each church, then pick the best match for this week.
    by_church = {}
    for r in rows:
        cid = r.get("church_id")
        by_church.setdefault(cid, []).append(r)
    out = []
    for cid, church_rows in by_church.items():
        # Exact week match wins.
        exact = next((r for r in church_rows if r.get("week_date") == week_date), None)
        if exact:
            out.append(exact)
            continue
        # Otherwise carry forward the most recent earlier budget.
        earlier = [r for r in church_rows
                   if r.get("week_date") and r.get("week_date") <= week_date]
        if earlier:
            earlier.sort(key=lambda x: x.get("week_date", ""), reverse=True)
            src = earlier[0]
        else:
            # Last resort: most recent of any week.
            any_sorted = sorted(church_rows,
                                key=lambda x: x.get("updated_at") or x.get("created_at") or "",
                                reverse=True)
            src = any_sorted[0] if any_sorted else None
        if src:
            # Project the carried-forward budget onto this week so the UI
            # shows it as the active budget for week_date.
            out.append({
                "id": src.get("id"),
                "church_id": cid,
                "week_date": week_date,
                "amount": _to_float(src.get("amount")),
                "set_by": src.get("set_by", ""),
                "created_at": src.get("created_at", ""),
                "updated_at": src.get("updated_at", ""),
                "carried_from": src.get("week_date", ""),  # audit hint
            })
    return out


def set_budgets_for_week(week_date, items, set_by=""):
    """Bulk-set budgets for a week. items = [{church_id, amount}, ...]"""
    rows = _read_tab(CHURCH_BUDGETS_TAB)
    by_key = {(r.get("church_id"), r.get("week_date")): r for r in rows}
    for it in items or []:
        cid = it.get("church_id")
        if not cid:
            continue
        amt = _to_float(it.get("amount"))
        key = (cid, week_date)
        if key in by_key:
            by_key[key]["amount"] = amt
            by_key[key]["set_by"] = set_by
            by_key[key]["updated_at"] = _now_iso()
        else:
            rec = {
                "id": _new_id("B"),
                "church_id": cid,
                "week_date": week_date,
                "amount": amt,
                "set_by": set_by,
                "created_at": _now_iso(),
            }
            rows.append(rec)
            by_key[key] = rec
    _write_tab(CHURCH_BUDGETS_TAB, rows)
    return len(items or [])


def clear_budgets_for_week(week_date):
    """V1.21 — Delete all budget rows for a given week."""
    rows = _read_tab(CHURCH_BUDGETS_TAB)
    kept = [r for r in rows if r.get("week_date") != week_date]
    removed = len(rows) - len(kept)
    _write_tab(CHURCH_BUDGETS_TAB, kept)
    return removed


def archive_budget(week_date, church_id):
    """V1.21 — Mark a single church's budget for a week as archived."""
    rows = _read_tab(CHURCH_BUDGETS_TAB)
    found = False
    for r in rows:
        if r.get("week_date") == week_date and r.get("church_id") == church_id:
            r["archived"] = True
            r["archived_at"] = _now_iso()
            found = True
    _write_tab(CHURCH_BUDGETS_TAB, rows)
    return found


# ==================================================================
# NOTIFICATIONS  (bidirectional: parish <-> church / ministry)
# ==================================================================
NOTIFICATIONS_TAB = "notifications"


def send_notification(payload):
    """payload = {sender_id, sender_name, sender_role, recipient_role,
                  recipient_user_id, church_id, title, body, category, parent_id}"""
    title = (payload.get("title") or "").strip()
    body = (payload.get("body") or "").strip()
    if not title and not body:
        return None
    rec = {
        "id": _new_id("N"),
        "sender_id": payload.get("sender_id", ""),
        "sender_name": payload.get("sender_name", ""),
        "sender_role": payload.get("sender_role", ""),
        "recipient_role": (payload.get("recipient_role") or "ALL").upper(),
        "recipient_user_id": payload.get("recipient_user_id", ""),
        "church_id": payload.get("church_id", ""),
        "title": title,
        "body": body,
        "category": payload.get("category", "announcement"),
        "parent_id": payload.get("parent_id", ""),
        "read_by": [],
        "created_at": _now_iso(),
    }
    rows = _read_tab(NOTIFICATIONS_TAB)
    rows.append(rec)
    _write_tab(NOTIFICATIONS_TAB, rows)
    return rec


def _notification_targets_me(note, user):
    """Does this notification belong in the given user's inbox?"""
    role = (user.get("role") or "").upper()
    if note.get("sender_id") == user.get("id"):
        # sender sees their own outgoing too, but flagged
        return True
    if note.get("recipient_user_id") == user.get("id"):
        return True
    rt = (note.get("recipient_role") or "").upper()
    if rt == "ALL":
        return True
    if rt == role:
        return True
    if rt == "ALL_CHURCH" and role in ("CHURCH_PASTOR", "CHURCH_FINANCE"):
        return True
    if rt == "ALL_MINISTRY" and role == "MINISTRY_LEADER":
        return True
    # if the note is scoped to a specific church and the user belongs to that
    # church (any role), they see it — covers a ministry leader who operates
    # inside the targeted church.
    if note.get("church_id") and user.get("church_id") == note.get("church_id"):
        return True
    return False


def list_notifications_for_user(user):
    """Inbox for a user, newest first, with `outgoing` flag + `read` flag."""
    rows = _read_tab(NOTIFICATIONS_TAB)
    out = []
    for n in rows:
        if _notification_targets_me(n, user):
            is_out = n.get("sender_id") == user.get("id")
            n2 = dict(n)
            n2["outgoing"] = is_out
            n2["read"] = user.get("id") in (n.get("read_by") or [])
            out.append(n2)
    out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return out


def unread_notification_count(user):
    rows = _read_tab(NOTIFICATIONS_TAB)
    cnt = 0
    uid = user.get("id")
    for n in rows:
        if n.get("sender_id") == uid:
            continue
        if not _notification_targets_me(n, user):
            continue
        if uid not in (n.get("read_by") or []):
            cnt += 1
    return cnt


def mark_notification_read(note_id, user_id):
    rows = _read_tab(NOTIFICATIONS_TAB)
    for n in rows:
        if n.get("id") == note_id:
            rb = n.get("read_by") or []
            if user_id not in rb:
                rb.append(user_id)
                n["read_by"] = rb
            _write_tab(NOTIFICATIONS_TAB, rows)
            return True
    return False


# ==================================================================
# DOCUMENTS  (approval + digital signing workflow)
# ==================================================================
DOCUMENTS_TAB = "documents"


def submit_document(payload):
    """payload = {title, doc_type, body, church_id, submitted_by,
                  submitted_by_name}"""
    if not (payload.get("title") or "").strip():
        return None
    rec = {
        "id": _new_id("D"),
        "title": payload.get("title", "").strip(),
        "doc_type": payload.get("doc_type", "request"),
        "body": payload.get("body", "").strip(),
        "church_id": payload.get("church_id", ""),
        "church_name": payload.get("church_name", ""),
        "submitted_by": payload.get("submitted_by", ""),
        "submitted_by_name": payload.get("submitted_by_name", ""),
        "status": "pending",
        "signed_by": "",
        "signed_by_name": "",
        "signed_at": "",
        "signature_hash": "",
        "feedback": "",
        "created_at": _now_iso(),
    }
    rows = _read_tab(DOCUMENTS_TAB)
    rows.append(rec)
    _write_tab(DOCUMENTS_TAB, rows)
    return rec


def list_documents(status=None, church_id=None, submitted_by=None):
    rows = _read_tab(DOCUMENTS_TAB)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if church_id:
        rows = [r for r in rows if r.get("church_id") == church_id]
    if submitted_by:
        rows = [r for r in rows if r.get("submitted_by") == submitted_by]
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return rows


def find_document(doc_id):
    rows = _read_tab(DOCUMENTS_TAB)
    return next((r for r in rows if r.get("id") == doc_id), None)


def delete_document(doc_id):
    """V1.21 — Hard-delete a single document."""
    rows = _read_tab(DOCUMENTS_TAB)
    keep = [r for r in rows if r.get("id") != doc_id]
    _write_tab(DOCUMENTS_TAB, keep)
    return len(rows) - len(keep) > 0


def clear_all_documents(church_id=None, status=None):
    """V1.21 — Delete all documents, optionally scoped."""
    rows = _read_tab(DOCUMENTS_TAB)
    def _match(r):
        if church_id and r.get("church_id") != church_id:
            return False
        if status and r.get("status") != status:
            return False
        return True
    keep = [r for r in rows if not _match(r)]
    removed = len(rows) - len(keep)
    _write_tab(DOCUMENTS_TAB, keep)
    return removed


def sign_document(doc_id, signer):
    """Mark a document as signed by the parish pastor."""
    rows = _read_tab(DOCUMENTS_TAB)
    for r in rows:
        if r.get("id") == doc_id:
            r["status"] = "signed"
            r["signed_by"] = signer.get("id", "")
            r["signed_by_name"] = signer.get("name", "")
            r["signed_at"] = _now_iso()
            import hashlib
            blob = f"{r['id']}|{r['signed_by']}|{r['signed_at']}|{r['title']}"
            r["signature_hash"] = hashlib.sha256(blob.encode()).hexdigest()[:24]
            _write_tab(DOCUMENTS_TAB, rows)
            return r
    return None


def reject_document(doc_id, signer, feedback=""):
    rows = _read_tab(DOCUMENTS_TAB)
    for r in rows:
        if r.get("id") == doc_id:
            r["status"] = "rejected"
            r["signed_by"] = signer.get("id", "")
            r["signed_by_name"] = signer.get("name", "")
            r["signed_at"] = _now_iso()
            r["feedback"] = feedback
            _write_tab(DOCUMENTS_TAB, rows)
            return r
    return None


# ==================================================================
# SERVICE / CERTIFICATE REQUESTS  (member reception approval flow)
# A category/ministry leader uploads a certificate + a message asking
# that a Christian be received; the church pastor approves → the
# Christian is automatically added to the church's members.
# ==================================================================
SERVICE_REQUESTS_TAB = "service_requests"


def submit_service_request(payload):
    """payload = {requester_id, requester_name, requester_role, church_id,
                  christian_name, christian_phone, request_type, message,
                  certificate_filename}"""
    if not (payload.get("christian_name") or "").strip():
        return None
    rec = {
        "id": _new_id("SR"),
        "requester_id": payload.get("requester_id", ""),
        "requester_name": payload.get("requester_name", ""),
        "requester_role": payload.get("requester_role", ""),
        "church_id": payload.get("church_id", ""),
        "church_name": payload.get("church_name", ""),
        "christian_name": payload["christian_name"].strip(),
        "christian_phone": (payload.get("christian_phone") or "").strip(),
        "christian_gender": (payload.get("christian_gender") or "").upper(),
        "request_type": (payload.get("request_type") or "NEW_MEMBER").upper(),
        "message": (payload.get("message") or "").strip(),
        "certificate_filename": payload.get("certificate_filename", ""),
        "attachments": payload.get("attachments", []),
        "assigned_to_role": payload.get("assigned_to_role", "MINISTRY_LEADER"),
        "escalated_to": "",
        "escalation_history": [],
        "status": "pending",
        "approved_by": "",
        "approved_by_name": "",
        "approved_at": "",
        "feedback": "",
        "created_member_id": "",
        "created_at": _now_iso(),
    }
    rows = _read_tab(SERVICE_REQUESTS_TAB)
    rows.append(rec)
    _write_tab(SERVICE_REQUESTS_TAB, rows)
    return rec


def list_service_requests(church_id=None, status=None, requester_id=None):
    rows = _read_tab(SERVICE_REQUESTS_TAB)
    if church_id:
        rows = [r for r in rows if r.get("church_id") == church_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if requester_id:
        rows = [r for r in rows if r.get("requester_id") == requester_id]
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return rows


def find_service_request(req_id):
    for r in _read_tab(SERVICE_REQUESTS_TAB):
        if r.get("id") == req_id:
            return r
    return None


def approve_service_request(req_id, approver):
    """Approve and auto-create the member from the request data."""
    rows = _read_tab(SERVICE_REQUESTS_TAB)
    for r in rows:
        if r.get("id") == req_id:
            r["status"] = "approved"
            r["approved_by"] = approver.get("id", "")
            r["approved_by_name"] = approver.get("name", "")
            r["approved_at"] = _now_iso()
            # Auto-create the member in this church.
            member = insert_member({
                "church_id": r.get("church_id", ""),
                "name": r.get("christian_name", ""),
                "gender": r.get("christian_gender", ""),
                "phone": r.get("christian_phone", ""),
                "category": "ABAKRISTO_BASHYA",
                "active": True,
            })
            r["created_member_id"] = member["id"] if member else ""
            _write_tab(SERVICE_REQUESTS_TAB, rows)
            return r
    return None


def reject_service_request(req_id, approver, feedback=""):
    rows = _read_tab(SERVICE_REQUESTS_TAB)
    for r in rows:
        if r.get("id") == req_id:
            r["status"] = "rejected"
            r["approved_by"] = approver.get("id", "")
            r["approved_by_name"] = approver.get("name", "")
            r["approved_at"] = _now_iso()
            r["feedback"] = feedback
            _write_tab(SERVICE_REQUESTS_TAB, rows)
            return r
    return None


def parish_override_reject_service_request(req_id, parish_user, reason=""):
    """V1.12 — Parish pastor (head of all) overrides a reception that a
    local church already approved. Sets status to 'parish_rejected',
    stamps the parish review, and DEACTIVATES the member that was auto-
    created on approval (so the person does not stay on the church roster
    against the parish's decision). Returns the updated record or None.

    Only an already-APPROVED request can be overridden (you cannot
    override a pending or already-rejected one — those are the church's
    to handle).
    """
    rows = _read_tab(SERVICE_REQUESTS_TAB)
    for r in rows:
        if r.get("id") != req_id:
            continue
        if r.get("status") != "approved":
            return None  # nothing to override
        r["status"] = "parish_rejected"
        r["parish_reviewed_by"] = parish_user.get("id", "")
        r["parish_reviewed_name"] = parish_user.get("name", "")
        r["parish_reviewed_at"] = _now_iso()
        r["parish_override_reason"] = (reason or "").strip()
        # Deactivate the member that approval auto-created.
        mid = r.get("created_member_id", "")
        if mid:
            update_member(mid, {"active": False, "parish_override": True})
        _write_tab(SERVICE_REQUESTS_TAB, rows)
        return r
    return None


# ==================================================================
# DEATH REPORTS  (mark a member deceased → removed from active
# roster → notification to parish)
# ==================================================================
DEATH_REPORTS_TAB = "death_reports"


def report_death(payload):
    """payload = {member_id, church_id, reported_by, reported_by_name,
                  death_date, notes}"""
    mid = payload.get("member_id")
    if not mid:
        return None
    member = find_member(mid)
    if not member:
        return None
    rec = {
        "id": _new_id("DR"),
        "member_id": mid,
        "member_name": member.get("name", ""),
        "church_id": payload.get("church_id", member.get("church_id", "")),
        "church_name": payload.get("church_name", ""),
        "category": member.get("category", ""),
        "reported_by": payload.get("reported_by", ""),
        "reported_by_name": payload.get("reported_by_name", ""),
        "death_date": payload.get("death_date", ""),
        "notes": (payload.get("notes") or "").strip(),
        "created_at": _now_iso(),
    }
    rows = _read_tab(DEATH_REPORTS_TAB)
    rows.append(rec)
    _write_tab(DEATH_REPORTS_TAB, rows)
    # Mark the member deceased + inactive so they leave the active roster.
    update_member(mid, {"active": False, "deceased": True,
                        "death_date": payload.get("death_date", "")})
    return rec


def list_death_reports(church_id=None):
    rows = _read_tab(DEATH_REPORTS_TAB)
    if church_id:
        rows = [r for r in rows if r.get("church_id") == church_id]
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return rows


# ==================================================================
# SCHEDULES  (a leader creates a time-scheduled event; feedback
# is collected in-system)
# ==================================================================
SCHEDULES_TAB = "schedules"
SCHEDULE_STATUSES = ["pending", "approved", "declined", "upcoming", "done", "cancelled"]


def create_schedule(payload):
    """payload = {title, description, scheduled_by, scheduled_by_name,
                  church_id, ministry_id, datetime, location}"""
    if not (payload.get("title") or "").strip() or not payload.get("datetime"):
        return None
    rec = {
        "id": _new_id("SC"),
        "title": payload["title"].strip(),
        "description": (payload.get("description") or "").strip(),
        "scheduled_by": payload.get("scheduled_by", ""),
        "scheduled_by_name": payload.get("scheduled_by_name", ""),
        "scheduled_by_role": payload.get("scheduled_by_role", ""),
        "church_id": payload.get("church_id", ""),
        "ministry_id": payload.get("ministry_id", ""),
        "datetime": payload["datetime"],
        "location": (payload.get("location") or "").strip(),
        "status": "upcoming",
        "feedback": [],
        "created_at": _now_iso(),
    }
    rows = _read_tab(SCHEDULES_TAB)
    rows.append(rec)
    _write_tab(SCHEDULES_TAB, rows)
    return rec


def list_schedules(church_id=None, ministry_id=None, status=None,
                   scheduled_by=None):
    rows = _read_tab(SCHEDULES_TAB)
    if church_id:
        rows = [r for r in rows if r.get("church_id") == church_id]
    if ministry_id:
        rows = [r for r in rows if r.get("ministry_id") == ministry_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if scheduled_by:
        rows = [r for r in rows if r.get("scheduled_by") == scheduled_by]
    rows.sort(key=lambda x: x.get("datetime", ""), reverse=False)
    return rows


def add_schedule_feedback(schedule_id, user, feedback_text):
    rows = _read_tab(SCHEDULES_TAB)
    for r in rows:
        if r.get("id") == schedule_id:
            fb = r.get("feedback") or []
            fb.append({
                "user_id": user.get("id", ""),
                "user_name": user.get("name", ""),
                "user_role": user.get("role", ""),
                "text": (feedback_text or "").strip(),
                "created_at": _now_iso(),
            })
            r["feedback"] = fb
            _write_tab(SCHEDULES_TAB, rows)
            return r
    return None


def update_schedule_status(schedule_id, status):
    rows = _read_tab(SCHEDULES_TAB)
    for r in rows:
        if r.get("id") == schedule_id:
            r["status"] = status
            _write_tab(SCHEDULES_TAB, rows)
            return r
    return None


def update_schedule(schedule_id, updates):
    """Patch a schedule's editable fields (title, description, datetime,
    location, ministry_id). Used by the V1.15 edit-own-schedule endpoint.
    Returns the updated record, or None if not found. Does NOT touch
    status/feedback/scheduled_by (those are managed by other paths)."""
    rows = _read_tab(SCHEDULES_TAB)
    for r in rows:
        if r.get("id") == schedule_id:
            for k in ("title", "description", "datetime", "location",
                      "ministry_id"):
                if k in updates:
                    val = updates[k]
                    if isinstance(val, str):
                        val = val.strip()
                    r[k] = val
            r["updated_at"] = _now_iso()
            _write_tab(SCHEDULES_TAB, rows)
            return r
    return None


def delete_schedule(schedule_id):
    """Remove a schedule by id. Returns True if removed, False if not
    found. Used by the V1.15 delete-own-schedule endpoint."""
    rows = _read_tab(SCHEDULES_TAB)
    before = len(rows)
    rows = [r for r in rows if r.get("id") != schedule_id]
    if len(rows) == before:
        return False
    _write_tab(SCHEDULES_TAB, rows)
    return True


def clear_all_schedules(church_id=None, scheduled_by=None):
    """V1.21 — Delete all schedules, optionally scoped."""
    rows = _read_tab(SCHEDULES_TAB)
    def _match(r):
        if church_id and r.get("church_id") != church_id:
            return False
        if scheduled_by and r.get("scheduled_by") != scheduled_by:
            return False
        return True
    keep = [r for r in rows if not _match(r)]
    removed = len(rows) - len(keep)
    _write_tab(SCHEDULES_TAB, keep)
    return removed


# ==================================================================
# SYSTEM RESET
# ==================================================================
RESET_TARGETS = {
    "churches": [CHURCHES_TAB],
    "members": [MEMBERS_TAB, MM_TAB],
    "ministries": [MINISTRIES_TAB, MM_TAB],
    "offerings": [OFFERINGS_TAB, ITEMS_TAB],
    "budgets": [CHURCH_BUDGETS_TAB],
    "notifications": [NOTIFICATIONS_TAB],
    "documents": [DOCUMENTS_TAB],
    "service_requests": [SERVICE_REQUESTS_TAB],
    "death_reports": [DEATH_REPORTS_TAB],
    "schedules": [SCHEDULES_TAB],
    "announcements": [ANN_TAB],
    "users": [USERS_TAB],
}


def reset_all_system(keep_admin_id=None, targets=None):
    if targets is None or "all" in targets:
        targets = list(RESET_TARGETS.keys())
    summary = {}
    for t in targets:
        for tab in RESET_TARGETS.get(t, []):
            if tab == USERS_TAB and keep_admin_id:
                keep = [r for r in _read_tab(tab) if r.get("id") == keep_admin_id
                        or r.get("role") == "PARISH_PASTOR"]
                _write_tab(tab, keep)
                summary[tab] = len(keep)
            else:
                _write_tab(tab, [])
                summary[tab] = 0
    _prewarm_cache()
    return {"targets": targets, "summary": summary}


def reset_members_by_category(category):
    """Remove only the members belonging to a given member-category
    (e.g. wipe all ABAKRISTO_BASHYA) and their ministry assignments."""
    cat = (category or "").upper()
    if not cat:
        return {"removed": 0, "category": ""}
    members = _read_tab(MEMBERS_TAB)
    keep = [m for m in members if (m.get("category") or "").upper() != cat]
    removed = len(members) - len(keep)
    _write_tab(MEMBERS_TAB, keep)
    keep_ids = {m["id"] for m in keep}
    mm = _read_tab(MM_TAB)
    mm_keep = [a for a in mm if a.get("member_id") in keep_ids]
    _write_tab(MM_TAB, mm_keep)
    return {"removed": removed, "category": cat}


def clear_all_members(church_id=None, category=None, zone_id=None):
    """Remove every member (optionally scoped to one church, one zone and/or
    one category) and their ministry assignments. Returns {"removed", "scope"}."""
    members = _read_tab(MEMBERS_TAB)
    def _match(m):
        if church_id and m.get("church_id") != church_id:
            return False
        if zone_id and (m.get("zone_id") or "") != zone_id:
            return False
        if category and (m.get("category") or "") != category:
            return False
        return True
    removed_ids = {m["id"] for m in members if _match(m)}
    keep = [m for m in members if m["id"] not in removed_ids]
    scope_parts = []
    if church_id: scope_parts.append("church:" + church_id)
    if zone_id: scope_parts.append("zone:" + zone_id)
    if category: scope_parts.append("cat:" + category)
    scope = "+".join(scope_parts) if scope_parts else "all"
    removed = len(members) - len(keep)
    _write_tab(MEMBERS_TAB, keep)
    # Cascade: drop ministry assignments for the removed members.
    mm = _read_tab(MM_TAB)
    _write_tab(MM_TAB, [a for a in mm if a.get("member_id") not in removed_ids])
    return {"removed": removed, "scope": scope}


def clear_all_churches():
    """Parish-only: remove every church, cascade-delete its members, and
    orphan/deactivate the church pastor + finance accounts that belonged
    to those churches. Returns {"removed": N, "members_removed": M}.
    """
    churches = _read_tab(CHURCHES_TAB)
    church_ids = {c["id"] for c in churches}
    n = len(churches)
    _write_tab(CHURCHES_TAB, [])
    # Cascade: drop members of every removed church.
    members = _read_tab(MEMBERS_TAB)
    members_keep = [m for m in members if m.get("church_id") not in church_ids]
    members_removed = len(members) - len(members_keep)
    _write_tab(MEMBERS_TAB, members_keep)
    # Cascade: drop ministry assignments for the removed members.
    keep_ids = {m["id"] for m in members_keep}
    mm = _read_tab(MM_TAB)
    _write_tab(MM_TAB, [a for a in mm if a.get("member_id") in keep_ids])
    # Cascade: orphan + deactivate church-scoped accounts (pastor/finance/leader/reader).
    users = _read_tab(USERS_TAB)
    for u in users:
        if u.get("church_id") in church_ids:
            u["church_id"] = ""
            u["active"] = False
    _write_tab(USERS_TAB, users)
    return {"removed": n, "members_removed": members_removed}


def clear_all_sent_messages(church_id=None):
    """Wipe the message queue (sent + pending + failed SMS/email rows).
    Optionally scoped to one church's messages. Also clears the bulk-send
    batch log and the thank-you SMS log for consistency. Returns a summary.
    """
    summary = {"queue_removed": 0, "bulk_removed": 0, "thank_you_removed": 0,
               "scope": "church:" + church_id if church_id else "all"}
    # Main message queue.
    q = _read_tab(MSG_QUEUE_TAB)
    if church_id:
        keep = [r for r in q if r.get("church_id") != church_id]
    else:
        keep = []
    summary["queue_removed"] = len(q) - len(keep)
    _write_tab(MSG_QUEUE_TAB, keep)
    # Bulk-send batch log.
    try:
        b = _read_tab("bulk_send_batches")
        if church_id:
            b_keep = [r for r in b if r.get("church_id") != church_id]
        else:
            b_keep = []
        summary["bulk_removed"] = len(b) - len(b_keep)
        _write_tab("bulk_send_batches", b_keep)
    except Exception:
        pass
    # Thank-you SMS log.
    try:
        t = _read_tab("thank_you_sms_log")
        if church_id:
            t_keep = [r for r in t if r.get("church_id") != church_id]
        else:
            t_keep = []
        summary["thank_you_removed"] = len(t) - len(t_keep)
        _write_tab("thank_you_sms_log", t_keep)
    except Exception:
        pass
    return summary


# ==================================================================
# AUTOMATION LAYER (V1.6)
# Message queue (send when online), email reports log, system settings,
# global smart search, and system health.
# ==================================================================
MSG_QUEUE_TAB = "message_queue"
EMAIL_LOG_TAB = "email_reports_log"
SETTINGS_FILE = "system_settings"

SETTINGS_DEFAULTS = {
    # SMTP (email) — leave host empty to disable real sending (dry-run mode)
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "",
    "smtp_use_tls": True,
    # Automation toggles
    "auto_process_queue": True,        # background: process queue every 2 min
    "auto_weekly_email": True,         # background: send weekly report per church
    "weekly_email_day": "mon",         # mon/tue/.../sun
    "weekly_email_hour": 8,            # 0-23
    "queue_max_retries": 5,            # give up after this many attempts
    # SMS gateway (mirrors sms.py env, kept here so the UI can show/edit)
    "sms_gateway_url": os.environ.get("SMS_GATEWAY_URL", "http://192.168.1.169:8082"),
    "sms_dry_run": True,
    # Last-known system events (updated by scheduler / health check)
    "last_queue_run": "",
    "last_email_run": "",
    "last_backup": "",
}


def load_system_settings():
    return _read_singleton(SETTINGS_FILE, SETTINGS_DEFAULTS)


def save_system_settings(updates):
    cur = load_system_settings()
    for k in SETTINGS_DEFAULTS:
        if k in updates:
            v = updates[k]
            if k in ("smtp_use_tls", "auto_process_queue",
                     "auto_weekly_email", "sms_dry_run"):
                cur[k] = _to_bool(v, SETTINGS_DEFAULTS[k])
            elif k == "weekly_email_hour":
                try:
                    cur[k] = int(v)
                except Exception:
                    cur[k] = SETTINGS_DEFAULTS[k]
            else:
                cur[k] = v
    _write_singleton(SETTINGS_FILE, cur)
    return cur


# ------------------------------------------------------------------
# MESSAGE QUEUE — messages that wait until a connection is available,
# then are sent automatically (SMS via the gateway, email via SMTP).
# ------------------------------------------------------------------
def enqueue_message(payload):
    """payload = {channel: 'sms'|'email', to, subject?, body,
                 church_id?, created_by, created_by_name}"""
    channel = (payload.get("channel") or "sms").lower()
    if channel not in ("sms", "email"):
        return None, "Channel yemewe: sms cyangwa email."
    to = (payload.get("to") or "").strip()
    body = (payload.get("body") or "").strip()
    if not to or not body:
        return None, "Uwo uhereza n'ubutumwa birakenewe."
    rec = {
        "id": _new_id("MQ"),
        "channel": channel,
        "to": to,
        "subject": (payload.get("subject") or "").strip(),
        "body": body,
        "church_id": payload.get("church_id", ""),
        "created_by": payload.get("created_by", ""),
        "created_by_name": payload.get("created_by_name", ""),
        "status": "pending",          # pending | sent | failed | skipped
        "attempts": 0,
        "last_error": "",
        "sent_at": "",
        "created_at": _now_iso(),
    }
    rows = _read_tab(MSG_QUEUE_TAB)
    rows.append(rec)
    _write_tab(MSG_QUEUE_TAB, rows)
    return rec, None


def list_message_queue(status=None, channel=None, limit=200):
    rows = _read_tab(MSG_QUEUE_TAB)
    out = []
    for r in rows:
        if status and r.get("status") != status:
            continue
        if channel and r.get("channel") != channel:
            continue
        out.append(dict(r))
    out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return out[:limit]


def pending_queue_messages():
    return list_message_queue(status="pending")


def mark_message_sent(msg_id, response=""):
    rows = _read_tab(MSG_QUEUE_TAB)
    for r in rows:
        if r.get("id") == msg_id:
            r["status"] = "sent"
            r["sent_at"] = _now_iso()
            r["attempts"] = int(r.get("attempts", 0)) + 1
            r["last_error"] = ""
            _write_tab(MSG_QUEUE_TAB, rows)
            return r
    return None


def mark_message_failed(msg_id, error, max_retries=5):
    rows = _read_tab(MSG_QUEUE_TAB)
    for r in rows:
        if r.get("id") == msg_id:
            r["attempts"] = int(r.get("attempts", 0)) + 1
            r["last_error"] = (error or "")[:200]
            if r["attempts"] >= max_retries:
                r["status"] = "failed"
            _write_tab(MSG_QUEUE_TAB, rows)
            return r
    return None


def queue_stats():
    rows = _read_tab(MSG_QUEUE_TAB)
    s = {"pending": 0, "sent": 0, "failed": 0, "total": len(rows)}
    for r in rows:
        st = r.get("status", "pending")
        if st in s:
            s[st] += 1
    return s


# ------------------------------------------------------------------
# EMAIL REPORTS LOG — record of automatic / manual email reports sent.
# ------------------------------------------------------------------
def log_email_report(payload):
    rec = {
        "id": _new_id("ER"),
        "church_id": payload.get("church_id", ""),
        "church_name": payload.get("church_name", ""),
        "recipient": payload.get("recipient", ""),
        "subject": payload.get("subject", ""),
        "period": payload.get("period", "weekly"),
        "status": payload.get("status", "sent"),   # sent | failed
        "error": payload.get("error", ""),
        "trigger": payload.get("trigger", "manual"),  # manual | auto
        "sent_at": _now_iso(),
    }
    rows = _read_tab(EMAIL_LOG_TAB)
    rows.append(rec)
    _write_tab(EMAIL_LOG_TAB, rows)
    return rec


def list_email_reports(limit=100):
    rows = _read_tab(EMAIL_LOG_TAB)
    out = [dict(r) for r in rows]
    out.sort(key=lambda x: x.get("sent_at", ""), reverse=True)
    return out[:limit]


# ------------------------------------------------------------------
# GLOBAL SMART SEARCH — search across the whole system in one call.
# ------------------------------------------------------------------
def search_all(query, user=None, limit=15):
    """Returns grouped results: {members, churches, schedules, offerings,
    service_requests, death_reports, users}. Each item carries enough to
    link the user to the right record (id + label + subtitle + page)."""
    q = (query or "").strip().lower()
    if not q or len(q) < 2:
        return {}

    def _match(*fields):
        for f in fields:
            if f and q in str(f).lower():
                return True
        return False

    # Restrict members by church for church / ministry roles.
    church_filter = None
    if user and user.get("role") in ("CHURCH_PASTOR", "CHURCH_FINANCE",
                                     "MINISTRY_LEADER"):
        church_filter = user.get("church_id", "")

    results = {}

    # Members
    members = _read_tab(MEMBERS_TAB)
    items = []
    for m in members:
        if church_filter and m.get("church_id") != church_filter:
            continue
        if _match(m.get("name"), m.get("phone"), m.get("id")):
            c = find_church(m.get("church_id", ""))
            items.append({
                "id": m.get("id", ""),
                "label": m.get("name", ""),
                "subtitle": ("Itorero: " + (c.get("name", "") if c else "—")
                             + " • " + (m.get("category", "") or "")
                             + " • " + (m.get("phone", "") or "—")),
                "page": "my_members",
            })
        if len(items) >= limit:
            break
    if items:
        results["members"] = items

    # Churches (parish-only)
    if not church_filter:
        items = []
        for c in _read_tab(CHURCHES_TAB):
            if _match(c.get("name"), c.get("pastor_name"),
                      c.get("phone"), c.get("id")):
                items.append({
                    "id": c.get("id", ""),
                    "label": c.get("name", ""),
                    "subtitle": ("Umushumba: " + (c.get("pastor_name", "") or "—")
                                 + " • " + (c.get("phone", "") or "—")),
                    "page": "churches",
                })
            if len(items) >= limit:
                break
        if items:
            results["churches"] = items

    # Schedules
    items = []
    for s in _read_tab(SCHEDULES_TAB):
        if church_filter and s.get("church_id") != church_filter:
            continue
        if _match(s.get("title"), s.get("description"), s.get("location")):
            items.append({
                "id": s.get("id", ""),
                "label": s.get("title", ""),
                "subtitle": (s.get("datetime", "")[:16] + " • "
                             + (s.get("location", "") or "—")
                             + " • " + (s.get("status", "") or "")),
                "page": "schedules",
            })
        if len(items) >= limit:
            break
    if items:
        results["schedules"] = items

    # Offerings
    items = []
    for o in _read_tab(OFFERINGS_TAB):
        if church_filter and o.get("church_id") != church_filter:
            continue
        if _match(o.get("church_name"), o.get("period"), o.get("id"),
                  o.get("date")):
            items.append({
                "id": o.get("id", ""),
                "label": (o.get("church_name", "") or "Itorero") + " — amaturo",
                "subtitle": (o.get("period", "") or o.get("date", "")
                             + " • " + str(o.get("igiteranyo", "")) + " RWF"),
                "page": "offerings",
            })
        if len(items) >= limit:
            break
    if items:
        results["offerings"] = items

    # Service requests
    items = []
    for sr in _read_tab(SERVICE_REQUESTS_TAB):
        if church_filter and sr.get("church_id") != church_filter:
            continue
        if _match(sr.get("christian_name"), sr.get("requester_name"),
                  sr.get("status")):
            items.append({
                "id": sr.get("id", ""),
                "label": sr.get("christian_name", "") or "Igisabye",
                "subtitle": (sr.get("status", "") + " • "
                             + (sr.get("request_type", "") or "")),
                "page": "service_requests",
            })
        if len(items) >= limit:
            break
    if items:
        results["service_requests"] = items

    # Users (parish-only, for admin lookup)
    if not church_filter:
        items = []
        for u in _read_tab(USERS_TAB):
            if _user_status(u) == "rejected":
                continue
            if _match(u.get("name"), u.get("username"), u.get("email"),
                      u.get("phone")):
                items.append({
                    "id": u.get("id", ""),
                    "label": u.get("name", ""),
                    "subtitle": (u.get("username", "") + " • "
                                 + u.get("role", "") + " • "
                                 + _user_status(u)),
                    "page": "users" if False else "pending_users",
                })
            if len(items) >= limit:
                break
        if items:
            results["users"] = items

    # Zones (visible to church+ roles; restricted by church above the
    # church_filter set earlier)
    items = []
    for z in _read_tab(ZONES_TAB):
        if church_filter and z.get("church_id") != church_filter:
            continue
        if _match(z.get("name"), z.get("reader_name"), z.get("description")):
            c = find_church(z.get("church_id", ""))
            items.append({
                "id": z.get("id", ""),
                "label": z.get("name", ""),
                "subtitle": ("Itorero: " + (c.get("name", "") if c else "—")
                             + " • Umuyobozi: " + (z.get("reader_name", "") or "—")),
                "page": "zones",
            })
        if len(items) >= limit:
            break
    if items:
        results["zones"] = items

    # Assets (parish + church see them; church-filter applied)
    if not church_filter or True:
        items = []
        for a in _read_tab(ASSETS_TAB):
            if church_filter and a.get("church_id") != church_filter:
                continue
            if _match(a.get("name"), a.get("description"), a.get("category")):
                c = find_church(a.get("church_id", ""))
                items.append({
                    "id": a.get("id", ""),
                    "label": a.get("name", ""),
                    "subtitle": (a.get("category", "") + " • "
                                 + str(a.get("value", 0)) + " RWF • "
                                 + (c.get("name", "") if c else "—")),
                    "page": "assets",
                })
            if len(items) >= limit:
                break
        if items:
            results["assets"] = items

    return results


# ------------------------------------------------------------------
# SYSTEM HEALTH — the monitoring snapshot shown on the dashboard.
# ------------------------------------------------------------------
def system_health():
    """One-shot snapshot of every subsystem for the monitoring panel."""
    settings = load_system_settings()
    qs = queue_stats()
    # File-store sanity: count rows in the core tables.
    counts = {
        "churches": len(_read_tab(CHURCHES_TAB)),
        "members": len(_read_tab(MEMBERS_TAB)),
        "offerings": len(_read_tab(OFFERINGS_TAB)),
        "schedules": len(_read_tab(SCHEDULES_TAB)),
        "notifications": len(_read_tab(NOTIFICATIONS_TAB)),
        "queue": len(_read_tab(MSG_QUEUE_TAB)),
    }
    # SMTP configured? (host non-empty)
    smtp_ok = bool((settings.get("smtp_host") or "").strip())
    # SMS gateway: assume ok unless explicitly told offline
    sms_ok = bool((settings.get("sms_gateway_url") or "").strip())
    now = _now_iso()
    return {
        "ts": now,
        "db": "ok",
        "counts": counts,
        "queue": qs,
        "smtp_configured": smtp_ok,
        "sms_configured": sms_ok,
        "scheduler_running": _scheduler_state.get("running", False),
        "last_queue_run": settings.get("last_queue_run", ""),
        "last_email_run": settings.get("last_email_run", ""),
        "last_backup": settings.get("last_backup", ""),
        "auto_process_queue": settings.get("auto_process_queue", True),
        "auto_weekly_email": settings.get("auto_weekly_email", True),
    }


# Lightweight in-process flag so the health endpoint can report whether
# the background scheduler thread is alive.
_scheduler_state = {"running": False, "started_at": ""}


# ==================================================================
# V1.7 EXPANSION — zones, church assets, activity log (bottom-up
# monitoring), service-request attachments + escalation chain, and the
# two new roles (ZONE_READER, PARISH_MANAGER).
# ==================================================================
ZONES_TAB = "zones"
ASSETS_TAB = "assets"
ACTIVITY_TAB = "activity_log"

ZONE_READER = "ZONE_READER"
PARISH_MANAGER = "PARISH_MANAGER"

ASSET_CATEGORIES = [
    "AMATWARA",          # vehicles
    "INZUBA_N_AMASHANYARAZI",  # sound + electricity equipment
    "IBINTU_BYO_GUSAMBA",  # furniture
    "AMAHOTELI_N_IMIBUGA",  # buildings + land
    "IBIKORESHO_BYA_TIYOLOGI",  # tech equipment
    "IBINDI",            # other
]

ASSET_DECISIONS = ["APPROVED", "REVIEW", "ACTION_NEEDED", "REJECTED"]


# ------------------------------------------------------------------
# ZONES — geographic / ministry subdivisions below the ministry leader.
# A ZONE_READER owns a zone and adds its members. Everything that
# happens in a zone flows up: zone → ministry → church → parish.
# ------------------------------------------------------------------
def list_zones(church_id=None, reader_id=None):
    rows = _read_tab(ZONES_TAB)
    out = []
    for z in rows:
        if church_id and z.get("church_id") != church_id:
            continue
        if reader_id and z.get("reader_id") != reader_id:
            continue
        z = dict(z)
        z["member_count"] = len([m for m in _read_tab(MEMBERS_TAB)
                                 if m.get("zone_id") == z.get("id")])
        out.append(z)
    return out


def find_zone(zone_id):
    """Return one zone record by id, or None."""
    if not zone_id:
        return None
    for z in _read_tab(ZONES_TAB):
        if z.get("id") == zone_id:
            return z
    return None


def create_zone(payload):
    if not payload.get("name") or not payload.get("church_id"):
        return None
    rec = {
        "id": _new_id("Z"),
        "church_id": payload["church_id"],
        "name": (payload.get("name") or "").strip(),
        "reader_id": payload.get("reader_id", ""),
        "reader_name": payload.get("reader_name", ""),
        "description": payload.get("description", ""),
        "created_at": _now_iso(),
    }
    rows = _read_tab(ZONES_TAB)
    rows.append(rec)
    _write_tab(ZONES_TAB, rows)
    return rec


def delete_zone(zone_id):
    rows = _read_tab(ZONES_TAB)
    keep = [z for z in rows if z.get("id") != zone_id]
    _write_tab(ZONES_TAB, keep)
    # Unassign members of this zone
    members = _read_tab(MEMBERS_TAB)
    for m in members:
        if m.get("zone_id") == zone_id:
            m["zone_id"] = ""
    _write_tab(MEMBERS_TAB, members)
    return {"removed": len(rows) - len(keep)}


# ------------------------------------------------------------------
# CHURCH ASSETS (imitungi y'itorero) — every church finance leader /
# pastor registers what the church owns, with its value. The parish
# pastor sees ALL assets across the parish, grouped by category, with
# the total value — and can record a decision that notifies the church.
# ------------------------------------------------------------------
def list_assets(church_id=None, category=None):
    rows = _read_tab(ASSETS_TAB)
    out = []
    for a in rows:
        if church_id and a.get("church_id") != church_id:
            continue
        if category and a.get("category") != category:
            continue
        a = dict(a)
        c = find_church(a.get("church_id", ""))
        a["church_name"] = c.get("name", "") if c else ""
        out.append(a)
    out.sort(key=lambda x: x.get("acquired_date", ""), reverse=True)
    return out


def insert_asset(payload):
    if not payload.get("name") or not payload.get("church_id"):
        return None
    rec = {
        "id": _new_id("A"),
        "church_id": payload["church_id"],
        "name": (payload.get("name") or "").strip(),
        "category": (payload.get("category") or "IBINDI").upper(),
        "value": _to_int(payload.get("value", 0)),
        "quantity": _to_int(payload.get("quantity", 1)),
        "description": payload.get("description", ""),
        "acquired_date": payload.get("acquired_date", ""),
        "doc_paths": payload.get("doc_paths", []),
        "status": payload.get("status", "ACTIVE"),  # ACTIVE | SOLD | DAMAGED
        "decision": "",          # parish pastor decision
        "decision_note": "",
        "decided_by": "",
        "decided_at": "",
        "created_by": payload.get("created_by", ""),
        "created_by_name": payload.get("created_by_name", ""),
        "created_at": _now_iso(),
    }
    rows = _read_tab(ASSETS_TAB)
    rows.append(rec)
    _write_tab(ASSETS_TAB, rows)
    return rec


def update_asset(asset_id, updates):
    rows = _read_tab(ASSETS_TAB)
    for a in rows:
        if a.get("id") == asset_id:
            for k in ("name", "category", "value", "quantity", "description",
                      "acquired_date", "status", "doc_paths"):
                if k in updates:
                    if k in ("value", "quantity"):
                        a[k] = _to_int(updates[k])
                    elif k == "doc_paths":
                        a[k] = updates[k] if isinstance(updates[k], list) else []
                    else:
                        a[k] = updates[k]
            _write_tab(ASSETS_TAB, rows)
            return a
    return None


def delete_asset(asset_id):
    rows = _read_tab(ASSETS_TAB)
    keep = [a for a in rows if a.get("id") != asset_id]
    _write_tab(ASSETS_TAB, keep)
    return {"removed": len(rows) - len(keep)}


def clear_all_assets(church_id=None):
    """V1.21 — Delete all assets, optionally scoped to one church."""
    rows = _read_tab(ASSETS_TAB)
    if church_id:
        keep = [a for a in rows if a.get("church_id") != church_id]
    else:
        keep = []
    removed = len(rows) - len(keep)
    _write_tab(ASSETS_TAB, keep)
    return removed


def asset_decision(asset_id, decision, note, decided_by, decided_by_name):
    """Parish pastor records a decision on an asset (APPROVED /
    REVIEW / ACTION_NEEDED / REJECTED). Logs a notification to the church
    and an activity-log entry so the chain is visible bottom-up."""
    rows = _read_tab(ASSETS_TAB)
    asset = None
    for a in rows:
        if a.get("id") == asset_id:
            a["decision"] = decision.upper()
            a["decision_note"] = (note or "")[:500]
            a["decided_by"] = decided_by
            a["decided_by_name"] = decided_by_name
            a["decided_at"] = _now_iso()
            asset = a
            break
    if asset:
        _write_tab(ASSETS_TAB, rows)
        # Notify the church leaders (use send_notification so the body /
        # read_by / recipient targeting is correct and the bell shows it).
        church = find_church(asset.get("church_id", ""))
        church_name = church.get("name", "") if church else "Itorero"
        msg = (f"Umwanzuro kuri '{asset.get('name','')}': {decision}. "
               + (note or ""))
        send_notification({
            "sender_id": decided_by,
            "sender_name": decided_by_name,
            "sender_role": "PARISH_PASTOR",
            "recipient_role": "ALL_CHURCH",
            "church_id": asset.get("church_id", ""),
            "title": f"Umwanzuro ku mutungo — {church_name}",
            "body": msg,
            "category": "ASSET_DECISION",
        })
        log_activity({
            "actor_id": decided_by, "actor_name": decided_by_name,
            "actor_role": "PARISH_PASTOR",
            "church_id": asset.get("church_id", ""),
            "action": "ASSET_DECISION",
            "target": asset.get("name", ""),
            "detail": f"{decision} — {note or ''}",
            "scope": "parish_to_church",
        })
    return asset


def asset_value_summary():
    """Parish-wide asset summary: total value + by-church + by-category."""
    rows = _read_tab(ASSETS_TAB)
    by_church = {}
    by_category = {}
    total = 0
    for a in rows:
        val = _to_int(a.get("value", 0)) * _to_int(a.get("quantity", 1))
        total += val
        cid = a.get("church_id", "")
        c = find_church(cid)
        cname = c.get("name", cid) if c else cid
        by_church.setdefault(cname, {"value": 0, "count": 0})
        by_church[cname]["value"] += val
        by_church[cname]["count"] += 1
        cat = a.get("category", "IBINDI")
        by_category.setdefault(cat, {"value": 0, "count": 0})
        by_category[cat]["value"] += val
        by_category[cat]["count"] += 1
    return {"total_value": total, "total_items": len(rows),
            "by_church": by_church, "by_category": by_category}


# ------------------------------------------------------------------
# ACTIVITY LOG — the bottom-up monitoring feed. Every meaningful action
# (member added, offering entered, service request submitted/escalated,
# asset added, decision taken) is recorded here with its scope so the
# parish pastor + parish manager can see the whole parish's pulse.
# ------------------------------------------------------------------
def log_activity(payload):
    rec = {
        "id": _new_id("ACT"),
        "actor_id": payload.get("actor_id", ""),
        "actor_name": payload.get("actor_name", ""),
        "actor_role": payload.get("actor_role", ""),
        "church_id": payload.get("church_id", ""),
        "zone_id": payload.get("zone_id", ""),
        "action": payload.get("action", ""),       # MEMBER_ADDED, etc.
        "target": payload.get("target", ""),
        "detail": payload.get("detail", ""),
        "scope": payload.get("scope", "church"),   # zone/ministry/church/parish/parish_to_church
        "ts": _now_iso(),
    }
    rows = _read_tab(ACTIVITY_TAB)
    rows.append(rec)
    # Keep the log bounded
    if len(rows) > 2000:
        rows = rows[-1500:]
    _write_tab(ACTIVITY_TAB, rows)
    return rec


def list_activity(church_id=None, zone_id=None, scope=None, limit=200,
                 actions=None):
    rows = _read_tab(ACTIVITY_TAB)
    out = []
    for r in rows:
        if church_id and r.get("church_id") != church_id:
            continue
        if zone_id and r.get("zone_id") != zone_id:
            continue
        if scope and r.get("scope") != scope:
            continue
        if actions and r.get("action") not in actions:
            continue
        out.append(dict(r))
    out.sort(key=lambda x: x.get("ts", ""), reverse=True)
    return out[:limit]


# ------------------------------------------------------------------
# SERVICE REQUESTS — V1.7 enhancements: file attachments + an
# escalation chain (zone → ministry → church → parish). A request can
# be escalated upward when the lower level cannot handle it.
# ------------------------------------------------------------------
ESCALATION_CHAIN = ["ZONE_READER", "MINISTRY_LEADER",
                    "CHURCH_PASTOR", "PARISH_PASTOR"]


def add_request_attachments(req_id, doc_paths):
    rows = _read_tab(SERVICE_REQUESTS_TAB)
    for r in rows:
        if r.get("id") == req_id:
            existing = r.get("attachments", [])
            if not isinstance(existing, list):
                existing = []
            r["attachments"] = existing + (doc_paths or [])
            _write_tab(SERVICE_REQUESTS_TAB, rows)
            return r
    return None


def escalate_service_request(req_id, by_user, by_name, by_role, note=""):
    """Move the request one step up the chain and log the escalation."""
    rows = _read_tab(SERVICE_REQUESTS_TAB)
    req = None
    for r in rows:
        if r.get("id") == req_id:
            cur = r.get("assigned_to_role") or r.get("requester_role", "ZONE_READER")
            try:
                idx = ESCALATION_CHAIN.index(cur)
            except ValueError:
                idx = 0
            nxt = ESCALATION_CHAIN[min(idx + 1, len(ESCALATION_CHAIN) - 1)]
            r["assigned_to_role"] = nxt
            r["escalated_to"] = nxt
            history = r.get("escalation_history", [])
            if not isinstance(history, list):
                history = []
            history.append({"from": cur, "to": nxt, "by": by_name,
                            "by_role": by_role, "note": note,
                            "ts": _now_iso()})
            r["escalation_history"] = history
            r["status"] = "escalated"
            req = r
            break
    if req:
        _write_tab(SERVICE_REQUESTS_TAB, rows)
        log_activity({
            "actor_id": by_user, "actor_name": by_name, "actor_role": by_role,
            "church_id": req.get("church_id", ""),
            "action": "SERVICE_ESCALATED",
            "target": req.get("christian_name", ""),
            "detail": f"{cur} → {nxt}: {note}",
            "scope": "parish" if nxt == "PARISH_PASTOR" else "church",
        })
    return req


def _to_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ==================================================================
# V1.8 EXPANSION — visitors report, member discipline + suspension,
# parish pastor delegation, parish-wide members-by-category +
# ministries aggregators, free-text church creation helper.
# ==================================================================
VISITORS_TAB = "visitors"
DISCIPLINE_TAB = "discipline"
DELEGATIONS_TAB = "delegations"

MARITAL_STATUSES = ["SINGLE", "MARRIED", "WIDOWED", "DIVORCED", "SEPARATED"]
EDUCATION_LEVELS = ["PRIMARY", "SECONDARY", "ADVANCED", "UNIVERSITY",
                     "MASTERS", "PHD", "NONE"]


# ------------------------------------------------------------------
# CHURCHES — free-text creation helper so users can register against
# a church that does not yet exist in the dropdown (modular).
# ------------------------------------------------------------------
def find_or_create_church(name, parish=""):
    name = (name or "").strip()
    if not name:
        return None
    for c in _read_tab(CHURCHES_TAB):
        if (c.get("name") or "").strip().lower() == name.lower():
            return c
    rec = {
        "id": _new_id("C"),
        "name": name,
        "parish": parish or "ADEPR",
        "leader_name": "",
        "leader_phone": "",
        "leader_email": "",
        "location": "",
        "active": True,
        "created_at": _now_iso(),
    }
    rows = _read_tab(CHURCHES_TAB)
    rows.append(rec)
    _write_tab(CHURCHES_TAB, rows)
    return rec


def search_churches(query, limit=10):
    """Fuzzy lookup used by the free-text church picker on any form."""
    q = (query or "").strip().lower()
    if not q:
        return []
    out = []
    for c in _read_tab(CHURCHES_TAB):
        if q in (c.get("name") or "").lower() or \
           q in (c.get("location") or "").lower():
            out.append(c)
            if len(out) >= limit:
                break
    return out


# ------------------------------------------------------------------
# VISITORS — umushyitsi waje ku cyumweru. Church pastor enters the
# visitor's photo, certificate, name, phone, the goal/lesson they
# were taught. Everything reaches the parish (whole parish view).
# ------------------------------------------------------------------
def list_visitors(church_id=None, week_date=None):
    rows = _read_tab(VISITORS_TAB)
    out = []
    for v in rows:
        if church_id and v.get("church_id") != church_id:
            continue
        if week_date and v.get("week_date") != week_date:
            continue
        v = dict(v)
        c = find_church(v.get("church_id", ""))
        v["church_name"] = c.get("name", "") if c else ""
        out.append(v)
    out.sort(key=lambda x: x.get("week_date", ""), reverse=True)
    return out


def insert_visitor(payload):
    if not payload.get("name") or not payload.get("church_id"):
        return None
    rec = {
        "id": _new_id("V"),
        "church_id": payload["church_id"],
        "name": (payload.get("name") or "").strip(),
        "phone": (payload.get("phone") or "").strip(),
        "gender": (payload.get("gender") or "").upper(),
        "week_date": payload.get("week_date", ""),
        "goal_taught": payload.get("goal_taught", ""),
        "address": payload.get("address", ""),
        "photo": payload.get("photo", ""),
        "certificate": payload.get("certificate", ""),
        "notes": payload.get("notes", ""),
        "status": payload.get("status", "VISITED"),  # VISITED|FOLLOWUP|JOINED
        "entered_by": payload.get("entered_by", ""),
        "entered_by_name": payload.get("entered_by_name", ""),
        "created_at": _now_iso(),
    }
    rows = _read_tab(VISITORS_TAB)
    rows.append(rec)
    _write_tab(VISITORS_TAB, rows)
    log_activity({
        "actor_id": payload.get("entered_by", ""),
        "actor_name": payload.get("entered_by_name", ""),
        "actor_role": payload.get("actor_role", "CHURCH_PASTOR"),
        "church_id": payload.get("church_id", ""),
        "action": "VISITOR_RECORDED",
        "target": rec["name"],
        "detail": f"Umushyitsi wa {rec.get('week_date','—')}",
        "scope": "church",
    })
    return rec


def update_visitor(vid, updates):
    rows = _read_tab(VISITORS_TAB)
    for v in rows:
        if v.get("id") == vid:
            for k in ("name", "phone", "gender", "week_date", "goal_taught",
                      "address", "photo", "certificate", "notes", "status"):
                if k in updates:
                    v[k] = updates[k]
            _write_tab(VISITORS_TAB, rows)
            return v
    return None


def delete_visitor(vid):
    rows = _read_tab(VISITORS_TAB)
    keep = [v for v in rows if v.get("id") != vid]
    _write_tab(VISITORS_TAB, keep)
    return {"removed": len(rows) - len(keep)}


# ------------------------------------------------------------------
# DISCIPLINE — church pastor / ministry leader can discipline a
# member or leader, but the action escalates UP and is recorded.
# Only the parish pastor can confirm; the suspended member's
# record shows the reason. Logs + notification.
# ------------------------------------------------------------------
DISCIPLINE_TYPES = ["WARNING", "SUSPENSION", "EXCOMMUNICATION", "RESTORATION"]
DISCIPLINE_STATUSES = ["PENDING", "CONFIRMED", "LIFTED"]


def list_discipline(church_id=None, status=None):
    rows = _read_tab(DISCIPLINE_TAB)
    out = []
    for d in rows:
        if church_id and d.get("church_id") != church_id:
            continue
        if status and d.get("status") != status:
            continue
        d = dict(d)
        m = find_member(d.get("member_id", ""))
        d["member_name"] = m.get("name", "") if m else d.get("member_name", "")
        c = find_church(d.get("church_id", ""))
        d["church_name"] = c.get("name", "") if c else ""
        out.append(d)
    out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return out


def insert_discipline(payload):
    # Allow raising by name even if the member is not yet registered, so a
    # pastor can discipline a visitor or a person not yet in the system.
    if not payload.get("church_id"):
        return None
    if not payload.get("member_id") and not payload.get("member_name"):
        return None
    rec = {
        "id": _new_id("D"),
        "member_id": payload["member_id"],
        "member_name": payload.get("member_name", ""),
        "church_id": payload["church_id"],
        "discipline_type": (payload.get("discipline_type") or "WARNING").upper(),
        "reason": (payload.get("reason") or "").strip(),
        "action_taken": (payload.get("action_taken") or "").strip(),
        "certificate": payload.get("certificate", ""),
        "status": "PENDING",   # parish pastor confirms
        "raised_by": payload.get("raised_by", ""),
        "raised_by_name": payload.get("raised_by_name", ""),
        "raised_by_role": payload.get("raised_by_role", ""),
        "confirmed_by": "",
        "confirmed_by_name": "",
        "confirmed_at": "",
        "confirmation_note": "",
        "lifted_at": "",
        "created_at": _now_iso(),
    }
    rows = _read_tab(DISCIPLINE_TAB)
    rows.append(rec)
    _write_tab(DISCIPLINE_TAB, rows)
    # Notify parish pastor + log
    send_notification({
        "sender_id": payload.get("raised_by", ""),
        "sender_name": payload.get("raised_by_name", ""),
        "sender_role": payload.get("raised_by_role", ""),
        "recipient_role": "PARISH_PASTOR",
        "church_id": payload["church_id"],
        "title": f"Kubitanya imana — {rec.get('member_name','')}",
        "body": f"{rec['discipline_type']}: {rec['reason']}",
        "category": "discipline",
    })
    log_activity({
        "actor_id": payload.get("raised_by", ""),
        "actor_name": payload.get("raised_by_name", ""),
        "actor_role": payload.get("raised_by_role", ""),
        "church_id": payload["church_id"],
        "action": "DISCIPLINE_RAISED",
        "target": rec.get("member_name", ""),
        "detail": f"{rec['discipline_type']} — {rec['reason'][:60]}",
        "scope": "church",
    })
    return rec


def confirm_discipline(did, confirmer, note=""):
    """Parish pastor confirms a discipline record (status → CONFIRMED)."""
    rows = _read_tab(DISCIPLINE_TAB)
    rec = None
    for d in rows:
        if d.get("id") == did:
            d["status"] = "CONFIRMED"
            d["confirmed_by"] = confirmer.get("id", "")
            d["confirmed_by_name"] = confirmer.get("name", "")
            d["confirmed_at"] = _now_iso()
            d["confirmation_note"] = (note or "")[:500]
            rec = d
            break
    if rec:
        _write_tab(DISCIPLINE_TAB, rows)
        send_notification({
            "sender_id": confirmer.get("id", ""),
            "sender_name": confirmer.get("name", ""),
            "sender_role": "PARISH_PASTOR",
            "recipient_role": "ALL_CHURCH",
            "church_id": rec.get("church_id", ""),
            "title": f"Kubitanya imana cyemejwe — {rec.get('member_name','')}",
            "body": f"{rec['discipline_type']} byemejwe na paruwasi. {note}",
            "category": "discipline",
        })
        log_activity({
            "actor_id": confirmer.get("id", ""),
            "actor_name": confirmer.get("name", ""),
            "actor_role": "PARISH_PASTOR",
            "church_id": rec.get("church_id", ""),
            "action": "DISCIPLINE_CONFIRMED",
            "target": rec.get("member_name", ""),
            "detail": rec.get("discipline_type", ""),
            "scope": "parish_to_church",
        })
    return rec


def lift_discipline(did, lifter, note=""):
    """Parish pastor lifts a suspension / restores a member."""
    rows = _read_tab(DISCIPLINE_TAB)
    rec = None
    for d in rows:
        if d.get("id") == did:
            d["status"] = "LIFTED"
            d["lifted_at"] = _now_iso()
            d["confirmation_note"] = (note or d.get("confirmation_note", ""))[:500]
            rec = d
            break
    if rec:
        _write_tab(DISCIPLINE_TAB, rows)
        log_activity({
            "actor_id": lifter.get("id", ""),
            "actor_name": lifter.get("name", ""),
            "actor_role": lifter.get("role", "PARISH_PASTOR"),
            "church_id": rec.get("church_id", ""),
            "action": "DISCIPLINE_LIFTED",
            "target": rec.get("member_name", ""),
            "detail": note,
            "scope": "parish_to_church",
        })
    return rec


# ------------------------------------------------------------------
# DELEGATIONS — parish pastor temporarily hands a feature / duty to
# someone (by name) for a given period, with a reason. The delegated
# feature appears in the receiver's menu while the delegation is active.
# ------------------------------------------------------------------
def list_delegations(active_only=False):
    rows = _read_tab(DELEGATIONS_TAB)
    out = []
    now = _now_iso()[:10]
    for d in rows:
        if active_only:
            if d.get("status") != "ACTIVE":
                continue
            end = (d.get("end_date") or "9999")[:10]
            if end < now:
                continue
        d = dict(d)
        c = find_church(d.get("church_id", ""))
        d["church_name"] = c.get("name", "") if c else ""
        out.append(d)
    out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return out


def insert_delegation(payload):
    if not payload.get("delegate_name") or not payload.get("feature"):
        return None
    rec = {
        "id": _new_id("DLG"),
        "delegate_name": payload["delegate_name"],
        "delegate_role": payload.get("delegate_role", ""),
        "delegate_user_id": payload.get("delegate_user_id", ""),
        "church_id": payload.get("church_id", ""),
        "feature": payload["feature"],   # e.g. "members", "offering", "assets"
        "reason": payload.get("reason", ""),
        "start_date": payload.get("start_date", _now_iso()[:10]),
        "end_date": payload.get("end_date", ""),
        "status": "ACTIVE",
        "delegated_by": payload.get("delegated_by", ""),
        "delegated_by_name": payload.get("delegated_by_name", ""),
        "created_at": _now_iso(),
    }
    rows = _read_tab(DELEGATIONS_TAB)
    rows.append(rec)
    _write_tab(DELEGATIONS_TAB, rows)
    log_activity({
        "actor_id": payload.get("delegated_by", ""),
        "actor_name": payload.get("delegated_by_name", ""),
        "actor_role": "PARISH_PASTOR",
        "church_id": payload.get("church_id", ""),
        "action": "DELEGATION_GRANTED",
        "target": payload["delegate_name"],
        "detail": f"{payload['feature']} ({payload.get('start_date','')} → {payload.get('end_date','—')})",
        "scope": "parish",
    })
    return rec


def revoke_delegation(dlg_id, revoker):
    rows = _read_tab(DELEGATIONS_TAB)
    rec = None
    for d in rows:
        if d.get("id") == dlg_id:
            d["status"] = "REVOKED"
            rec = d
            break
    if rec:
        _write_tab(DELEGATIONS_TAB, rows)
        log_activity({
            "actor_id": revoker.get("id", ""),
            "actor_name": revoker.get("name", ""),
            "actor_role": "PARISH_PASTOR",
            "church_id": rec.get("church_id", ""),
            "action": "DELEGATION_REVOKED",
            "target": rec.get("delegate_name", ""),
            "detail": rec.get("feature", ""),
            "scope": "parish",
        })
    return rec


# ------------------------------------------------------------------
# PARISH AGGREGATORS — the parish pastor dashboard now shows, across
# ALL churches, members grouped by category, plus every ministry with
# its report. Bottom-up visibility in one place.
# ------------------------------------------------------------------
def parish_members_by_category():
    """Across the whole parish, count members per category per church."""
    churches = _read_tab(CHURCHES_TAB)
    members = _read_tab(MEMBERS_TAB)
    by_church = {}
    totals = {c: 0 for c in MEMBER_CATEGORIES}
    for m in members:
        if m.get("deceased"):
            continue
        cid = m.get("church_id", "")
        c = find_church(cid)
        cname = c.get("name", cid) if c else cid
        cat = m.get("category", "ABAKRISTO_BOSE")
        by_church.setdefault(cname, {c: 0 for c in MEMBER_CATEGORIES})
        by_church[cname][cat] = by_church[cname].get(cat, 0) + 1
        totals[cat] = totals.get(cat, 0) + 1
    return {"by_church": by_church, "totals": totals,
            "grand_total": sum(totals.values())}


def parish_ministries_report():
    """Every ministry across all churches with its member count + leader."""
    ministries = _read_tab(MINISTRIES_TAB)
    members = _read_tab(MEMBERS_TAB)
    out = []
    for mn in ministries:
        c = find_church(mn.get("church_id", ""))
        count = len([m for m in members
                     if m.get("ministry_id") == mn.get("id")
                     and not m.get("deceased")])
        out.append({
            "id": mn.get("id", ""),
            "name": mn.get("name", ""),
            "church_name": c.get("name", "") if c else "",
            "church_id": mn.get("church_id", ""),
            "leader": mn.get("leader_name", ""),
            "member_count": count,
            "description": mn.get("description", ""),
        })
    out.sort(key=lambda x: x.get("church_name", ""))
    return out


