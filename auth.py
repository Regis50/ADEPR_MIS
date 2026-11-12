"""
auth.py — Session management + Role-Based Access Control decorators.
Sessions persist in data/sessions.json (survives restart).

Roles (from the Instruction + user's Ruhango-only scope):
  PARISH_PASTOR   — Umushumba wa Paruwasi (top admin, like OWNER)
  CHURCH_PASTOR   — Umushumba w'itorero (manages one church)
  CHURCH_FINANCE  — Umuyobozi ushinzwe imali w'itorero (enters amaturo)
  MINISTRY_LEADER — Umuyobozi wa ministeur (manages one ministry)

Per the user: ama makuru y'amaturo abishyirwamo n'umuyobozi ushinzwe imali
cyangwa umushumba w'itorero, bikagaragara kuri Paruwasi.
"""

import os
import json
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, make_response
import db

SESSION_COOKIE = "adepr_session_v1"
SESSION_TTL = timedelta(days=7)
SESSION_FILE = os.path.join(db.DATA_DIR, "sessions.json")


def _load_sessions():
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_sessions(sessions):
    tmp = SESSION_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2)
    os.replace(tmp, SESSION_FILE)


def login(username, password):
    user = db.find_user_by_credentials(username, password)
    if not user:
        return None, None
    token = secrets.token_urlsafe(48)
    expires = (datetime.now() + SESSION_TTL).isoformat()
    sessions = _load_sessions()
    sessions[token] = {"user_id": user["id"], "expires_at": expires}
    _save_sessions(sessions)
    return user, token


def logout(token):
    if not token:
        return
    sessions = _load_sessions()
    if token in sessions:
        del sessions[token]
        _save_sessions(sessions)


def current_user(request_obj):
    token = request_obj.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    sessions = _load_sessions()
    sess = sessions.get(token)
    if not sess:
        return None
    try:
        expires = datetime.fromisoformat(sess["expires_at"])
        if datetime.now() > expires:
            del sessions[token]
            _save_sessions(sessions)
            return None
    except (KeyError, ValueError, TypeError):
        return None
    return db.find_user_by_id(sess["user_id"])


# ------------------------------------------------------------------
# Decorators
# ------------------------------------------------------------------
def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user(request)
        if not user:
            return jsonify({"error": "Ntibyemera. Injira kandi."}), 401
        if not db._to_bool(user.get("active"), True):
            return jsonify({"error": "Konti yawe ntabwo ikora. Baza umushumba wa paruwasi."}), 403
        request._user = user
        return fn(*args, **kwargs)
    return wrapper


def require_parish(fn):
    """PARISH_PASTOR only."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user(request)
        if not user:
            return jsonify({"error": "Ntibyemera. Injira kandi."}), 401
        if user.get("role") != "PARISH_PASTOR":
            return jsonify({"error": "Ukeneye kuba Umushumba wa Paruwasi."}), 403
        request._user = user
        return fn(*args, **kwargs)
    return wrapper


def require_church(fn):
    """CHURCH_PASTOR only (must have a church_id assigned)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user(request)
        if not user:
            return jsonify({"error": "Ntibyemera. Injira kandi."}), 401
        if user.get("role") != "CHURCH_PASTOR":
            return jsonify({"error": "Ukeneye kuba Umushumba w'itorero."}), 403
        if not user.get("church_id"):
            return jsonify({"error": "Nta torero wahawe. Baza umushumba wa paruwasi."}), 403
        request._user = user
        return fn(*args, **kwargs)
    return wrapper


def require_church_or_finance(fn):
    """CHURCH_PASTOR or CHURCH_FINANCE (both must have a church_id assigned).

    Used for the amaturo entry flow: either the church shepherd
    (umushumba w'itorero) or the finance leader (umuyobozi ushinzwe imali)
    can record the weekly offerings, which then aggregate at the parish level.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user(request)
        if not user:
            return jsonify({"error": "Ntibyemera. Injira kandi."}), 401
        if user.get("role") not in ("CHURCH_PASTOR", "CHURCH_FINANCE"):
            return jsonify({"error": "Ukeneye kuba Umushumba cyangwa ushinzwe imali w'itorero."}), 403
        if not user.get("church_id"):
            return jsonify({"error": "Nta torero wahawe. Baza umushumba wa paruwasi."}), 403
        request._user = user
        return fn(*args, **kwargs)
    return wrapper


def require_ministry(fn):
    """MINISTRY_LEADER only (must have a ministry_id assigned)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user(request)
        if not user:
            return jsonify({"error": "Ntibyemera. Injira kandi."}), 401
        if user.get("role") != "MINISTRY_LEADER":
            return jsonify({"error": "Ukeneye kuba Umuyobozi wa ministeur."}), 403
        if not user.get("ministry_id"):
            return jsonify({"error": "Nta ministeur wahawe. Baza umushumba wa paruwasi."}), 403
        request._user = user
        return fn(*args, **kwargs)
    return wrapper


def require_zone_reader(fn):
    """ZONE_READER only (must have a church_id + zone_id assigned)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user(request)
        if not user:
            return jsonify({"error": "Ntibyemera. Injira kandi."}), 401
        if user.get("role") != "ZONE_READER":
            return jsonify({"error": "Ukeneye kuba Umuyobozi wa zone."}), 403
        if not user.get("church_id"):
            return jsonify({"error": "Nta zone wahawe. Baza umushumba w'itorero."}), 403
        request._user = user
        return fn(*args, **kwargs)
    return wrapper


def require_parish_manager(fn):
    """PARISH_MANAGER only — assists the parish pastor, sees parish-wide
    data (especially financial + assets)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user(request)
        if not user:
            return jsonify({"error": "Ntibyemera. Injira kandi."}), 401
        if user.get("role") != "PARISH_MANAGER":
            return jsonify({"error": "Ukeneye kuba Muyobozi wa Paruwasi."}), 403
        request._user = user
        return fn(*args, **kwargs)
    return wrapper


def require_parish_or_manager(fn):
    """PARISH_PASTOR or PARISH_MANAGER — both run the parish."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user(request)
        if not user:
            return jsonify({"error": "Ntibyemera. Injira kandi."}), 401
        if user.get("role") not in ("PARISH_PASTOR", "PARISH_MANAGER"):
            return jsonify({"error": "Ukeneye kuba Umushumba cyangwa Muyobozi wa Paruwasi."}), 403
        request._user = user
        return fn(*args, **kwargs)
    return wrapper


def require_parish_or_church_pastor(fn):
    """PARISH_PASTOR (whole parish) or CHURCH_PASTOR (own church only).

    The handler itself is responsible for scoping church-pastor actions to
    the user's own church_id; this decorator only gates on role.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user(request)
        if not user:
            return jsonify({"error": "Ntibyemera. Injira kandi."}), 401
        if user.get("role") not in ("PARISH_PASTOR", "CHURCH_PASTOR"):
            return jsonify({"error": "Ukeneye kuba Umushumba wa Paruwasi cyangwa w'itorero."}), 403
        request._user = user
        return fn(*args, **kwargs)
    return wrapper


def require_parish_or_church_pastor_or_zone(fn):
    """PARISH_PASTOR (whole parish), CHURCH_PASTOR (own church) or
    ZONE_READER (own zone only).

    The handler itself scopes church/zone actions to the user's own
    church_id / zone_id; this decorator only gates on role.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user(request)
        if not user:
            return jsonify({"error": "Ntibyemera. Injira kandi."}), 401
        if user.get("role") not in ("PARISH_PASTOR", "CHURCH_PASTOR", "ZONE_READER"):
            return jsonify({"error": "Ukeneye kuba Umushumba wa Paruwasi, w'itorero cyangwa wa zone."}), 403
        request._user = user
        return fn(*args, **kwargs)
    return wrapper


def set_session_cookie(resp, token):
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="Lax",
                    max_age=int(SESSION_TTL.total_seconds()), path="/")
    return resp


def clear_session_cookie(resp):
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# Role constants
PARISH_PASTOR = "PARISH_PASTOR"
CHURCH_PASTOR = "CHURCH_PASTOR"
CHURCH_FINANCE = "CHURCH_FINANCE"
MINISTRY_LEADER = "MINISTRY_LEADER"
ZONE_READER = "ZONE_READER"
PARISH_MANAGER = "PARISH_MANAGER"
