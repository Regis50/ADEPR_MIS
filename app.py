"""
app.py — ADEPR Paruwasi ya Ruhango MIS
Flask server with role-based access (Parish Pastor / Church Pastor /
Church Finance / Ministry Leader).

Scope: RUHANGO Parish only — 38 amatorero.
Ama makuru y'amaturo abishyirwamo n'umuyobozi ushinzwe imali cyangwa
umushumba w'itorero, bikagaragara kuri Paruwasi.

Run:
  1. pip install -r requirements.txt
  2. python3 seed.py   (only the first time)
  3. python3 app.py
  → open http://127.0.0.1:5000

Default logins (after seeding):
  parish / parish123           — Umushumba wa Paruwasi (full access)
  ruhango / church123          — Umushumba w'itorero (RUHANGO church)
  ruhango_fin / finance123     — Ushinzwe imali (RUHANGO church)
  leader_abana / leader123     — Ministry Leader (Abana)
"""

import os
import json
import traceback
from datetime import datetime

from flask import (
    Flask, send_file, jsonify, render_template,
    request, make_response, send_from_directory,
)
from flask_cors import CORS

import db
import auth
import menu_config
from auth import (
    require_auth, require_parish, require_church, require_church_or_finance,
    require_ministry, require_zone_reader, require_parish_manager,
    require_parish_or_manager, require_parish_or_church_pastor,
    require_parish_or_church_pastor_or_zone,
    current_user, set_session_cookie, clear_session_cookie,
)

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app, supports_credentials=True)


# ==================================================================
# Helpers
# ==================================================================
def _safe_user(u):
    if not u:
        return None
    # Strip every credential field — never expose hashes, plaintext, or
    # security answers through the API. SECRET_FIELDS is the single
    # source of truth in db.py.
    out = {k: v for k, v in u.items() if k not in db.SECRET_FIELDS}
    if out.get("church_id"):
        c = db.find_church(out["church_id"])
        if c:
            out["church_name"] = c.get("name", "")
    if out.get("ministry_id"):
        m = db.find_ministry(out["ministry_id"])
        if m:
            out["ministry_name"] = m.get("name", "")
    if out.get("zone_id"):
        z = db.find_zone(out["zone_id"])
        if z:
            out["zone_name"] = z.get("name", "")
    return out


def _safe_users(users):
    return [_safe_user(u) for u in users]


# ==================================================================
# HTML
# ==================================================================
@app.route("/")
def index():
    # V1.19 — send no-cache headers so the browser always fetches the
    # latest index.html (avoids the user being stuck on an older cached
    # build after we ship an update).
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/health")
def health():
    return jsonify({"ok": True, "service": "ADEPR MIS", "time": datetime.now().isoformat()})


# ==================================================================
# AUTH
# ==================================================================
@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error": "Izina n'ijambobanga birakenewe."}), 400
    user, token = auth.login(username, password)
    if not user or not token:
        return jsonify({"error": "Izina cyangwa ijambobanga sibyo."}), 401
    resp = make_response(jsonify({"ok": True, "user": _safe_user(user)}))
    set_session_cookie(resp, token)
    return resp


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        auth.logout(token)
    resp = make_response(jsonify({"ok": True}))
    clear_session_cookie(resp)
    return resp


# ------------------------------------------------------------------
# Self-service registration + approval + password reset (V1.5)
# ------------------------------------------------------------------
@app.route("/api/public/churches", methods=["GET"])
def api_public_churches():
    """Public list of churches (id+name only) for the registration form."""
    out = [{"id": c.get("id", ""), "name": c.get("name", "")}
           for c in db.list_churches()]
    out.sort(key=lambda x: x["name"])
    return jsonify(out)


@app.route("/api/public/churches/search", methods=["GET"])
def api_public_churches_search():
    """Public church search for the registration free-text picker."""
    q = request.args.get("q", "")
    rows = db.search_churches(q)
    return jsonify([{"id": r.get("id", ""), "name": r.get("name", "")}
                    for r in rows])


@app.route("/api/public/churches/find-or-create", methods=["POST"])
def api_public_churches_find_or_create():
    """Public find-or-create so unauthenticated users registering against
    a new church can still attach to it (modular)."""
    data = request.get_json(silent=True) or {}
    rec = db.find_or_create_church(data.get("name", ""))
    if not rec:
        return jsonify({"error": "Izina ry'itorero irakenewe."}), 400
    return jsonify({"id": rec.get("id", ""), "name": rec.get("name", "")})


@app.route("/api/public/security-questions", methods=["GET"])
def api_public_security_questions():
    return jsonify(db.SECURITY_QUESTIONS)


@app.route("/api/auth/register", methods=["POST"])
def api_auth_register():
    """Public self-registration → status 'pending' until the church
    shepherd (umushumba w'itorero) approves."""
    data = request.get_json(silent=True) or {}
    rec, err = db.register_user(data)
    if err:
        return jsonify({"error": err}), 400
    # Notify the church shepherd of the chosen church.
    church = db.find_church(rec.get("church_id", ""))
    db.send_notification({
        "sender_id": "",
        "sender_name": rec.get("name", ""),
        "sender_role": rec.get("role", ""),
        "recipient_role": "ALL_CHURCH",
        "church_id": rec.get("church_id", ""),
        "title": f"Konti nshya isaba kwemezwa: {rec.get('name','')}",
        "body": (f"{rec.get('name','')} ({rec.get('username','')}) yasabye "
                 f"konti ya {rec.get('role','')} mu itorero "
                 f"{church.get('name','') if church else ''}. Emeza cyangwa ange."),
        "category": "registration",
    })
    safe = _safe_user(rec)
    safe["status"] = rec.get("status", "pending")
    return jsonify({"ok": True, "user": safe, "message":
                    "Konti yawe yoherejwe. Tegereza kwemezwa n'umushumba w'itorero."}), 201


@app.route("/api/auth/forgot-password", methods=["POST"])
def api_auth_forgot_password():
    """Self-service: given username + security answer, set a new password."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    answer = data.get("security_answer") or ""
    new_pw = data.get("new_password") or ""
    if not username or not answer or not new_pw:
        return jsonify({"error": "Username, igisubizo, n'ijambobanga rishya birakenewe."}), 400
    rec, err = db.reset_password(username, answer, new_pw)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True, "message": "Ijambo ry'ibanga ryahinduwe. Injira."})


@app.route("/api/auth/security-question", methods=["GET"])
def api_auth_security_question():
    """Given a username, return its security question (so the forgot-pw
    form can show it)."""
    username = (request.args.get("username") or "").strip()
    if not username:
        return jsonify({"error": "Andika username."}), 400
    q = db.get_security_question(username)
    if not q:
        return jsonify({"error": "Username ntabonetse cyangwa nta cyibazo cyabitswe."}), 404
    return jsonify(q)


@app.route("/api/auth/change-password", methods=["POST"])
@require_auth
def api_auth_change_password():
    user = request._user
    data = request.get_json(silent=True) or {}
    rec, err = db.change_password(user["id"],
                                  data.get("old_password", ""),
                                  data.get("new_password", ""))
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True, "message": "Ijambo ry'ibanga ryahinduwe."})


# Pending-account approval (church shepherd for own church; parish all)
@app.route("/api/users/pending", methods=["GET"])
@require_auth
def api_users_pending():
    user = request._user
    if user.get("role") == "PARISH_PASTOR":
        rows = db.list_pending_users()
    elif user.get("church_id"):
        rows = db.list_pending_users(church_id=user["church_id"])
    else:
        rows = []
    # attach church name
    for r in rows:
        c = db.find_church(r.get("church_id", ""))
        r["church_name"] = c.get("name", "") if c else ""
    return jsonify(_safe_users(rows))


@app.route("/api/users/<uid>/approve", methods=["POST"])
@require_auth
def api_users_approve(uid):
    user = request._user
    target = db.find_user_by_id(uid)
    if not target:
        return jsonify({"error": "Konti ntabonetse."}), 404
    # Church shepherd approves only their own church's requests; parish all.
    if user.get("role") == "CHURCH_PASTOR":
        if target.get("church_id") != user.get("church_id"):
            return jsonify({"error": "Ushobora gusa kwemeza konti z'itorero ryawe."}), 403
    elif user.get("role") != "PARISH_PASTOR":
        return jsonify({"error": "N'umushumba w'itorero gusa ushobora kwemeza."}), 403
    rec = db.approve_user(uid, user)
    if not rec:
        return jsonify({"error": "Konti ntabonetse cyangwa yari yemejwe."}), 404
    # Notify the parish pastor of the new active account.
    db.send_notification({
        "sender_id": user["id"],
        "sender_name": user.get("name", ""),
        "sender_role": user.get("role", ""),
        "recipient_role": "PARISH_PASTOR",
        "church_id": rec.get("church_id", ""),
        "title": f"Konti yemejwe: {rec.get('name','')}",
        "body": (f"{rec.get('name','')} ({rec.get('username','')}) yemejwe na "
                 f"{user.get('name','')} nk'umukoresha wa {rec.get('role','')}."),
        "category": "registration",
    })
    return jsonify(rec)


@app.route("/api/users/<uid>/reject", methods=["POST"])
@require_auth
def api_users_reject(uid):
    user = request._user
    target = db.find_user_by_id(uid)
    if not target:
        return jsonify({"error": "Konti ntabonetse."}), 404
    if user.get("role") == "CHURCH_PASTOR":
        if target.get("church_id") != user.get("church_id"):
            return jsonify({"error": "Ushobora gusa kwemeza konti z'itorero ryawe."}), 403
    elif user.get("role") != "PARISH_PASTOR":
        return jsonify({"error": "N'umushumba w'itorero gusa ushobora kwemeza."}), 403
    data = request.get_json(silent=True) or {}
    rec = db.reject_user(uid, user, data.get("reason", ""))
    if not rec:
        return jsonify({"error": "Konti ntabonetse cyangwa yari yemejwe."}), 404
    return jsonify(rec)


@app.route("/api/auth/session", methods=["GET"])
def api_session():
    user = current_user(request)
    if not user:
        return jsonify({"authenticated": False}), 200
    # V1.12 — ship the personalised menu + parish/church/leader names so
    # the sidebar is config-driven (no more hardcoded nav per role) and
    # settings (parish name, church leader name) reflect in the UI.
    profile = db.load_parish_profile() or {}
    parish_name = profile.get("parish_name") or "Paruwasi ya Ruhango"
    pastor_name = profile.get("pastor_name") or ""
    church_name = ""
    leader_name = ""
    cid = user.get("church_id") or ""
    if cid:
        c = db.find_church(cid)
        if c:
            church_name = c.get("name", "")
            leader_name = c.get("leader_name") or c.get("pastor_name") or ""
    menu = menu_config.menu_for_role(user.get("role", ""), {
        "church_name": church_name,
        "leader_name": leader_name,
        "parish_name": parish_name,
    })
    return jsonify({
        "authenticated": True,
        "user": _safe_user(user),
        "menu": menu,
        "parish_name": parish_name,
        "pastor_name": pastor_name,
        "church_name": church_name,
        "leader_name": leader_name,
    }), 200


# ==================================================================
# TRANSLATIONS (public read; parish write)
# ==================================================================
@app.route("/api/translations", methods=["GET"])
def api_translations_get():
    return jsonify(db.load_translations())


@app.route("/api/translations", methods=["PUT"])
@require_parish
def api_translations_update():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or not data:
        return jsonify({"error": "Body must be a non-empty JSON object"}), 400
    new_state = db.save_translations(data)
    return jsonify({"ok": True, "translations": new_state})


# ==================================================================
# DASHBOARD
# ==================================================================
@app.route("/api/dashboard", methods=["GET"])
@require_auth
def api_dashboard():
    user = request._user
    role = user.get("role")
    church_id = user.get("church_id") if role == "CHURCH_PASTOR" else None
    kpis = db.dashboard_kpis(
        parish_pastor=(role == "PARISH_PASTOR"),
        church_id=church_id,
    )
    charts = db.dashboard_charts(church_id=church_id)
    return jsonify({"kpis": kpis, "charts": charts})


# ==================================================================
# CHURCHES  (Parish Pastor)
# ==================================================================
@app.route("/api/churches", methods=["GET"])
@require_parish_or_manager
def api_churches_list():
    parish = request.args.get("parish")
    rows = db.list_churches(parish=parish)
    # attach member counts
    for c in rows:
        c["members_count"] = len(db.list_members(church_id=c["id"]))
        c["offerings_total"] = sum(
            float(o.get("total", 0) or 0)
            for o in db.list_offerings(church_id=c["id"])
        )
    return jsonify(rows)


@app.route("/api/churches", methods=["POST"])
@require_parish
def api_churches_create():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "Izina ry'itorero rirakenewe."}), 400
    c = db.insert_church(data)
    if not c:
        return jsonify({"error": "Byanze."}), 500
    # Optionally create a church pastor account
    if data.get("create_pastor") and data.get("pastor_username"):
        uname = data["pastor_username"].strip().lower()
        pw = data.get("pastor_password") or "church123"
        if not db.find_user_by_username(uname):
            db.insert_user({
                "username": uname,
                "password": pw,
                "name": data.get("pastor_name") or c.get("leader_name", ""),
                "role": "CHURCH_PASTOR",
                "phone": c.get("leader_phone", ""),
                "email": "",
                "church_id": c["id"],
                "active": True,
            })
    return jsonify(c), 201


@app.route("/api/churches/<cid>", methods=["PUT"])
@require_parish
def api_churches_update(cid):
    data = request.get_json(silent=True) or {}
    ok = db.update_church(cid, data)
    if not ok:
        return jsonify({"error": "Itorero ntiryabonetse."}), 404
    return jsonify({"ok": True})


@app.route("/api/churches/<cid>", methods=["DELETE"])
@require_parish
def api_churches_delete(cid):
    ok = db.delete_church(cid)
    if not ok:
        return jsonify({"error": "Itorero ntiryabonetse."}), 404
    return jsonify({"ok": True})


# ==================================================================
# USERS (Church Pastors + Ministry Leaders)  (Parish Pastor)
# ==================================================================
@app.route("/api/users", methods=["GET"])
@require_parish
def api_users_list():
    role_filter = request.args.get("role")
    rows = db.list_users(active_only=False)
    out = [u for u in _safe_users(rows) if u.get("active") is not False]
    if role_filter:
        out = [u for u in out if u.get("role") == role_filter.upper()]
    return jsonify(out)


@app.route("/api/users", methods=["POST"])
@require_parish
def api_users_create():
    data = request.get_json(silent=True) or {}
    if not data.get("username") or not data.get("name"):
        return jsonify({"error": "username na name birakenewe."}), 400
    role = (data.get("role") or "CHURCH_PASTOR").upper()
    # V1.25 — all 5 admin-creatable roles are now accepted (ZONE_READER
    # and PARISH_MANAGER were previously rejected here even though the
    # role dropdown offered them).
    if role not in ("CHURCH_PASTOR", "CHURCH_FINANCE", "MINISTRY_LEADER",
                    "ZONE_READER", "PARISH_MANAGER"):
        return jsonify({"error": "Role yemewe: CHURCH_PASTOR, CHURCH_FINANCE, MINISTRY_LEADER, ZONE_READER cyangwa PARISH_MANAGER"}), 400
    # Role-specific entity validation: each role must be tied to the
    # parish entity it actually leads/manages.
    if role in ("CHURCH_PASTOR", "CHURCH_FINANCE", "MINISTRY_LEADER") and not (data.get("church_id") or "").strip():
        return jsonify({"error": "Hitamo itorero uwo mukoresha akorera."}), 400
    if role == "MINISTRY_LEADER" and not (data.get("ministry_id") or "").strip():
        return jsonify({"error": "Hitamo ministeur umuyobozi ayobora."}), 400
    if role == "ZONE_READER" and not (data.get("zone_id") or "").strip():
        return jsonify({"error": "Hitamo zone umuyobozi ayobora."}), 400
    data["role"] = role
    u = db.insert_user(data)
    if not u:
        return jsonify({"error": "Username isanzweho cyangwa byanze."}), 400
    return jsonify(_safe_user(u)), 201


@app.route("/api/users/<uid>", methods=["PUT"])
@require_parish
def api_users_update(uid):
    data = request.get_json(silent=True) or {}
    if "active" in data:
        data["active"] = db._to_bool(data["active"], True)
    if "role" in data:
        data["role"] = str(data["role"]).upper()
    ok = db.update_user(uid, data)
    if not ok:
        return jsonify({"error": "Ukoresha ntabonetse."}), 404
    return jsonify({"ok": True})


@app.route("/api/users/<uid>", methods=["DELETE"])
@require_parish
def api_users_delete(uid):
    # Soft-disable by default (keep history)
    ok = db.update_user(uid, {"active": False})
    if not ok:
        return jsonify({"error": "Ukoresha ntabonetse."}), 404
    return jsonify({"ok": True, "disabled": True})


@app.route("/api/users/<uid>/hard-delete", methods=["POST"])
@require_parish
def api_users_hard_delete(uid):
    ok = db.delete_user_hard(uid)
    if not ok:
        return jsonify({"error": "Ntibyakunze gusiba."}), 400
    return jsonify({"ok": True, "mode": "hard"})


# ==================================================================
# MINISTRIES  (Parish Pastor)
# ==================================================================
@app.route("/api/ministries", methods=["GET"])
@require_auth
def api_ministries_list():
    user = request._user
    role = user.get("role")
    # V1.27 — church users see parish-wide ministries + their own church's;
    # parish pastor sees all (no church_id filter).
    if role in ("CHURCH_PASTOR", "CHURCH_FINANCE"):
        rows = db.list_ministries(active_only=True,
                                  church_id=user.get("church_id", ""),
                                  include_parish_wide=True)
    else:
        rows = db.list_ministries(active_only=(role != "PARISH_PASTOR"))
    # attach member counts + church name (for scoped ministries)
    for m in rows:
        m["members_count"] = len(db.list_member_ministries(ministry_id=m["id"]))
        if m.get("church_id") and not m.get("church_name"):
            c = db.find_church(m["church_id"])
            if c:
                m["church_name"] = c.get("name", "")
    return jsonify(rows)


@app.route("/api/ministries", methods=["POST"])
@require_parish_or_church_pastor
def api_ministries_create():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "Izina rya ministeur rirakenewe."}), 400
    u = request._user
    # V1.27 — a church pastor creates ministries scoped to their own
    # church; parish pastor can create either parish-wide (no church_id)
    # or church-scoped ones.
    if u.get("role") == "CHURCH_PASTOR":
        data["church_id"] = u.get("church_id", "")
    m = db.insert_ministry(data)
    if not m:
        return jsonify({"error": "Byanze."}), 500
    # Optionally create a leader account (tied to the ministry's church)
    if data.get("create_leader") and data.get("leader_username"):
        uname = data["leader_username"].strip().lower()
        pw = data.get("leader_password") or "leader123"
        if not db.find_user_by_username(uname):
            db.insert_user({
                "username": uname, "password": pw,
                "name": data.get("leader_name") or m.get("leader_name", ""),
                "role": "MINISTRY_LEADER", "phone": m.get("leader_phone", ""),
                "ministry_id": m["id"], "church_id": m.get("church_id", ""),
                "active": True,
            })
    return jsonify(m), 201


@app.route("/api/ministries/<mid>", methods=["PUT"])
@require_parish_or_church_pastor
def api_ministries_update(mid):
    u = request._user
    data = request.get_json(silent=True) or {}
    m = db.find_ministry(mid)
    if not m:
        return jsonify({"error": "Ministeur ntabonetse."}), 404
    # V1.27 — church pastor can only edit ministries in their own church
    # (a parish-wide ministry is parish-only territory).
    if u.get("role") == "CHURCH_PASTOR" and m.get("church_id") != u.get("church_id"):
        return jsonify({"error": "Ushobora guhindura gusa ministeur z'itorero ryawe."}), 403
    # A church pastor cannot turn their ministry into a parish-wide one.
    if u.get("role") == "CHURCH_PASTOR":
        data["church_id"] = u.get("church_id", "")
    ok = db.update_ministry(mid, data)
    if not ok:
        return jsonify({"error": "Byanze."}), 500
    return jsonify({"ok": True})


@app.route("/api/ministries/<mid>", methods=["DELETE"])
@require_parish_or_church_pastor
def api_ministries_delete(mid):
    u = request._user
    m = db.find_ministry(mid)
    if not m:
        return jsonify({"error": "Ministeur ntabonetse."}), 404
    if u.get("role") == "CHURCH_PASTOR" and m.get("church_id") != u.get("church_id"):
        return jsonify({"error": "Ushobora gusiba gusa ministeur z'itorero ryawe."}), 403
    ok = db.delete_ministry(mid)
    if not ok:
        return jsonify({"error": "Byanze."}), 500
    return jsonify({"ok": True})


# ==================================================================
# MEMBERS  (Parish Pastor sees all; Church Pastor sees own church)
# ==================================================================
@app.route("/api/members", methods=["GET"])
@require_parish
def api_members_list_all():
    church_id = request.args.get("church_id")
    category = request.args.get("category")
    rows = db.list_members(church_id=church_id, category=category)
    # attach church name
    churches = {c["id"]: c for c in db.list_churches()}
    for m in rows:
        c = churches.get(m.get("church_id"))
        m["church_name"] = c.get("name") if c else ""
    return jsonify(rows)


# CHURCH PASTOR — own members
@app.route("/api/my-members", methods=["GET"])
@require_auth
def api_my_members_list():
    user = request._user
    if user.get("role") not in ("CHURCH_PASTOR", "CHURCH_FINANCE",
                                 "MINISTRY_LEADER", "ZONE_READER",
                                 "PARISH_PASTOR", "PARISH_MANAGER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    church_id = user.get("church_id") or ""
    category = request.args.get("category")
    # parish-level roles without a church see all members; otherwise scoped.
    if user.get("role") in ("PARISH_PASTOR", "PARISH_MANAGER") and \
            request.args.get("all") == "1":
        church_id = None
    rows = db.list_members(church_id=church_id, category=category)
    # zone reader sees only their zone's members.
    if user.get("role") == "ZONE_READER" and user.get("zone_id"):
        rows = [r for r in rows if r.get("zone_id") == user.get("zone_id")]
    return jsonify(rows)


@app.route("/api/my-members", methods=["POST"])
@require_auth
def api_my_members_create():
    user = request._user
    # CHURCH_PASTOR, CHURCH_FINANCE, MINISTRY_LEADER and ZONE_READER can
    # add members to their church (zone reader adds to their zone).
    if user.get("role") not in ("CHURCH_PASTOR", "CHURCH_FINANCE",
                                 "MINISTRY_LEADER", "ZONE_READER"):
        return jsonify({"error": "Ntibyemewe kwongeramo umukristo."}), 403
    if not user.get("church_id"):
        return jsonify({"error": "Nta gitorero wahawe."}), 403
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "Izina ry'umukristo rirakenewe."}), 400
    data["church_id"] = user["church_id"]
    # Zone reader auto-tags the member with their zone.
    if user.get("role") == "ZONE_READER" and not data.get("zone_id"):
        data["zone_id"] = user.get("zone_id", "")
    if data.get("category"):
        data["category"] = str(data["category"]).upper()
    m = db.insert_member(data)
    if not m:
        return jsonify({"error": "Byanze."}), 500
    db.log_activity({
        "actor_id": user.get("id", ""), "actor_name": user.get("name", ""),
        "actor_role": user.get("role", ""),
        "church_id": user.get("church_id", ""),
        "zone_id": m.get("zone_id", ""),
        "action": "MEMBER_ADDED", "target": m.get("name", ""),
        "detail": f"{m.get('category','')} • {m.get('phone','') or '—'}",
        "scope": "zone" if user.get("role") == "ZONE_READER" else "church",
    })
    return jsonify(m), 201


@app.route("/api/my-members/<mid>", methods=["PUT"])
@require_auth
def api_my_members_update(mid):
    user = request._user
    if user.get("role") not in ("CHURCH_PASTOR", "CHURCH_FINANCE",
                                 "MINISTRY_LEADER", "ZONE_READER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    m = db.find_member(mid)
    if not m or m.get("church_id") != user.get("church_id"):
        return jsonify({"error": "Ntibyemewe."}), 403
    data = request.get_json(silent=True) or {}
    ok = db.update_member(mid, data)
    if not ok:
        return jsonify({"error": "Ntabonetse."}), 404
    return jsonify({"ok": True})


@app.route("/api/my-members/<mid>", methods=["DELETE"])
@require_auth
def api_my_members_delete(mid):
    user = request._user
    if user.get("role") not in ("CHURCH_PASTOR", "CHURCH_FINANCE",
                                 "MINISTRY_LEADER", "ZONE_READER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    m = db.find_member(mid)
    if not m or m.get("church_id") != user.get("church_id"):
        return jsonify({"error": "Ntibyemewe."}), 403
    ok = db.delete_member(mid)
    if not ok:
        return jsonify({"error": "Ntabonetse."}), 404
    return jsonify({"ok": True})


# ==================================================================
# OFFERINGS
# ==================================================================
@app.route("/api/offerings", methods=["GET"])
@require_parish
def api_offerings_list_all():
    church_id = request.args.get("church_id")
    start = request.args.get("start_date")
    end = request.args.get("end_date")
    rows = db.list_offerings(church_id=church_id, start_date=start, end_date=end)
    churches = {c["id"]: c for c in db.list_churches()}
    for o in rows:
        c = churches.get(o.get("church_id"))
        o["church_name"] = c.get("name") if c else ""
    return jsonify(rows)


@app.route("/api/offerings/attachments", methods=["GET"])
@require_parish
def api_offerings_attachments():
    """Flat list of every proof-file attachment (MoMo SMS, bank slip, ...)
    across all churches — so the parish pastor can audit them in one place.
    Optional filters: ?church_id= &start_date= &end_date= &kind="""
    church_id = request.args.get("church_id")
    start = request.args.get("start_date")
    end = request.args.get("end_date")
    kind = (request.args.get("kind") or "").lower()
    rows = db.list_offering_attachments(
        church_id=church_id, start_date=start, end_date=end)
    if kind in ("momo_sms", "bank_slip", "other"):
        rows = [r for r in rows if r.get("kind") == kind]
    return jsonify(rows)


@app.route("/api/my-offerings", methods=["GET"])
@require_church_or_finance
def api_my_offerings_list():
    user = request._user
    rows = db.list_offerings(church_id=user["church_id"])
    return jsonify(rows)


@app.route("/api/my-offerings", methods=["POST"])
@require_church_or_finance
def api_my_offerings_create():
    user = request._user
    data = request.get_json(silent=True) or {}
    if not data.get("week_date"):
        return jsonify({"error": "Itariki y'icyumweru irakenewe."}), 400
    data["church_id"] = user["church_id"]
    data["recorded_by"] = user["id"]
    data["recorder_name"] = user.get("name", "")
    data["recorder_role"] = user.get("role", "")
    o = db.insert_offering(data)
    if not o:
        return jsonify({"error": "Byanze."}), 500
    dist = o.get("distribution") or {}
    igit = dist.get("igiteranyo", 0.0)
    church = db.find_church(user["church_id"])
    church_name = church.get("name", "") if church else ""

    # SMS thank-you to the church pastor / finance officer who reported.
    # Ubu koherereza ubutumwa bwa message2.py-style (yuzuye n'imibare yose,
    # ranking, ijanisha, umugisha) — builder ikomoka kuri data y'icyumweru
    # cyo. Komeza dry_run=True (nta kohereza kw'ukuri kuri auto-trigger;
    # parish pastor ahita asoma muri log + panel, ahitemo "Tumiza").
    try:
        import sms as sms_mod
        import thank_you_message as _tym
        week_date = (data.get("week_date") or o.get("week_date") or "")
        parish_name = (church.get("parish", "") if church else "") or None
        built = _tym.build(user["church_id"], week_date, parish_name=parish_name)
        thank_msg = built["message"]
        recipients = []
        for u in db.list_users(active_only=True):
            if u.get("church_id") == user["church_id"] and u.get("role") in (
                    "CHURCH_PASTOR", "CHURCH_FINANCE"):
                if u.get("phone"):
                    recipients.append({"name": u.get("name", ""), "phone": u["phone"]})
        if recipients:
            sms_mod.broadcast(recipients, thank_msg, dry_run=True)
        # Andika muri log ya thank-you SMS (dry_run) — bituma panel
        # "Ubutumwa bwo gushimira" yerekana ko byagenze neza.
        try:
            v13.insert_thank_you_sms({
                "church_id": user["church_id"],
                "church_name": church_name,
                "week_date": week_date,
                "total_offering": float(igit or 0),
                "recipient_phone": recipients[0]["phone"] if recipients else "",
                "recipient_name": recipients[0]["name"] if recipients else "",
                "message": thank_msg,
                "sent_by": user["id"],
                "sent_by_name": user.get("name", ""),
                "status": "dry_run",
                "gateway_response": "auto thank-you (dry_run) — parish pastor ahitemo Tumiza",
            })
        except Exception:
            pass
    except Exception:
        pass

    # Notification to the Parish Pastor.
    try:
        db.send_notification({
            "sender_id": user["id"],
            "sender_name": user.get("name", "") or church_name,
            "sender_role": user.get("role", ""),
            "recipient_role": "PARISH_PASTOR",
            "church_id": user["church_id"],
            "title": f"Amaturo ya {church_name} yabitswe",
            "body": (f"{church_name} yabitswe amaturo y'icyumweru wa "
                     f"{data['week_date']}: {int(round(igit)):,} RWF."),
            "category": "offering",
        })
    except Exception:
        pass

    return jsonify(o), 201


# ==================================================================
# RANKINGS
# ==================================================================
@app.route("/api/rankings", methods=["GET"])
@require_parish
def api_rankings():
    parish = request.args.get("parish")
    start = request.args.get("start_date")
    end = request.args.get("end_date")
    return jsonify(db.rankings(parish=parish, start_date=start, end_date=end))


@app.route("/api/parish/weekly-summary", methods=["GET"])
@require_parish
def api_parish_weekly_summary():
    """Aggregate weekly summary for the whole parish — the
    'incamake y'icyumweru' totals row of the Excel sheet."""
    start = request.args.get("start_date")
    end = request.args.get("end_date")
    return jsonify(db.parish_weekly_summary(start_date=start, end_date=end))


@app.route("/api/my-rank", methods=["GET"])
@require_church_or_finance
def api_my_rank():
    user = request._user
    all_rank = db.rankings()
    mine = next((r for r in all_rank if r.get("church_id") == user["church_id"]), None)
    if mine:
        return jsonify(mine)
    return jsonify({"rank": 0, "total": 0, "church_id": user["church_id"]})


# ==================================================================
# SMS BROADCAST  (Parish Pastor)
# ==================================================================
@app.route("/api/sms/preview-recipients", methods=["POST"])
@require_parish
def api_sms_preview():
    data = request.get_json(silent=True) or {}
    target = (data.get("target_role") or "ALL").upper()
    users = db.list_users(active_only=True)
    if target == "ALL":
        recipients = [u for u in users if u.get("role") != "PARISH_PASTOR"]
    elif target == "CHURCH_PASTOR":
        recipients = [u for u in users if u.get("role") == "CHURCH_PASTOR"]
    elif target == "CHURCH_FINANCE":
        recipients = [u for u in users if u.get("role") == "CHURCH_FINANCE"]
    elif target == "MINISTRY_LEADER":
        recipients = [u for u in users if u.get("role") == "MINISTRY_LEADER"]
    else:
        recipients = users
    # Prefer church leader phone if user phone missing
    churches = {c["id"]: c for c in db.list_churches()}
    out = []
    for u in recipients:
        phone = u.get("phone", "")
        if not phone and u.get("church_id") and u["church_id"] in churches:
            phone = churches[u["church_id"]].get("leader_phone", "")
        if phone:
            out.append({"name": u.get("name"), "phone": phone,
                        "role": u.get("role"), "id": u.get("id")})
    return jsonify({"recipients": out, "count": len(out)})


@app.route("/api/sms/broadcast", methods=["POST"])
@require_parish
def api_sms_broadcast():
    import sms
    user = request._user
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    target = (data.get("target_role") or "ALL").upper()
    dry_run = db._to_bool(data.get("dry_run", True), True)
    title = data.get("title", "Itangazo")

    if not message:
        return jsonify({"error": "Ubutumwa ntibuwemo."}), 400

    # Gather recipients
    users = db.list_users(active_only=True)
    if target == "ALL":
        recipients = [u for u in users if u.get("role") != "PARISH_PASTOR"]
    elif target == "CHURCH_PASTOR":
        recipients = [u for u in users if u.get("role") == "CHURCH_PASTOR"]
    elif target == "CHURCH_FINANCE":
        recipients = [u for u in users if u.get("role") == "CHURCH_FINANCE"]
    elif target == "MINISTRY_LEADER":
        recipients = [u for u in users if u.get("role") == "MINISTRY_LEADER"]
    else:
        recipients = users
    churches = {c["id"]: c for c in db.list_churches()}
    payload = []
    for u in recipients:
        phone = u.get("phone", "")
        if not phone and u.get("church_id") and u["church_id"] in churches:
            phone = churches[u["church_id"]].get("leader_phone", "")
        if phone:
            payload.append({"name": u.get("name", ""), "phone": phone})

    # V1.21 — append custom extra contacts the parish pastor typed in.
    extra_contacts = data.get("extra_contacts") or []
    if isinstance(extra_contacts, list):
        for c in extra_contacts:
            if isinstance(c, dict):
                p = str(c.get("phone", "")).strip()
                if p:
                    payload.append({"name": str(c.get("name", "")).strip(), "phone": p})

    result = sms.broadcast(payload, message, dry_run=dry_run)
    ann = db.insert_announcement({
        "title": title,
        "message": message,
        "target_role": target,
        "sent_by": user["id"],
        "sender_name": user.get("name", ""),
        "dry_run": dry_run,
        "recipients_count": result["total"],
        "sent_count": result["sent"],
        "failed_count": result["failed"],
        "status": "DRY_RUN" if dry_run else "SENT",
    })
    return jsonify({
        "ok": True,
        "announcement": ann,
        "broadcast": result,
    })


@app.route("/api/announcements", methods=["GET"])
@require_parish_or_manager
def api_announcements_list():
    return jsonify(db.list_announcements())


# ==================================================================
# REPORTS + EXPORT  (Parish Pastor)
# ==================================================================
@app.route("/api/reports/<period>", methods=["GET"])
@require_parish
def api_reports_generate(period):
    if period not in ("weekly", "monthly", "yearly"):
        return jsonify({"error": "Period yemewe: weekly, monthly, yearly"}), 400
    parish = request.args.get("parish")
    signer = request._user
    try:
        import reports
        path = reports.create_offering_report(period=period, parish=parish, signer=signer)
        return send_file(path, as_attachment=True,
                         download_name=os.path.basename(path))
    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


@app.route("/api/reports/parish-overview", methods=["GET"])
@require_parish
def api_reports_parish_overview():
    """V1.9: a one-document PDF summarizing the whole parish —
    KPIs, members by category, churches, offerings totals, discipline, visitors."""
    import io
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                         Paragraph, Spacer, KeepTogether)
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        try:
            pdfmetrics.registerFont(TTFont("NotoSans",
                "/usr/share/fonts/truetype/chinese/NotoSansSC-Regular.ttf"))
            pdfmetrics.registerFont(TTFont("NotoSans-Bold",
                "/usr/share/fonts/truetype/chinese/NotoSansSC-Bold.ttf"))
            body_font = "NotoSans"
            bold_font = "NotoSans-Bold"
        except Exception:
            body_font = "Helvetica"
            bold_font = "Helvetica-Bold"

        u = request._user
        kpis = db.dashboard_kpis(parish_pastor=True)
        cat_agg = db.parish_members_by_category()
        ministries = db.parish_ministries_report()
        disciplines = db.list_discipline()
        visitors = db.list_visitors()

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("t", parent=styles["Title"], fontName=bold_font,
                                     fontSize=18, textColor=colors.HexColor("#1F3864"),
                                     alignment=TA_CENTER, spaceAfter=4)
        sub_style = ParagraphStyle("s", parent=styles["BodyText"], fontName=body_font,
                                    fontSize=10, textColor=colors.HexColor("#64748B"),
                                    alignment=TA_CENTER, spaceAfter=14)
        h_style = ParagraphStyle("h", parent=styles["Heading2"], fontName=bold_font,
                                  fontSize=12, textColor=colors.HexColor("#1F3864"),
                                  spaceBefore=12, spaceAfter=6)
        cell_style = ParagraphStyle("c", parent=styles["BodyText"], fontName=body_font,
                                     fontSize=8, leading=10)

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
                                leftMargin=1.6*cm, rightMargin=1.6*cm,
                                topMargin=1.6*cm, bottomMargin=1.6*cm)
        elems = []
        parish_name = (db.load_parish_profile() or {}).get("parish_name") or "Paruwasi ya Ruhango"
        elems.append(Paragraph("RAPORO Y'AMAKURU YA PARUWASI", title_style))
        elems.append(Paragraph(parish_name + " — yanditswe ku wa "
                               + datetime.now().strftime("%d/%m/%Y"), sub_style))

        # KPIs
        elems.append(Paragraph("1. Imibare ikomeye (KPIs)", h_style))
        kpi_data = [["Icyerekezo", "Igiteranyo"],
                    ["Amatorero yose", str(kpis.get("total_churches", 0))],
                    ["Abakristo bose", str(kpis.get("total_members", 0))],
                    ["Amaturo yose (RWF)", f"{int(kpis.get('total_offerings', 0)):,}"],
                    ["Amaturo y'iyi cyumweru (RWF)", f"{int(kpis.get('this_week_offerings', 0)):,}"],
                    ["Igice cya paruwasi 2% (RWF)", f"{int(kpis.get('parish_share', 0)):,}"],
                    ["Abashumba b'itorero", str(kpis.get("active_church_pastors", 0))],
                    ["Abayobozi b'imali", str(kpis.get("active_church_finance", 0))]]
        t = Table(kpi_data, colWidths=[10*cm, 6*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), bold_font),
            ("FONTNAME", (0, 1), (-1, -1), body_font),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F8")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elems.append(t)

        # Members by category — per church
        elems.append(Paragraph("2. Abakristo mu byiciro (ku matorero)", h_style))
        cat_headers = ["Itorero"] + list(cat_agg["totals"].keys()) + ["Igiteranyo"]
        cat_rows = [cat_headers]
        for name, cats in cat_agg["by_church"].items():
            row = [name]
            total = 0
            for cat in cat_agg["totals"].keys():
                cnt = cats.get(cat, 0)
                row.append(str(cnt))
                total += cnt
            row.append(str(total))
            cat_rows.append(row)
        tot_row = ["IGITERANYO"] + [str(v) for v in cat_agg["totals"].values()] + [str(cat_agg["grand_total"])]
        cat_rows.append(tot_row)
        col_w = [4*cm] + [1.6*cm] * (len(cat_headers) - 1)
        t2 = Table(cat_rows, colWidths=col_w, repeatRows=1)
        t2.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), bold_font),
            ("FONTNAME", (0, 1), (-1, -1), body_font),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BBBBBB")),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#FFF3D6")),
            ("FONTNAME", (0, -1), (-1, -1), bold_font),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F2F4F8")]),
        ]))
        elems.append(t2)

        # Ministries
        elems.append(Paragraph("3. Ama ministeur yose", h_style))
        if ministries:
            min_rows = [["Ministeur", "Itorero", "Umuyobozi", "Abakristo"]]
            for m in ministries:
                min_rows.append([m.get("name", ""), m.get("church_name", ""),
                                  m.get("leader", ""), str(m.get("member_count", 0))])
            t3 = Table(min_rows, colWidths=[5*cm, 4*cm, 4*cm, 2*cm], repeatRows=1)
            t3.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), bold_font),
                ("FONTNAME", (0, 1), (-1, -1), body_font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BBBBBB")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F8")]),
            ]))
            elems.append(t3)
        else:
            elems.append(Paragraph("Nta ministeur iriho.", cell_style))

        # Discipline summary
        elems.append(Paragraph("4. Abahawe inzira (Discipline) — " + str(len(disciplines)) + " byose", h_style))
        if disciplines:
            disc_rows = [["Izina", "Itorero", "Ubwoko", "Status", "Igihe"]]
            for d in disciplines:
                disc_rows.append([d.get("member_name", ""),
                                   d.get("church_name", "") or "",
                                   d.get("discipline_type", ""),
                                   d.get("status", ""),
                                   (d.get("created_at", "") or "")[:10]])
            t4 = Table(disc_rows, colWidths=[4*cm, 4*cm, 3*cm, 3*cm, 3*cm], repeatRows=1)
            t4.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), bold_font),
                ("FONTNAME", (0, 1), (-1, -1), body_font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BBBBBB")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F8")]),
            ]))
            elems.append(t4)
        else:
            elems.append(Paragraph("Nta nzira yahawe n'umwe.", cell_style))

        # Visitors summary
        elems.append(Paragraph("5. Abashyitsi — " + str(len(visitors)) + " byose", h_style))
        if visitors:
            vis_rows = [["Izina", "Telefone", "Igihe", "Itorero", "Status"]]
            for v in visitors[:30]:
                vis_rows.append([v.get("name", ""), v.get("phone", ""),
                                  v.get("week_date", ""),
                                  v.get("church_name", "") or "",
                                  v.get("status", "")])
            t5 = Table(vis_rows, colWidths=[4*cm, 3*cm, 3*cm, 4*cm, 3*cm], repeatRows=1)
            t5.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), bold_font),
                ("FONTNAME", (0, 1), (-1, -1), body_font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BBBBBB")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F8")]),
            ]))
            elems.append(t5)
        else:
            elems.append(Paragraph("Nta mushyitsi wanditswe.", cell_style))

        elems.append(Spacer(1, 24))
        elems.append(Paragraph(
            "Raporo yakorewe na " + (u.get("name") or "ADEPR MIS") +
            " — " + datetime.now().strftime("%d/%m/%Y %H:%M"),
            ParagraphStyle("foot", parent=cell_style, fontSize=8,
                           textColor=colors.HexColor("#64748B"), alignment=TA_CENTER)))

        doc.build(elems)
        buf.seek(0)
        resp = make_response(buf.read())
        resp.headers["Content-Type"] = "application/pdf"
        resp.headers["Content-Disposition"] = \
            'attachment; filename="Parish_Overview_Report.pdf"'
        return resp
    except Exception:
        return jsonify({"error": traceback.format_exc()[-800:]}), 500


@app.route("/api/export/<period>", methods=["GET"])
@require_parish
def api_export_excel(period):
    if period not in ("weekly", "monthly", "yearly"):
        return jsonify({"error": "Period yemewe: weekly, monthly, yearly"}), 400
    parish = request.args.get("parish")
    try:
        import reports
        path = reports.export_excel(period=period, parish=parish)
        return send_file(path, as_attachment=True,
                         download_name=os.path.basename(path))
    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


@app.route("/api/sync-sheets", methods=["POST"])
@require_parish
def api_sync_sheets():
    import sheets_reader
    if not sheets_reader.credentials_present():
        return jsonify({"ok": False, "error": "credentials.json ntabwo ihari."}), 400
    return jsonify(sheets_reader.sync_from_sheets())


# ==================================================================
# PARISH PROFILE + SIGNATURE  (Parish Pastor)
# ==================================================================
@app.route("/api/parish/profile", methods=["GET"])
@require_auth
def api_parish_profile_get():
    return jsonify(db.load_parish_profile())


@app.route("/api/parish/profile", methods=["PUT"])
@require_parish
def api_parish_profile_update():
    data = request.get_json(silent=True) or {}
    profile = db.save_parish_profile(data)
    return jsonify({"ok": True, "profile": profile})


@app.route("/api/parish/signature", methods=["GET"])
@require_auth
def api_parish_signature_get():
    pastors = [u for u in db.list_users(active_only=True) if u.get("role") == "PARISH_PASTOR"]
    if not pastors:
        return jsonify({"has_signature": False, "png_base64": ""})
    sig = db.get_signature(pastors[0]["id"])
    return jsonify({
        "has_signature": bool(sig.get("png_base64")),
        "png_base64": sig.get("png_base64", ""),
        "name": sig.get("name", pastors[0].get("name", "")),
        "signed_at": sig.get("signed_at", ""),
    })


@app.route("/api/parish/signature", methods=["PUT"])
@require_parish
def api_parish_signature_update():
    data = request.get_json(silent=True) or {}
    b64 = data.get("png_base64", "")
    if not b64:
        return jsonify({"error": "png_base64 irakenewe."}), 400
    user = request._user
    ok = db.save_signature(user["id"], b64, user.get("name", ""))
    return jsonify({"ok": ok})


# ==================================================================
# OWN SIGNATURE  (any authenticated user signs themselves)
# ==================================================================
@app.route("/api/my-signature", methods=["GET"])
@require_auth
def api_my_signature_get():
    user = request._user
    sig = db.get_signature(user["id"])
    return jsonify({
        "has_signature": bool(sig.get("png_base64")),
        "png_base64": sig.get("png_base64", ""),
        "name": sig.get("name", user.get("name", "")),
        "signed_at": sig.get("signed_at", ""),
    })


@app.route("/api/my-signature", methods=["PUT"])
@require_auth
def api_my_signature_update():
    data = request.get_json(silent=True) or {}
    b64 = data.get("png_base64", "")
    if not b64:
        return jsonify({"error": "png_base64 irakenewe."}), 400
    user = request._user
    ok = db.save_signature(user["id"], b64, user.get("name", ""))
    return jsonify({"ok": ok})


@app.route("/api/signatures/all", methods=["GET"])
@require_parish
def api_all_signatures():
    sigs = db.load_signatures()
    return jsonify(sigs)


# ==================================================================
# MY CHURCH / MY MINISTRY (current user)
# ==================================================================
@app.route("/api/my-church", methods=["GET"])
@require_church_or_finance
def api_my_church():
    user = request._user
    c = db.find_church(user["church_id"])
    if not c:
        return jsonify({"error": "Itorero ntiryabonetse."}), 404
    c["members_count"] = len(db.list_members(church_id=c["id"]))
    return jsonify(c)


@app.route("/api/my-ministry", methods=["GET"])
@require_ministry
def api_my_ministry():
    user = request._user
    m = db.find_ministry(user["ministry_id"])
    if not m:
        return jsonify({"error": "Ministeur ntabonetse."}), 404
    m["members_count"] = len(db.list_member_ministries(ministry_id=m["id"]))
    return jsonify(m)


@app.route("/api/my-ministry-members", methods=["GET"])
@require_ministry
def api_my_ministry_members():
    user = request._user
    assignments = db.list_member_ministries(ministry_id=user["ministry_id"])
    member_ids = [a["member_id"] for a in assignments]
    out = []
    for mid in member_ids:
        m = db.find_member(mid)
        if m:
            c = db.find_church(m.get("church_id"))
            m["church_name"] = c.get("name") if c else ""
            out.append(m)
    return jsonify(out)


# ==================================================================
# CHANGE OWN PASSWORD  (any authenticated)
# ==================================================================
@app.route("/api/me/password", methods=["PUT"])
@require_auth
def api_my_password_update():
    data = request.get_json(silent=True) or {}
    new_pw = (data.get("new_password") or "").strip()
    if not new_pw or len(new_pw) < 4:
        return jsonify({"error": "Ijambobanga rigomba kugira nibura inyuguti 4."}), 400
    user = request._user
    ok = db.update_user(user["id"], {"password": new_pw})
    if not ok:
        return jsonify({"error": "Byanze."}), 500
    return jsonify({"ok": True})


# ==================================================================
# CHURCH BUDGETS  (set by Parish Pastor; used for achievement %)
# ==================================================================
@app.route("/api/budgets", methods=["GET"])
@require_auth
def api_budgets_list():
    user = request._user
    week = request.args.get("week_date")
    include_archived = request.args.get("include_archived", "0") in ("1", "true", "True")
    if not week:
        today = datetime.now().date()
        from datetime import timedelta
        monday = today - timedelta(days=today.weekday())
        week = monday.isoformat()
    rows = db.list_church_budgets(week_date=week)
    # V1.21 — hide archived budgets unless explicitly requested.
    if not include_archived:
        rows = [r for r in rows if not db._to_bool(r.get("archived"), False)]
    churches = db.list_churches()
    by_cid = {r["church_id"]: r for r in rows}
    out = []
    for c in churches:
        # Parish Pastor sees all; church users only see their own.
        if user.get("role") != "PARISH_PASTOR" and c["id"] != user.get("church_id"):
            continue
        b = by_cid.get(c["id"])
        out.append({
            "church_id": c["id"],
            "church_name": c.get("name", ""),
            "week_date": week,
            "amount": b["amount"] if b else 0.0,
            "set_by": b.get("set_by", "") if b else "",
        })
    return jsonify({"week_date": week, "items": out})


@app.route("/api/budgets", methods=["POST"])
@require_parish
def api_budgets_set():
    data = request.get_json(silent=True) or {}
    week = data.get("week_date")
    items = data.get("items") or []
    if not week or not items:
        return jsonify({"error": "week_date na items birakenewe."}), 400
    n = db.set_budgets_for_week(week, items, set_by=request._user["id"])
    return jsonify({"ok": True, "saved": n, "week_date": week})


@app.route("/api/budgets/clear-all", methods=["POST"])
@require_parish
def api_budgets_clear_all():
    """V1.21 — Delete all budgets for a given week."""
    week = request.args.get("week_date", "")
    if not week:
        return jsonify({"error": "week_date irakenewe."}), 400
    deleted = db.clear_budgets_for_week(week)
    return jsonify({"ok": True, "deleted": deleted, "week_date": week})


@app.route("/api/budgets/archive", methods=["POST"])
@require_parish
def api_budgets_archive():
    """V1.21 — Archive a single church's budget for a week."""
    week = request.args.get("week_date", "")
    church_id = request.args.get("church_id", "")
    if not week or not church_id:
        return jsonify({"error": "week_date na church_id birakenewe."}), 400
    ok = db.archive_budget(week, church_id)
    if not ok:
        return jsonify({"error": "Budget ntabonetse."}), 404
    return jsonify({"ok": True, "archived": True})


# ==================================================================
# NOTIFICATIONS  (bidirectional)
# ==================================================================
@app.route("/api/notifications", methods=["GET"])
@require_auth
def api_notifications_list():
    user = request._user
    notes = db.list_notifications_for_user(user)
    return jsonify(notes)


@app.route("/api/notifications/unread-count", methods=["GET"])
@require_auth
def api_notifications_unread():
    return jsonify({"count": db.unread_notification_count(request._user)})


@app.route("/api/notifications/latest", methods=["GET"])
@require_auth
def api_notifications_latest():
    """V1.9: poll newest notifications since a given id — used to toast new ones."""
    try:
        since_id = request.args.get("since", "")
        user = request._user
        notes = db.list_notifications_for_user(user)
        # Filter incoming (not outgoing) newer than since_id
        out = []
        max_id = ""
        for n in notes:
            if n.get("outgoing"):
                continue
            if since_id and str(n.get("id", "")) <= str(since_id):
                continue
            out.append(n)
            if not max_id or str(n.get("id", "")) > str(max_id):
                max_id = str(n.get("id", ""))
        return jsonify({"items": out[:10], "max_id": max_id})
    except Exception:
        return jsonify({"items": [], "max_id": ""})


@app.route("/api/notifications/<note_id>/read", methods=["POST"])
@require_auth
def api_notification_mark_read(note_id):
    db.mark_notification_read(note_id, request._user["id"])
    return jsonify({"ok": True})


@app.route("/api/notifications", methods=["POST"])
@require_auth
def api_notifications_send():
    user = request._user
    data = request.get_json(silent=True) or {}
    role = user.get("role", "")
    payload = {
        "sender_id": user["id"],
        "sender_name": user.get("name", ""),
        "sender_role": role,
        "title": data.get("title", ""),
        "body": data.get("body", ""),
        "category": data.get("category", "message"),
        "parent_id": data.get("parent_id", ""),
    }
    if role == "PARISH_PASTOR":
        # parish -> church / ministry / all
        target = (data.get("recipient_role") or "ALL").upper()
        payload["recipient_role"] = target
        if data.get("church_id"):
            payload["church_id"] = data["church_id"]
    else:
        # church / ministry -> parish pastor
        payload["recipient_role"] = "PARISH_PASTOR"
        if user.get("church_id"):
            payload["church_id"] = user["church_id"]
    note = db.send_notification(payload)
    if not note:
        return jsonify({"error": "Ubutumwa ntibwuzuye."}), 400
    return jsonify(note), 201


# ==================================================================
# CHURCH COMPARISON  (my_rank benchmark)
# ==================================================================
@app.route("/api/my-comparison", methods=["GET"])
@require_church_or_finance
def api_my_comparison():
    user = request._user
    comp = db.church_comparison(user["church_id"])
    if not comp:
        return jsonify({"error": "Ntibyabonetse."}), 404
    return jsonify(comp)


# ==================================================================
# DOCUMENTS  (request → parish approve + sign → notify + SMS)
# ==================================================================
@app.route("/api/documents", methods=["GET"])
@require_auth
def api_documents_list():
    user = request._user
    role = user.get("role", "")
    status = request.args.get("status")
    if role == "PARISH_PASTOR":
        rows = db.list_documents(status=status)
    elif user.get("church_id"):
        rows = db.list_documents(status=status, church_id=user["church_id"])
    else:
        rows = db.list_documents(status=status, submitted_by=user["id"])
    return jsonify(rows)


@app.route("/api/documents", methods=["POST"])
@require_church_or_finance
def api_documents_submit():
    user = request._user
    data = request.get_json(silent=True) or {}
    church = db.find_church(user.get("church_id", ""))
    rec = db.submit_document({
        "title": data.get("title", ""),
        "doc_type": data.get("doc_type", "request"),
        "body": data.get("body", ""),
        "church_id": user.get("church_id", ""),
        "church_name": church.get("name", "") if church else "",
        "submitted_by": user["id"],
        "submitted_by_name": user.get("name", ""),
    })
    if not rec:
        return jsonify({"error": "Umwanya \"title\" urakenewe."}), 400
    # Notify the parish pastor
    db.send_notification({
        "sender_id": user["id"],
        "sender_name": user.get("name", ""),
        "sender_role": user.get("role", ""),
        "recipient_role": "PARISH_PASTOR",
        "church_id": user.get("church_id", ""),
        "title": f"Inkete nshya: {rec['title']}",
        "body": (f"{rec['church_name']} yohereje inkete "
                 f"\"{rec['title']}\" y'emezwa."),
        "category": "document",
    })
    return jsonify(rec), 201


@app.route("/api/documents/<doc_id>/sign", methods=["POST"])
@require_parish
def api_documents_sign(doc_id):
    doc = db.sign_document(doc_id, request._user)
    if not doc:
        return jsonify({"error": "Inkete ntabonetse."}), 404
    # Notify the submitter's church
    db.send_notification({
        "sender_id": request._user["id"],
        "sender_name": request._user.get("name", ""),
        "sender_role": "PARISH_PASTOR",
        "recipient_role": "ALL_CHURCH",
        "church_id": doc.get("church_id", ""),
        "title": f"Inkete yemejwe: {doc['title']}",
        "body": (f"\"{doc['title']}\" yemejwe nyuma yo kuyisinya na "
                 f"{doc.get('signed_by_name', '')}."),
        "category": "document",
    })
    # SMS to the submitter's church leadership
    try:
        import sms as sms_mod
        msg = (f'Inkete "{doc["title"]}" yemejwe na '
               f'{doc.get("signed_by_name","")} (ADEPR Paruwasi ya Ruhango).')
        recipients = []
        for u in db.list_users(active_only=True):
            if u.get("church_id") == doc.get("church_id") and u.get("role") in (
                    "CHURCH_PASTOR", "CHURCH_FINANCE") and u.get("phone"):
                recipients.append({"name": u.get("name", ""), "phone": u["phone"]})
        if recipients:
            sms_mod.broadcast(recipients, msg, dry_run=True)
    except Exception:
        pass
    return jsonify(doc)


@app.route("/api/documents/<doc_id>/reject", methods=["POST"])
@require_parish
def api_documents_reject(doc_id):
    data = request.get_json(silent=True) or {}
    doc = db.reject_document(doc_id, request._user, data.get("feedback", ""))
    if not doc:
        return jsonify({"error": "Inkete ntabonetse."}), 404
    db.send_notification({
        "sender_id": request._user["id"],
        "sender_name": request._user.get("name", ""),
        "sender_role": "PARISH_PASTOR",
        "recipient_role": "ALL_CHURCH",
        "church_id": doc.get("church_id", ""),
        "title": f"Inkete ntiyemejwe: {doc['title']}",
        "body": (f"\"{doc['title']}\" ntiyemejwe. Impamvu: "
                 f"{doc.get('feedback','—')}"),
        "category": "document",
    })
    return jsonify(doc)


@app.route("/api/documents/<doc_id>", methods=["DELETE"])
@require_parish_or_church_pastor
def api_documents_delete(doc_id):
    """V1.21 — Delete a single document."""
    user = request._user
    doc = db.find_document(doc_id)
    if not doc:
        return jsonify({"error": "Inkete ntabonetse."}), 404
    if user.get("role") == "CHURCH_PASTOR" and doc.get("church_id") != user.get("church_id"):
        return jsonify({"error": "Ntibyemewe."}), 403
    db.delete_document(doc_id)
    return jsonify({"ok": True})


@app.route("/api/documents/clear-all", methods=["POST"])
@require_parish_or_church_pastor
def api_documents_clear_all():
    """V1.21 — Delete all documents."""
    user = request._user
    church_id = user.get("church_id") if user.get("role") == "CHURCH_PASTOR" else None
    if not church_id and user.get("role") == "CHURCH_PASTOR":
        return jsonify({"error": "Konti yawe ntabwo iyobewe itorero."}), 400
    status = (request.args.get("status") or "").strip() or None
    removed = db.clear_all_documents(church_id=church_id, status=status)
    return jsonify({"ok": True, "deleted": removed})


# ==================================================================
# MINISTRY LEADER — member management
# (a ministry leader can add members to their ministry; one leader
#  per ministry, but a leader's account carries a church_id so they
#  operate within their own church.)
# ==================================================================
@app.route("/api/ministry-members", methods=["GET"])
@require_ministry
def api_ministry_members_list():
    user = request._user
    assignments = db.list_member_ministries(ministry_id=user["ministry_id"])
    member_ids = [a["member_id"] for a in assignments]
    out = []
    for mid in member_ids:
        m = db.find_member(mid)
        if m:
            c = db.find_church(m.get("church_id"))
            m["church_name"] = c.get("name") if c else ""
            out.append(m)
    return jsonify(out)


@app.route("/api/ministry-members", methods=["POST"])
@require_ministry
def api_ministry_members_add():
    user = request._user
    data = request.get_json(silent=True) or {}
    # The ministry leader's account carries a church_id (set when the parish
    # pastor created the account). New members are created in that church.
    church_id = user.get("church_id") or data.get("church_id")
    if not church_id:
        return jsonify({
            "error": "Konti yawe nta itorero yerekanye. "
                     "Banza umushumba wa Paruwasi akongereho."
        }), 400
    if not (data.get("name") or "").strip():
        return jsonify({"error": "Amazina y'umukristu arakenewe."}), 400
    rec = db.insert_member({
        "church_id": church_id,
        "name": data["name"].strip(),
        "gender": data.get("gender", ""),
        "phone": data.get("phone", ""),
        "category": data.get("category", "ABAKRISTO_BOSE"),
        "dob": data.get("dob", ""),
        "baptism_date": data.get("baptism_date", ""),
        "address": data.get("address", ""),
        "active": True,
    })
    if not rec:
        return jsonify({"error": "Byanze."}), 500
    # Assign the new member to this leader's ministry.
    db.assign_member_ministries(rec["id"], [user["ministry_id"]])
    return jsonify(rec), 201


# ==================================================================
# V1.14 — MINISTRY LEADER: edit / delete OWN members
# A ministry leader may edit or remove a member who is currently
# assigned to their ministry. The assignment is the ownership test:
# if the member is not in this leader's ministry, 403. Removing the
# member here deletes the member record entirely (and its ministry
# links) — matching the leader's expectation that "my member" is
# fully under their care. The parish/church pastor can still see the
# change in the activity log.
# ==================================================================
def _member_in_leader_ministry(member, user):
    """True if `member` is currently assigned to the leader's ministry."""
    if not member:
        return False
    assignments = db.list_member_ministries(ministry_id=user["ministry_id"])
    ids = {a.get("member_id") for a in assignments}
    return member.get("id") in ids


@app.route("/api/my-ministry-members/<member_id>", methods=["PUT"])
@require_ministry
def api_my_ministry_members_update(member_id):
    user = request._user
    member = db.find_member(member_id)
    if not member:
        return jsonify({"error": "Umukristu ntabonetse."}), 404
    if not _member_in_leader_ministry(member, user):
        return jsonify({"error": "Ntibyemewe — umukristu ntabwo uri mu ministeur yawe."}), 403
    data = request.get_json(silent=True) or {}
    # Fields a ministry leader is allowed to edit on their own members.
    allowed = {}
    for k in ("name", "gender", "phone", "category", "dob",
              "baptism_date", "address", "active"):
        if k in data:
            allowed[k] = data[k]
    if not allowed:
        return jsonify({"error": "Nta makuru yahinduwe."}), 400
    if "name" in allowed and not str(allowed["name"]).strip():
        return jsonify({"error": "Amazina ntaabugenewe kuba atariho."}), 400
    db.update_member(member_id, allowed)
    db.log_activity({
        "actor_id": user["id"],
        "actor_name": user.get("name", ""),
        "actor_role": user.get("role", ""),
        "church_id": user.get("church_id", ""),
        "scope": "ministry",
        "action": "MEMBER_UPDATED",
        "target": member_id,
        "detail": "Umuyobozi wa ministeur yahinduye: " + ", ".join(allowed.keys()),
    })
    updated = db.find_member(member_id)
    c = db.find_church(updated.get("church_id"))
    if c:
        updated["church_name"] = c.get("name", "")
    return jsonify(updated)


@app.route("/api/my-ministry-members/<member_id>", methods=["DELETE"])
@require_ministry
def api_my_ministry_members_delete(member_id):
    user = request._user
    member = db.find_member(member_id)
    if not member:
        return jsonify({"error": "Umukristu ntabonetse."}), 404
    if not _member_in_leader_ministry(member, user):
        return jsonify({"error": "Ntibyemewe — umukristu ntabwo uri mu ministeur yawe."}), 403
    member_name = member.get("name", "")
    db.delete_member(member_id)   # also clears ministry assignments
    db.log_activity({
        "actor_id": user["id"],
        "actor_name": user.get("name", ""),
        "actor_role": user.get("role", ""),
        "church_id": user.get("church_id", ""),
        "scope": "ministry",
        "action": "MEMBER_DELETED",
        "target": member_id,
        "detail": "Umuyobozi wa ministeur yasuye: " + member_name,
    })
    return jsonify({"ok": True, "deleted": member_id})


# ==================================================================
# SERVICE / CERTIFICATE REQUESTS  (member reception approval flow)
# A leader uploads a certificate + message asking that a Christian be
# received; the church pastor approves → the Christian is added as a
# member automatically. Reject carries feedback.
# ==================================================================
@app.route("/api/service-requests", methods=["GET"])
@require_auth
def api_service_requests_list():
    user = request._user
    status = request.args.get("status")
    role = user.get("role", "")
    if role == "PARISH_PASTOR":
        rows = db.list_service_requests(status=status)
    elif role == "MINISTRY_LEADER":
        rows = db.list_service_requests(status=status, requester_id=user["id"])
    elif user.get("church_id"):
        rows = db.list_service_requests(status=status, church_id=user["church_id"])
    else:
        rows = db.list_service_requests(status=status)
    return jsonify(rows)


@app.route("/api/service-requests", methods=["POST"])
@require_auth
def api_service_requests_submit():
    user = request._user
    data = request.get_json(silent=True) or {}
    church_id = user.get("church_id") or data.get("church_id")
    if not church_id:
        return jsonify({"error": "Konti yawe nta itorero yerekanye."}), 400
    if not (data.get("christian_name") or "").strip():
        return jsonify({"error": "Amazina y'umukristu arakenewe."}), 400
    church = db.find_church(church_id)
    rec = db.submit_service_request({
        "requester_id": user["id"],
        "requester_name": user.get("name", ""),
        "requester_role": user.get("role", ""),
        "church_id": church_id,
        "church_name": church.get("name", "") if church else "",
        "christian_name": data["christian_name"],
        "christian_phone": data.get("christian_phone", ""),
        "christian_gender": data.get("christian_gender", ""),
        "request_type": data.get("request_type", "NEW_MEMBER"),
        "message": data.get("message", ""),
        "certificate_filename": data.get("certificate_filename", ""),
        "attachments": data.get("attachments", []) or [],
    })
    if not rec:
        return jsonify({"error": "Byanze."}), 500
    # Notify the church pastor + parish pastor.
    db.send_notification({
        "sender_id": user["id"],
        "sender_name": user.get("name", ""),
        "sender_role": user.get("role", ""),
        "recipient_role": "ALL_CHURCH",
        "church_id": church_id,
        "title": f"Gusaba kwakira umukristu: {rec['christian_name']}",
        "body": (f"{user.get('name','')} yasabye kwakira {rec['christian_name']} "
                 f"mu itorero. Cert: {rec.get('certificate_filename') or '—'}."),
        "category": "service",
    })
    return jsonify(rec), 201


@app.route("/api/service-requests/<req_id>/approve", methods=["POST"])
@require_church
def api_service_requests_approve(req_id):
    """Church pastor approves → member auto-created in the church."""
    req = db.approve_service_request(req_id, request._user)
    if not req:
        return jsonify({"error": "Isabye ntabonetse cyangwa ryemejwe."}), 404
    db.send_notification({
        "sender_id": request._user["id"],
        "sender_name": request._user.get("name", ""),
        "sender_role": request._user.get("role", ""),
        "recipient_role": "PARISH_PASTOR",
        "church_id": req.get("church_id", ""),
        "title": f"Umukristu yemejwe: {req['christian_name']}",
        "body": (f"{req['church_name']} yemeje kwakira {req['christian_name']} "
                 f"nk'umukristo nshya. Member id: {req.get('created_member_id','')[:10]}."),
        "category": "service",
    })
    return jsonify(req)


@app.route("/api/service-requests/<req_id>/reject", methods=["POST"])
@require_church
def api_service_requests_reject(req_id):
    data = request.get_json(silent=True) or {}
    req = db.reject_service_request(req_id, request._user, data.get("feedback", ""))
    if not req:
        return jsonify({"error": "Isabye ntabonetse."}), 404
    db.send_notification({
        "sender_id": request._user["id"],
        "sender_name": request._user.get("name", ""),
        "sender_role": request._user.get("role", ""),
        "recipient_role": request._user.get("role", "MINISTRY_LEADER"),
        "church_id": req.get("church_id", ""),
        "title": f"Isabye ryanze: {req['christian_name']}",
        "body": (f"Kwakira {req['christian_name']} byanze. Impamvu: "
                 f"{req.get('feedback','—')}"),
        "category": "service",
    })
    return jsonify(req)


@app.route("/api/service-requests/<req_id>/parish-override", methods=["POST"])
@require_parish
def api_service_requests_parish_override(req_id):
    """V1.12 — Parish pastor (head of all) overrides a reception that a
    local church already approved. The auto-created member is deactivated
    and the church is notified that the parish reversed its decision."""
    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()
    if not reason:
        return jsonify({"error": "Andika impamvu yo guhana icyemezo cy'itorero."}), 400
    req = db.parish_override_reject_service_request(req_id, request._user, reason)
    if not req:
        return jsonify({"error": "Isabye ntabonetse cyangwa ntiryari cyemejwe n'itorero."}), 404
    # Notify the church that the parish reversed their approval.
    db.send_notification({
        "sender_id": request._user["id"],
        "sender_name": request._user.get("name", ""),
        "sender_role": request._user.get("role", ""),
        "recipient_role": "ALL_CHURCH",
        "church_id": req.get("church_id", ""),
        "title": f"Paruwasi yahanye: {req['christian_name']}",
        "body": (f"Paruwasi yahanye icyemezo cy'itorero {req.get('church_name','')} "
                 f"cyo kwakira {req['christian_name']}. Impamvu: {reason}. "
                 f"Umukristu yakuwe mu bakristo b'itorero."),
        "category": "service",
    })
    return jsonify(req)


# ==================================================================
# DEATH REPORTS  (member marked deceased → removed from active
# roster → notification to parish)
# ==================================================================
@app.route("/api/death-reports", methods=["GET"])
@require_auth
def api_death_reports_list():
    user = request._user
    role = user.get("role", "")
    if role == "PARISH_PASTOR":
        rows = db.list_death_reports()
    elif user.get("church_id"):
        rows = db.list_death_reports(church_id=user["church_id"])
    else:
        rows = db.list_death_reports()
    return jsonify(rows)


@app.route("/api/death-reports", methods=["POST"])
@require_church_or_finance
def api_death_reports_create():
    user = request._user
    data = request.get_json(silent=True) or {}
    member_id = data.get("member_id")
    if not member_id:
        return jsonify({"error": "Hitamo umukristu."}), 400
    member = db.find_member(member_id)
    if not member:
        return jsonify({"error": "Umukristu ntabonetse."}), 404
    if member.get("church_id") != user.get("church_id") and user.get("role") != "PARISH_PASTOR":
        return jsonify({"error": "Umunsi w'umukristu w'itorero ryawe."}), 403
    church = db.find_church(member.get("church_id", ""))
    rec = db.report_death({
        "member_id": member_id,
        "church_id": member.get("church_id", ""),
        "church_name": church.get("name", "") if church else "",
        "reported_by": user["id"],
        "reported_by_name": user.get("name", ""),
        "death_date": data.get("death_date", ""),
        "notes": data.get("notes", ""),
    })
    if not rec:
        return jsonify({"error": "Byanze."}), 500
    # Notify parish.
    db.send_notification({
        "sender_id": user["id"],
        "sender_name": user.get("name", ""),
        "sender_role": user.get("role", ""),
        "recipient_role": "PARISH_PASTOR",
        "church_id": member.get("church_id", ""),
        "title": f"Intuntu: {rec['member_name']}",
        "body": (f"{rec['church_name']} yatangaje ko {rec['member_name']} "
                 f"yitabye Imana kuwa {rec.get('death_date','—')}. "
                 f"Akurwamo muri sisitemu."),
        "category": "death",
    })
    return jsonify(rec), 201


# ==================================================================
# SCHEDULES  (a leader creates a scheduled event; feedback is
# collected in-system)
# ==================================================================
@app.route("/api/schedules", methods=["GET"])
@require_auth
def api_schedules_list():
    user = request._user
    status = request.args.get("status")
    role = user.get("role", "")
    if role == "PARISH_PASTOR":
        rows = db.list_schedules(status=status)
    elif role == "MINISTRY_LEADER":
        rows = db.list_schedules(status=status, scheduled_by=user["id"])
    elif user.get("church_id"):
        rows = db.list_schedules(status=status, church_id=user["church_id"])
    else:
        rows = db.list_schedules(status=status)
    return jsonify(rows)


@app.route("/api/schedules", methods=["POST"])
@require_auth
def api_schedules_create():
    user = request._user
    data = request.get_json(silent=True) or {}
    church_id = user.get("church_id") or data.get("church_id")
    rec = db.create_schedule({
        "title": data.get("title", ""),
        "description": data.get("description", ""),
        "scheduled_by": user["id"],
        "scheduled_by_name": user.get("name", ""),
        "scheduled_by_role": user.get("role", ""),
        "church_id": church_id or "",
        "ministry_id": user.get("ministry_id", "") or data.get("ministry_id", ""),
        "datetime": data.get("datetime", ""),
        "location": data.get("location", ""),
    })
    if not rec:
        return jsonify({"error": "Umutwe n'amasegonda (datetime) birakenewe."}), 400
    return jsonify(rec), 201


@app.route("/api/schedules/<sc_id>/feedback", methods=["POST"])
@require_auth
def api_schedules_feedback(sc_id):
    user = request._user
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Andika igitekerezo."}), 400
    rec = db.add_schedule_feedback(sc_id, user, text)
    if not rec:
        return jsonify({"error": "Gahunda ntabonetse."}), 404
    return jsonify(rec)


@app.route("/api/schedules/<sc_id>/status", methods=["POST"])
@require_auth
def api_schedules_status(sc_id):
    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "").lower()
    if status not in db.SCHEDULE_STATUSES:
        return jsonify({"error": "Status: " + ",".join(db.SCHEDULE_STATUSES)}), 400
    rec = db.update_schedule_status(sc_id, status)
    if not rec:
        return jsonify({"error": "Gahunda ntabonetse."}), 404
    return jsonify(rec)


# V1.15 — Edit / delete OWN schedule. A ministry leader / zone reader /
# church user who CREATED a schedule can edit its title/description/
# datetime/location or delete it — but ONLY if they created it (ownership
# check on scheduled_by). This fixes the gap where a ministeur could
# create a schedule but never correct or remove it.
@app.route("/api/schedules/<sc_id>", methods=["PUT"])
@require_auth
def api_schedules_edit(sc_id):
    user = request._user
    data = request.get_json(silent=True) or {}
    # Fetch the schedule to verify ownership.
    all_sched = db.list_schedules()
    sched = next((s for s in all_sched if s.get("id") == sc_id), None)
    if not sched:
        return jsonify({"error": "Gahunda ntabonetse."}), 404
    # Ownership: creator only. Parish pastors can edit any schedule
    # (they sit above the churches and may need to correct entries).
    is_owner = sched.get("scheduled_by") == user.get("id")
    is_parish = (user.get("role") or "").upper() in ("PARISH_PASTOR", "PARISH_MANAGER")
    if not (is_owner or is_parish):
        return jsonify({"error": "Ushobora guhindura gahunda wowe mwene gusa."}), 403
    # Validate required fields if provided.
    if "title" in data and not str(data.get("title", "")).strip():
        return jsonify({"error": "Umutwe ntushobora kuba ubusa."}), 400
    if "datetime" in data and not str(data.get("datetime", "")).strip():
        return jsonify({"error": "Igihe (datetime) kirakenewe."}), 400
    rec = db.update_schedule(sc_id, data)
    return jsonify(rec)


@app.route("/api/schedules/<sc_id>", methods=["DELETE"])
@require_auth
def api_schedules_delete(sc_id):
    user = request._user
    all_sched = db.list_schedules()
    sched = next((s for s in all_sched if s.get("id") == sc_id), None)
    if not sched:
        return jsonify({"error": "Gahunda ntabonetse."}), 404
    is_owner = sched.get("scheduled_by") == user.get("id")
    is_parish = (user.get("role") or "").upper() in ("PARISH_PASTOR", "PARISH_MANAGER")
    if not (is_owner or is_parish):
        return jsonify({"error": "Ushobora gukuraho gahunda wowe mwene gusa."}), 403
    ok = db.delete_schedule(sc_id)
    if not ok:
        return jsonify({"error": "Gahunda ntabonetse."}), 404
    return jsonify({"ok": True, "id": sc_id})


# V1.15 — Withdraw (cancel) OWN service request. A ministry leader / zone
# reader who submitted a reception request can withdraw it as long as it's
# still pending (not yet approved/rejected by the church). This fixes the
# gap where a requester couldn't undo their own submission.
@app.route("/api/service-requests/<req_id>/withdraw", methods=["POST"])
@require_auth
def api_service_requests_withdraw(req_id):
    user = request._user
    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()
    all_reqs = db.list_service_requests()
    req = next((r for r in all_reqs if r.get("id") == req_id), None)
    if not req:
        return jsonify({"error": "Gusaba ntabonetse."}), 404
    if req.get("requester_id") != user.get("id"):
        return jsonify({"error": "Ushobora gukuraho gusaba kwawe gusa."}), 403
    if req.get("status") not in ("pending", None):
        return jsonify({"error": "Gusaba cyongera gukorerwa — ntikiba cyakiriwe."}), 400
    # Mark as withdrawn (reuse the rejected status path with a clear note).
    rec = db.reject_service_request(
        req_id, {"id": user.get("id"), "name": user.get("name", ""),
                 "role": "SYSTEM"},
        f"[WITHDRAWN by requester] {reason}".strip())
    if not rec:
        return jsonify({"error": "Gusaba ntabonetse."}), 404
    return jsonify(rec)


# ------------------------------------------------------------------
# Google Calendar integration (V1.5)
# True OAuth sync requires a public server + Google Cloud credentials.
# Here we offer two practical, offline-capable exports that put the event
# into the user's Google Calendar with reminders:
#   1. .ics file download (works with Google Calendar import, Outlook, Apple)
#   2. "Add to Google Calendar" URL (opens Google Calendar pre-filled)
# ------------------------------------------------------------------
def _sc_to_dt(iso_str):
    """Parse the schedule datetime → (python datetime, gcal YYYYMMDDTHHMMSS)."""
    import datetime as _dt
    try:
        dt = _dt.datetime.fromisoformat(iso_str)
    except Exception:
        dt = _dt.datetime.now()
    return dt, dt.strftime("%Y%m%dT%H%M%S")


def _sc_end_dt(start_iso):
    """Default event duration = 1 hour."""
    import datetime as _dt
    try:
        dt = _dt.datetime.fromisoformat(start_iso) + _dt.timedelta(hours=1)
    except Exception:
        dt = _dt.datetime.now() + _dt.timedelta(hours=1)
    return dt.strftime("%Y%m%dT%H%M%S")


@app.route("/api/schedules/<sc_id>/gcal", methods=["GET"])
@require_auth
def api_schedules_gcal(sc_id):
    sc = next((r for r in db.list_schedules() if r.get("id") == sc_id), None)
    if not sc:
        return jsonify({"error": "Gahunda ntabonetse."}), 404
    _, start = _sc_to_dt(sc.get("datetime", ""))
    end = _sc_end_dt(sc.get("datetime", ""))
    from urllib.parse import quote
    params = (
        ("action", "TEMPLATE"),
        ("text", sc.get("title", "Gahunda")),
        ("dates", f"{start}/{end}"),
        ("details", sc.get("description", "")),
        ("location", sc.get("location", "")),
    )
    url = "https://calendar.google.com/calendar/render?" + \
          "&".join(f"{k}={quote(v)}" for k, v in params)
    return jsonify({"url": url})


@app.route("/api/schedules/<sc_id>/ics", methods=["GET"])
@require_auth
def api_schedules_ics(sc_id):
    sc = next((r for r in db.list_schedules() if r.get("id") == sc_id), None)
    if not sc:
        return jsonify({"error": "Gahunda ntabonetse."}), 404
    dt, start = _sc_to_dt(sc.get("datetime", ""))
    end = _sc_end_dt(sc.get("datetime", ""))
    import datetime as _dt
    stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    uid = f"{sc_id}@adepr-mis.local"
    title = sc.get("title", "Gahunda").replace("\n", "\\n")
    desc = (sc.get("description", "") or "").replace("\n", "\\n")
    loc = (sc.get("location", "") or "").replace("\n", "\\n")
    ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//ADEPR MIS//Schedule//RW\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "METHOD:PUBLISH\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{stamp}\r\n"
        f"DTSTART:{start}\r\n"
        f"DTEND:{end}\r\n"
        f"SUMMARY:{title}\r\n"
        f"DESCRIPTION:{desc}\r\n"
        f"LOCATION:{loc}\r\n"
        "BEGIN:VALARM\r\n"
        "TRIGGER:-PT30M\r\n"
        "ACTION:DISPLAY\r\n"
        f"DESCRIPTION:{title} iri hafi!\r\n"
        "END:VALARM\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    resp = make_response(ics)
    resp.headers["Content-Type"] = "text/calendar; charset=utf-8"
    resp.headers["Content-Disposition"] = \
        f"attachment; filename=adepr_schedule_{sc_id}.ics"
    return resp


# ==================================================================
# AUTOMATION LAYER (V1.6)
# Global search, list exports (Excel+PDF), message queue, email reports,
# system health + settings.
# ==================================================================

@app.route("/api/search", methods=["GET"])
@require_auth
def api_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({})
    return jsonify(db.search_all(q, user=request._user))


def _export_rows(resource, church_filter=None):
    """Return (headers, rows, title) for a given resource name."""
    if resource == "members":
        rows = db.list_members()
        headers = ["Izina", "Telefone", "Itorero", "Icyiciro", "Status",
                   "Igihe cyo kwinjira"]
        out = []
        for m in rows:
            c = db.find_church(m.get("church_id", ""))
            out.append([m.get("name", ""), m.get("phone", ""),
                        c.get("name", "") if c else "",
                        m.get("category", ""), m.get("status", ""),
                        (m.get("joined_at", "") or "")[:10]])
        return headers, out, "Abakristo bose"
    if resource == "churches":
        rows = db.list_churches()
        # V1.23 — full details export (was only showing names because the
        # field names did not match the stored record: leader_name, leader_phone,
        # leader_email, location, members_count, offerings_total).
        headers = ["#", "Itorero", "Paruwasi", "Umuyobozi", "Telefone",
                   "Email", "Aho herereye", "Abakristo", "Amaturo (RWF)",
                   "Status", "Igihe cyo kurekura"]
        out = []
        for i, c in enumerate(rows, 1):
            mc = c.get("members_count")
            if mc is None:
                mc = len(db.list_members(church_id=c.get("id", "")))
            ot = c.get("offerings_total")
            if ot is None:
                ot = sum(float(o.get("igiteranyo", 0) or 0)
                         for o in db.list_offerings(church_id=c.get("id", "")))
            active = c.get("active", True)
            status = "Kora (active)" if db._to_bool(active, True) else "Ntibikora (inactive)"
            out.append([
                i,
                c.get("name", ""),
                c.get("parish", ""),
                c.get("leader_name", ""),
                c.get("leader_phone", ""),
                c.get("leader_email", ""),
                c.get("location", ""),
                mc,
                ot,
                status,
                (c.get("created_at", "") or "")[:10],
            ])
        return headers, out, "Amatorero yose"
    if resource == "offerings":
        rows = db.list_offerings()
        headers = ["Itorero", "Igihe", "Igiteranyo (RWF)", "Abaherereye",
                   "Status"]
        out = [[o.get("church_name", ""), o.get("period", "") or o.get("date", ""),
                o.get("igiteranyo", ""), o.get("attendance", ""),
                o.get("status", "")] for o in rows]
        return headers, out, "Amaturo yose"
    if resource == "schedules":
        rows = db.list_schedules()
        headers = ["Umutwe", "Igihe", "Aho bizabera", "Uwarebye", "Status"]
        out = [[s.get("title", ""), (s.get("datetime", "") or "")[:16],
                s.get("location", ""), s.get("scheduled_by_name", ""),
                s.get("status", "")] for s in rows]
        return headers, out, "Gahunda (Schedules)"
    if resource == "service_requests":
        rows = db.list_service_requests()
        headers = ["Izina ry'umukristu", "Uwasabye", "Itorero", "Status",
                   "Igihe"]
        out = []
        for sr in rows:
            c = db.find_church(sr.get("church_id", ""))
            out.append([sr.get("christian_name", ""),
                        sr.get("requester_name", ""),
                        c.get("name", "") if c else "",
                        sr.get("status", ""),
                        (sr.get("created_at", "") or "")[:10]])
        return headers, out, "Ibisabye (Service requests)"
    if resource == "death_reports":
        rows = db.list_death_reports()
        headers = ["Izina ry'ubitabye", "Itorero", "Icyiciro",
                   "Igihe cyo gupfa", "Uwabitangije"]
        out = []
        for dr in rows:
            c = db.find_church(dr.get("church_id", ""))
            out.append([dr.get("member_name", ""),
                        c.get("name", "") if c else "",
                        dr.get("category", ""),
                        dr.get("death_date", ""),
                        dr.get("reported_by_name", "")])
        return headers, out, "Abitabye Imana"
    if resource == "users":
        rows = db.list_users()
        headers = ["Izina", "Username", "Role", "Itorero", "Status"]
        out = []
        for u in rows:
            c = db.find_church(u.get("church_id", ""))
            out.append([u.get("name", ""), u.get("username", ""),
                        u.get("role", ""),
                        c.get("name", "") if c else "",
                        u.get("status", "active")])
        return headers, out, "Abakoresha sisitemu"
    if resource == "visitors":
        rows = db.list_visitors()
        headers = ["Izina", "Telefone", "Igihe", "Intego", "Aho atuye",
                   "Status", "Itorero"]
        out = []
        for v in rows:
            out.append([v.get("name", ""), v.get("phone", ""),
                        v.get("week_date", ""), v.get("goal_taught", ""),
                        v.get("address", ""), v.get("status", ""),
                        v.get("church_name", "")])
        return headers, out, "Abashyitsi"
    if resource == "parish_ministries":
        rows = db.parish_ministries_report()
        headers = ["Ministeur", "Itorero", "Umuyobozi", "Abakristo"]
        out = []
        for mn in rows:
            out.append([mn.get("name", ""), mn.get("church_name", ""),
                        mn.get("leader", ""), mn.get("member_count", 0)])
        return headers, out, "Ama ministeur yose"
    if resource == "members_by_category":
        agg = db.parish_members_by_category()
        headers = ["Itorero"] + list(agg["totals"].keys()) + ["Igiteranyo"]
        out = []
        for name, cats in agg["by_church"].items():
            row = [name]
            total = 0
            for cat in agg["totals"].keys():
                cnt = cats.get(cat, 0)
                row.append(cnt)
                total += cnt
            row.append(total)
            out.append(row)
        # totals row
        tot_row = ["IGITERANYO"] + list(agg["totals"].values()) + [agg["grand_total"]]
        out.append(tot_row)
        return headers, out, "Abakristo mu byiciro"
    # V1.9 — additional export resources (no keyword/placeholder anywhere)
    if resource == "discipline":
        rows = db.list_discipline()
        headers = ["Izina", "Itorero", "Ubwoko", "Status", "Impamvu",
                   "Igihe cyo gutangiza", "Uwatangije"]
        out = []
        for d in rows:
            out.append([d.get("member_name", ""),
                        d.get("church_name", "") or "",
                        d.get("discipline_type", ""),
                        d.get("status", ""),
                        d.get("reason", ""),
                        (d.get("created_at", "") or "")[:10],
                        d.get("raised_by_name", "")])
        return headers, out, "Abahawe inzira (Discipline)"
    if resource == "delegations":
        rows = db.list_delegations(active_only=False)
        headers = ["Uwatanze", "Uwahawe", "Feature", "Impamvu",
                   "Igihe cyo gutangiza", "Igihe cyo kurangiza", "Status"]
        out = []
        for d in rows:
            out.append([d.get("delegated_by_name", ""),
                        d.get("delegate_name", ""),
                        d.get("feature", ""),
                        d.get("reason", ""),
                        (d.get("created_at", "") or "")[:10],
                        (d.get("end_date", "") or "")[:10],
                        d.get("status", "")])
        return headers, out, "Ubuhawe (Delegations)"
    if resource == "budgets":
        rows = db.list_church_budgets()
        headers = ["Itorero", "Igihe (Icyumweru)", "Igiteranyo cyagenwe",
                   "Uwabishize"]
        out = []
        for b in rows:
            c = db.find_church(b.get("church_id", ""))
            u = db.find_user_by_id(b.get("set_by", "")) if b.get("set_by") else None
            out.append([c.get("name", "") if c else "",
                        b.get("week_date", ""),
                        b.get("amount", 0),
                        (u.get("name", "") if u else "")])
        return headers, out, "Ingengo z'amafaranga (Budgets)"
    if resource == "ministries":
        rows = db.list_ministries()
        headers = ["Ministeur", "Umuyobozi", "Telefone",
                   "Biheruka", "Abakristo"]
        out = []
        for m in rows:
            mm = db.list_member_ministries(ministry_id=m.get("id", ""))
            out.append([m.get("name", ""),
                        m.get("leader_name", ""),
                        m.get("leader_phone", ""),
                        "Yego" if m.get("active") else "Oya",
                        len(mm)])
        return headers, out, "Ama ministeur (Ministries)"
    if resource == "documents":
        rows = db.list_documents()
        headers = ["Umutwe", "Itorero", "Uwatanzwe", "Status",
                   "Igihe cyo gutangiza"]
        out = []
        for d in rows:
            out.append([d.get("title", ""),
                        d.get("church_name", "") or "",
                        d.get("submitted_by_name", ""),
                        d.get("status", ""),
                        (d.get("created_at", "") or "")[:10]])
        return headers, out, "Inyandiko (Documents)"
    if resource == "zones":
        rows = db.list_zones()
        headers = ["Zone", "Itorero", "Umuyobozi wa zone", "Abakristo"]
        out = []
        for z in rows:
            c = db.find_church(z.get("church_id", ""))
            out.append([z.get("name", ""),
                        c.get("name", "") if c else "",
                        z.get("reader_name", ""),
                        z.get("member_count", 0)])
        return headers, out, "Ibice (Zones)"
    if resource == "activity_log":
        rows = db.list_activity(limit=500)
        headers = ["Icyabaye", "Itorero", "Uwabikoze", "Igihe", "Ibisobanuro"]
        out = []
        for a in rows:
            c = db.find_church(a.get("church_id", ""))
            out.append([a.get("action", ""),
                        c.get("name", "") if c else "",
                        a.get("actor_name", ""),
                        (a.get("ts", "") or "")[:16],
                        (a.get("detail", "") or "")[:120]])
        return headers, out, "Ibyabaye (Activity log)"
    if resource == "message_queue":
        rows = db.list_message_queue(limit=500)
        headers = ["Channel", "Uwoherejwe kuri", "Umutwe", "Status",
                   "Uwatanzwe", "Igihe"]
        out = []
        for q in rows:
            out.append([q.get("channel", ""),
                        q.get("to", ""),
                        q.get("subject", ""),
                        q.get("status", ""),
                        q.get("created_by_name", ""),
                        (q.get("created_at", "") or "")[:16]])
        return headers, out, "Ubutumwa butegereje (Message queue)"
    if resource == "pending_users":
        rows = db.list_pending_users()
        headers = ["Izina", "Username", "Role", "Itorero", "Igihe cyo kwiyandikisha"]
        out = []
        for u in rows:
            c = db.find_church(u.get("church_id", ""))
            out.append([u.get("name", ""),
                        u.get("username", ""),
                        u.get("role", ""),
                        c.get("name", "") if c else "",
                        (u.get("created_at", "") or "")[:10]])
        return headers, out, "Konti zitegewe kwemezwa (Pending users)"
    if resource == "rankings":
        rows = db.rankings()
        headers = ["Rank", "Itorero", "Amaturo yose", "Abihannye",
                   "Abana", "Abagarutse", "Umuyobozi", "Telefone"]
        out = []
        for r in rows:
            out.append([r.get("rank", ""),
                        r.get("name", ""),
                        r.get("total", 0),
                        r.get("abihannye", 0),
                        r.get("abana", 0),
                        r.get("abagarutse", 0),
                        r.get("leader_name", ""),
                        r.get("leader_phone", "")])
        return headers, out, "Uruhare w'amatorero (Rankings)"
    return [], [], "Unknown resource"


def _build_xlsx(headers, rows, title, sheet_name="Data"):
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]
    # Title row
    ws.cell(1, 1, title).font = Font(bold=True, size=14, color="1F3864")
    ws.merge_cells(start_row=1, start_column=1,
                   end_row=1, end_column=max(len(headers), 1))
    # Header row
    for ci, h in enumerate(headers, start=1):
        c = ws.cell(3, ci, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")
        c.alignment = Alignment(horizontal="center", vertical="center")
    # Data rows
    for ri, row in enumerate(rows, start=4):
        for ci, val in enumerate(row, start=1):
            ws.cell(ri, ci, val)
    # Column widths
    for ci, h in enumerate(headers, start=1):
        ws.column_dimensions[openpyxl_col(ci)].width = max(12, len(str(h)) + 4)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def openpyxl_col(n):
    from openpyxl.utils import get_column_letter
    return get_column_letter(n)


def _build_pdf(headers, rows, title):
    """A simple landscape PDF table with the Noto fonts for Kinyarwanda."""
    import io
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                     Paragraph, Spacer)
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        pdfmetrics.registerFont(TTFont("NotoSans", "/usr/share/fonts/truetype/chinese/NotoSansSC-Regular.ttf"))
        body_font = "NotoSans"
    except Exception:
        body_font = "Helvetica"
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("t", parent=styles["Title"], fontName=body_font,
                                 fontSize=16, textColor=colors.HexColor("#1F3864"),
                                 alignment=TA_CENTER, spaceAfter=12)
    cell_style = ParagraphStyle("c", parent=styles["BodyText"], fontName=body_font,
                                 fontSize=8, leading=10)
    head_style = ParagraphStyle("h", parent=cell_style, fontName=body_font,
                                 fontSize=8, leading=10, textColor=colors.white)
    data = [[Paragraph(str(h), head_style) for h in headers]]
    for row in rows:
        data.append([Paragraph(str(v), cell_style) for v in row])
    # V1.23 — compute column widths from the real usable page width so the
    # table fills the page instead of being stuck at 11cm total (which left
    # wide reports cramped and lots of empty space on the right).
    page_w, _ = landscape(A4)
    usable_w = page_w - 2 * (1 * 2.54) * cm   # left + right margins (inches→cm)
    n = max(len(headers), 1)
    col_w = [usable_w / n] * n
    t = Table(data, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F2F4F8")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=1*2.54, rightMargin=1*2.54,
                            topMargin=1.2*2.54, bottomMargin=1.2*2.54)
    elems = [Paragraph(title, title_style), Spacer(1, 6), t]
    doc.build(elems)
    buf.seek(0)
    return buf


@app.route("/api/export/<resource>.<fmt>", methods=["GET"])
@require_auth
def api_export_resource(resource, fmt):
    if fmt not in ("xlsx", "pdf"):
        return jsonify({"error": "Format yemewe: xlsx cyangwa pdf"}), 400
    headers, rows, title = _export_rows(resource)
    if not headers:
        return jsonify({"error": "Resource ntabwo yemewe: " + resource}), 400
    try:
        if fmt == "xlsx":
            buf = _build_xlsx(headers, rows, title, sheet_name=title[:31])
            resp = make_response(buf.read())
            resp.headers["Content-Type"] = \
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            resp.headers["Content-Disposition"] = \
                f"attachment; filename={resource}_export.xlsx"
        else:
            buf = _build_pdf(headers, rows, title)
            resp = make_response(buf.read())
            resp.headers["Content-Type"] = "application/pdf"
            resp.headers["Content-Disposition"] = \
                f"attachment; filename={resource}_export.pdf"
        return resp
    except Exception:
        return jsonify({"error": traceback.format_exc()[-500:]}), 500


# ----- Message queue -----
@app.route("/api/message-queue", methods=["GET"])
@require_auth
def api_message_queue_list():
    status = request.args.get("status")
    channel = request.args.get("channel")
    rows = db.list_message_queue(status=status, channel=channel)
    # Church-scoped roles only see their own church's queue; parish sees all.
    u = request._user
    if u.get("role") in ("CHURCH_PASTOR", "CHURCH_FINANCE", "MINISTRY_LEADER", "ZONE_READER") \
            and u.get("church_id"):
        rows = [r for r in rows if r.get("church_id") == u.get("church_id")]
    return jsonify(rows)


@app.route("/api/message-queue", methods=["POST"])
@require_auth
def api_message_queue_enqueue():
    """Queue a message for later delivery (auto-sent when online)."""
    data = request.get_json(silent=True) or {}
    u = request._user
    rec, err = db.enqueue_message({
        "channel": data.get("channel", "sms"),
        "to": data.get("to", ""),
        "subject": data.get("subject", ""),
        "body": data.get("body", ""),
        "church_id": u.get("church_id", ""),
        "created_by": u.get("id", ""),
        "created_by_name": u.get("name", ""),
    })
    if err:
        return jsonify({"error": err}), 400
    # Try to flush immediately so the user gets fast feedback.
    try:
        import scheduler
        scheduler.process_queue()
    except Exception:
        pass
    return jsonify(rec), 201


@app.route("/api/message-queue/process", methods=["POST"])
@require_parish
def api_message_queue_process():
    """Manually trigger the queue processor (parish pastor)."""
    try:
        import scheduler
        return jsonify(scheduler.process_queue())
    except Exception:
        return jsonify({"error": traceback.format_exc()[-500:]}), 500


@app.route("/api/message-queue/stats", methods=["GET"])
@require_auth
def api_message_queue_stats():
    return jsonify(db.queue_stats())


# ----- Email reports -----
@app.route("/api/email-reports", methods=["GET"])
@require_auth
def api_email_reports_list():
    return jsonify(db.list_email_reports())


@app.route("/api/email-reports/send", methods=["POST"])
@require_parish
def api_email_reports_send():
    """Manually trigger the weekly report mail-out (parish pastor)."""
    try:
        import scheduler
        return jsonify(scheduler.send_weekly_reports(trigger="manual"))
    except Exception:
        return jsonify({"error": traceback.format_exc()[-500:]}), 500


@app.route("/api/email-reports/test", methods=["POST"])
@require_parish
def api_email_reports_test():
    """Send a test email to verify SMTP works."""
    data = request.get_json(silent=True) or {}
    to = (data.get("to") or "").strip()
    if not to:
        return jsonify({"error": "Andika email yo kugezaho."}), 400
    try:
        import scheduler
        ok, err = scheduler._send_email(
            to, "Test — ADEPR MIS",
            "Iyi email ni ukugira ngo twemeze ko SMTP ikora neza.\n\n— ADEPR MIS")
        if not ok:
            return jsonify({"error": err}), 400
        db.log_email_report({
            "church_id": "", "church_name": "TEST",
            "recipient": to, "subject": "Test — ADEPR MIS",
            "period": "test", "status": "sent", "trigger": "manual",
        })
        return jsonify({"ok": True, "message": "Test email yoherejwe."})
    except Exception:
        return jsonify({"error": traceback.format_exc()[-500:]}), 500


# ----- System health + settings -----
@app.route("/api/system/health", methods=["GET"])
@require_auth
def api_system_health():
    return jsonify(db.system_health())


@app.route("/api/system/settings", methods=["GET"])
@require_parish
def api_system_settings_get():
    return jsonify(db.load_system_settings())


@app.route("/api/system/settings", methods=["POST"])
@require_parish
def api_system_settings_save():
    data = request.get_json(silent=True) or {}
    cur = db.save_system_settings(data)
    return jsonify(cur)


# ==================================================================
# V1.7 EXPANSION — zones, church assets, file upload, service-request
# attachments + escalation, activity log (bottom-up monitoring).
# ==================================================================

# ----- File upload (shared by service requests + assets) -----
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
ALLOWED_EXT = {"pdf", "jpg", "jpeg", "png", "gif", "webp", "doc", "docx", "xls", "xlsx"}
MAX_UPLOAD = 10 * 1024 * 1024  # 10 MB


@app.route("/api/upload", methods=["POST"])
@require_auth
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "Nta file yoherejwe."}), 400
    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"error": "File ntabwo ihari."}), 400
    ext = (f.filename.rsplit(".", 1)[-1] or "").lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": "Ubwoko bwa file ntabwo bwemewe. Emewe: "
                       + ", ".join(sorted(ALLOWED_EXT))}), 400
    data = f.read()
    if len(data) > MAX_UPLOAD:
        return jsonify({"error": "File nunini cyane (max 10MB)."}), 400
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    stored = db._new_id("F") + "." + ext
    with open(os.path.join(UPLOAD_DIR, stored), "wb") as out:
        out.write(data)
    orig = (f.filename or stored)[:120]
    return jsonify({"ok": True, "path": stored,
                    "original_name": orig, "size": len(data)})


# V1.15: Attach a proof file to an ALREADY-SAVED offering item. The church
# finance user may have saved an offering without a MoMo/bank slip and now
# wants to add it after the fact (instead of re-recording the whole week).
# Accepts the item_id (so the proof lands on the right category row), the
# uploaded file path (from /api/upload), and optional kind. Returns the
# updated item.
@app.route("/api/my-offerings/items/<item_id>/attachments", methods=["POST"])
@require_auth
def api_offering_item_attach(item_id):
    user = request._user
    role = (user.get("role") or "").upper()
    if role not in ("CHURCH_PASTOR", "CHURCH_FINANCE", "PARISH_PASTOR",
                    "PARISH_MANAGER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"error": "path ya file irakenewe (bwa /api/upload)."}), 400
    original_name = (data.get("original_name") or path)[:120]
    size = data.get("size", 0)
    cat_hint = (data.get("category") or "").upper()
    kind = (data.get("kind") or "").lower()
    if kind not in ("momo_sms", "bank_slip", "other"):
        kind = ("momo_sms" if cat_hint == "ICYACUMI_MOMO"
                else "bank_slip" if cat_hint == "ICYACUMI_BANK"
                else "other")
    rows = db._read_tab(db.ITEMS_TAB)
    target = None
    for r in rows:
        if r.get("id") == item_id:
            target = r
            break
    if not target:
        return jsonify({"error": "Icyemezo (item) ntabonetse."}), 404
    # Ownership: the offering must belong to the user's church (church
    # pastor/finance) OR the user is parish-level (oversight). We look up
    # the offering row to get church_id.
    off_rows = db._read_tab(db.OFFERINGS_TAB)
    off = next((o for o in off_rows if o.get("id") == target.get("offering_id")), None)
    if off:
        if role in ("CHURCH_PASTOR", "CHURCH_FINANCE") \
                and off.get("church_id") != user.get("church_id"):
            return jsonify({"error": "Ntibyemewe — item ntabwo iy'itorero ryawe."}), 403
    atts = target.get("attachments") or []
    atts.append({
        "path": path,
        "original_name": original_name,
        "kind": kind,
        "size": int(size or 0),
        "uploaded_at": db._now_iso(),
    })
    target["attachments"] = atts
    # Clearing the no_proof flag: adding a proof attachment means the row
    # is now backed by evidence.
    target["no_proof"] = False
    db._write_tab(db.ITEMS_TAB, rows)
    db._invalidate(db.ITEMS_TAB)
    db._invalidate(db.OFFERINGS_TAB)
    return jsonify({"ok": True, "item": target})


@app.route("/uploads/<path:fname>")
@require_auth
def serve_upload(fname):
    # prevent path traversal
    base = os.path.basename(fname)
    full = os.path.join(UPLOAD_DIR, base)
    if not os.path.isfile(full):
        return jsonify({"error": "File ntabwo ibonetse."}), 404
    return send_from_directory(UPLOAD_DIR, base)


# ----- Zones -----
@app.route("/api/zones", methods=["GET"])
@require_auth
def api_zones_list():
    church_id = request.args.get("church_id")
    u = request._user
    # zone readers see only their church; others as allowed by role
    if u.get("role") == "ZONE_READER":
        church_id = u.get("church_id")
    return jsonify(db.list_zones(church_id=church_id))


@app.route("/api/zones", methods=["POST"])
@require_church_or_finance
def api_zones_create():
    data = request.get_json(silent=True) or {}
    u = request._user
    rec = db.create_zone({
        "church_id": u.get("church_id", ""),
        "name": data.get("name", ""),
        "reader_id": data.get("reader_id", ""),
        "reader_name": data.get("reader_name", ""),
        "description": data.get("description", ""),
    })
    if not rec:
        return jsonify({"error": "Izina rya zone n'itorero birakenewe."}), 400
    return jsonify(rec), 201


@app.route("/api/zones/<zid>", methods=["DELETE"])
@require_church_or_finance
def api_zones_delete(zid):
    u = request._user
    z = next((z for z in db.list_zones(church_id=u.get("church_id", ""))
              if z.get("id") == zid), None)
    if not z:
        return jsonify({"error": "Zone ntabwo ibonetse muri iki gitorero."}), 404
    return jsonify(db.delete_zone(zid))


# ----- Church assets (imitungi) -----
@app.route("/api/assets", methods=["GET"])
@require_auth
def api_assets_list():
    u = request._user
    church_id = request.args.get("church_id")
    category = request.args.get("category")
    if u.get("role") in ("CHURCH_PASTOR", "CHURCH_FINANCE", "MINISTRY_LEADER",
                         "ZONE_READER"):
        church_id = u.get("church_id", "")
    return jsonify(db.list_assets(church_id=church_id, category=category))


@app.route("/api/assets/summary", methods=["GET"])
@require_parish_or_manager
def api_assets_summary():
    return jsonify(db.asset_value_summary())


@app.route("/api/assets", methods=["POST"])
@require_church_or_finance
def api_assets_create():
    data = request.get_json(silent=True) or {}
    u = request._user
    rec = db.insert_asset({
        "church_id": u.get("church_id", ""),
        "name": data.get("name", ""),
        "category": data.get("category", "IBINDI"),
        "value": data.get("value", 0),
        "quantity": data.get("quantity", 1),
        "description": data.get("description", ""),
        "acquired_date": data.get("acquired_date", ""),
        "doc_paths": data.get("doc_paths", []),
        "status": data.get("status", "ACTIVE"),
        "created_by": u.get("id", ""),
        "created_by_name": u.get("name", ""),
    })
    if not rec:
        return jsonify({"error": "Izina ry'ikintu n'itorero birakenewe."}), 400
    db.log_activity({
        "actor_id": u.get("id", ""), "actor_name": u.get("name", ""),
        "actor_role": u.get("role", ""),
        "church_id": u.get("church_id", ""),
        "action": "ASSET_ADDED", "target": rec.get("name", ""),
        "detail": f"{rec.get('category','')} • {rec.get('value',0)} RWF",
        "scope": "church",
    })
    return jsonify(rec), 201


@app.route("/api/assets/<aid>", methods=["PUT"])
@require_church_or_finance
def api_assets_update(aid):
    data = request.get_json(silent=True) or {}
    rec = db.update_asset(aid, data)
    if not rec:
        return jsonify({"error": "Ikintu ntabwo kibonetse."}), 404
    return jsonify(rec)


@app.route("/api/assets/<aid>", methods=["DELETE"])
@require_church_or_finance
def api_assets_delete(aid):
    return jsonify(db.delete_asset(aid))


@app.route("/api/assets/<aid>/decision", methods=["POST"])
@require_parish_or_manager
def api_assets_decision(aid):
    """Parish pastor / manager records a decision on a church asset,
    which notifies the church leaders and logs an activity entry."""
    data = request.get_json(silent=True) or {}
    decision = (data.get("decision") or "").upper()
    if decision not in db.ASSET_DECISIONS:
        return jsonify({"error": "Umwanzuro yemewe: " + ", ".join(db.ASSET_DECISIONS)}), 400
    u = request._user
    rec = db.asset_decision(aid, decision, data.get("note", ""),
                            u.get("id", ""), u.get("name", ""))
    if not rec:
        return jsonify({"error": "Ikintu ntabwo kibonetse."}), 404
    return jsonify(rec)


# ----- Service requests: attachments + escalation chain -----
@app.route("/api/service-requests/<rid>/attachments", methods=["POST"])
@require_auth
def api_sr_attachments(rid):
    data = request.get_json(silent=True) or {}
    paths = data.get("doc_paths", [])
    if not isinstance(paths, list):
        return jsonify({"error": "doc_paths igomba kuba list."}), 400
    rec = db.add_request_attachments(rid, paths)
    if not rec:
        return jsonify({"error": "Igisabye ntabwo kibonetse."}), 404
    return jsonify(rec)


@app.route("/api/service-requests/<rid>/escalate", methods=["POST"])
@require_auth
def api_sr_escalate(rid):
    """Move a service request one step up the chain (zone → ministry →
    church → parish). Any authenticated role in the chain can escalate."""
    data = request.get_json(silent=True) or {}
    u = request._user
    rec = db.escalate_service_request(rid, u.get("id", ""), u.get("name", ""),
                                      u.get("role", ""),
                                      data.get("note", ""))
    if not rec:
        return jsonify({"error": "Igisabye ntabwo kibonetse."}), 404
    return jsonify(rec)


# ----- Activity log (bottom-up monitoring feed) -----
@app.route("/api/activity-log", methods=["GET"])
@require_auth
def api_activity_log():
    u = request._user
    church_id = request.args.get("church_id")
    scope = request.args.get("scope")
    actions = request.args.get("actions")
    actions_list = actions.split(",") if actions else None
    # parish-level roles see everything; church-level see their church;
    # zone reader sees only their church's zone-scoped activity.
    if u.get("role") in ("CHURCH_PASTOR", "CHURCH_FINANCE",
                         "MINISTRY_LEADER", "ZONE_READER"):
        church_id = u.get("church_id", "")
    return jsonify(db.list_activity(church_id=church_id, scope=scope,
                                    actions=actions_list))


# ==================================================================
# V1.8 EXPANSION — free-text church creation, visitors report,
# member discipline + suspension, parish delegation, parish-wide
# member-by-category + ministries aggregators.
# ==================================================================

# ----- Free-text church search + create (modular forms) -----
@app.route("/api/churches/search", methods=["GET"])
@require_auth
def api_churches_search():
    q = request.args.get("q", "")
    return jsonify(db.search_churches(q))


@app.route("/api/churches/find-or-create", methods=["POST"])
@require_auth
def api_churches_find_or_create():
    data = request.get_json(silent=True) or {}
    rec = db.find_or_create_church(data.get("name", ""),
                                   data.get("parish", ""))
    if not rec:
        return jsonify({"error": "Izina ry'itorero irakenewe."}), 400
    return jsonify(rec)


# ----- Visitors (church enters, parish sees all) -----
@app.route("/api/visitors", methods=["GET"])
@require_auth
def api_visitors_list():
    u = request._user
    church_id = request.args.get("church_id")
    week_date = request.args.get("week_date")
    if u.get("role") in ("CHURCH_PASTOR", "CHURCH_FINANCE", "MINISTRY_LEADER",
                         "ZONE_READER"):
        church_id = u.get("church_id", "")
    return jsonify(db.list_visitors(church_id=church_id, week_date=week_date))


@app.route("/api/visitors", methods=["POST"])
@require_church_or_finance
def api_visitors_create():
    data = request.get_json(silent=True) or {}
    u = request._user
    rec = db.insert_visitor({
        "church_id": u.get("church_id", ""),
        "name": data.get("name", ""),
        "phone": data.get("phone", ""),
        "gender": data.get("gender", ""),
        "week_date": data.get("week_date", ""),
        "goal_taught": data.get("goal_taught", ""),
        "address": data.get("address", ""),
        "photo": data.get("photo", ""),
        "certificate": data.get("certificate", ""),
        "notes": data.get("notes", ""),
        "status": data.get("status", "VISITED"),
        "entered_by": u.get("id", ""),
        "entered_by_name": u.get("name", ""),
        "actor_role": u.get("role", ""),
    })
    if not rec:
        return jsonify({"error": "Izina n'itorero birakenewe."}), 400
    return jsonify(rec), 201


@app.route("/api/visitors/<vid>", methods=["PUT"])
@require_church_or_finance
def api_visitors_update(vid):
    data = request.get_json(silent=True) or {}
    rec = db.update_visitor(vid, data)
    if not rec:
        return jsonify({"error": "Ntabonetse."}), 404
    return jsonify(rec)


@app.route("/api/visitors/<vid>", methods=["DELETE"])
@require_church_or_finance
def api_visitors_delete(vid):
    return jsonify(db.delete_visitor(vid))


# ----- Discipline (raise → parish confirm → lift; logged + notified) -----
@app.route("/api/discipline", methods=["GET"])
@require_auth
def api_discipline_list():
    u = request._user
    church_id = request.args.get("church_id")
    status = request.args.get("status")
    if u.get("role") in ("CHURCH_PASTOR", "CHURCH_FINANCE",
                         "MINISTRY_LEADER", "ZONE_READER"):
        church_id = u.get("church_id", "")
    return jsonify(db.list_discipline(church_id=church_id, status=status))


@app.route("/api/discipline", methods=["POST"])
@require_auth
def api_discipline_create():
    """Church pastor / ministry leader / zone reader raises a discipline
    case. It escalates up to the parish pastor for confirmation."""
    u = request._user
    if u.get("role") not in ("CHURCH_PASTOR", "CHURCH_FINANCE",
                              "MINISTRY_LEADER", "ZONE_READER",
                              "PARISH_PASTOR", "PARISH_MANAGER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    data = request.get_json(silent=True) or {}
    rec = db.insert_discipline({
        "member_id": data.get("member_id", ""),
        "member_name": data.get("member_name", ""),
        "church_id": data.get("church_id") or u.get("church_id", ""),
        "discipline_type": data.get("discipline_type", "WARNING"),
        "reason": data.get("reason", ""),
        "action_taken": data.get("action_taken", ""),
        "certificate": data.get("certificate", ""),
        "raised_by": u.get("id", ""),
        "raised_by_name": u.get("name", ""),
        "raised_by_role": u.get("role", ""),
    })
    if not rec:
        return jsonify({"error": "Umukristo n'itorero birakenewe."}), 400
    return jsonify(rec), 201


@app.route("/api/discipline/<did>/confirm", methods=["POST"])
@require_parish_or_manager
def api_discipline_confirm(did):
    data = request.get_json(silent=True) or {}
    u = request._user
    rec = db.confirm_discipline(did, u, data.get("note", ""))
    if not rec:
        return jsonify({"error": "Ntabonetse."}), 404
    return jsonify(rec)


@app.route("/api/discipline/<did>/lift", methods=["POST"])
@require_parish_or_manager
def api_discipline_lift(did):
    data = request.get_json(silent=True) or {}
    u = request._user
    rec = db.lift_discipline(did, u, data.get("note", ""))
    if not rec:
        return jsonify({"error": "Ntabonetse."}), 404
    return jsonify(rec)


# ----- Delegations (parish pastor grants features temporarily) -----
@app.route("/api/delegations", methods=["GET"])
@require_auth
def api_delegations_list():
    active = request.args.get("active") == "1"
    return jsonify(db.list_delegations(active_only=active))


@app.route("/api/delegations", methods=["POST"])
@require_parish_or_manager
def api_delegations_create():
    data = request.get_json(silent=True) or {}
    u = request._user
    rec = db.insert_delegation({
        "delegate_name": data.get("delegate_name", ""),
        "delegate_role": data.get("delegate_role", ""),
        "delegate_user_id": data.get("delegate_user_id", ""),
        "church_id": data.get("church_id", ""),
        "feature": data.get("feature", ""),
        "reason": data.get("reason", ""),
        "start_date": data.get("start_date", ""),
        "end_date": data.get("end_date", ""),
        "delegated_by": u.get("id", ""),
        "delegated_by_name": u.get("name", ""),
    })
    if not rec:
        return jsonify({"error": "Izina n'ikintu cyo delegatera birakenewe."}), 400
    return jsonify(rec), 201


@app.route("/api/delegations/<dlg_id>/revoke", methods=["POST"])
@require_parish_or_manager
def api_delegations_revoke(dlg_id):
    u = request._user
    rec = db.revoke_delegation(dlg_id, u)
    if not rec:
        return jsonify({"error": "Ntabonetse."}), 404
    return jsonify(rec)


# ----- Parish-wide aggregators (parish dashboard) -----
@app.route("/api/parish/members-by-category", methods=["GET"])
@require_parish_or_manager
def api_parish_members_by_category():
    return jsonify(db.parish_members_by_category())


@app.route("/api/parish/ministries", methods=["GET"])
@require_parish_or_manager
def api_parish_ministries():
    return jsonify(db.parish_ministries_report())



@app.route("/api/system/reset", methods=["POST"])
@require_parish
def api_system_reset():
    data = request.get_json(silent=True) or {}
    if (data.get("confirm") or "").strip().upper() != "RESET":
        return jsonify({"error": 'Ohereza {"confirm":"RESET"} ngo ukome.'}), 400
    # Per-member-category reset (e.g. wipe only ABAKRISTO_BASHYA)
    if data.get("member_category"):
        return jsonify({"ok": True,
                        "result": db.reset_members_by_category(data["member_category"])})
    targets = data.get("targets") or ["all"]
    if isinstance(targets, str):
        targets = [targets]
    valid = {"churches", "members", "ministries", "offerings",
             "budgets", "notifications", "documents",
             "service_requests", "death_reports", "schedules",
             "announcements", "users", "all"}
    bad = [t for t in targets if t not in valid]
    if bad:
        return jsonify({"error": f"Targets ntibizwi: {bad}"}), 400
    summary = db.reset_all_system(keep_admin_id=request._user["id"], targets=targets)
    return jsonify({"ok": True, "summary": summary})


# ##################################################################
# V1.18 — "Siba yose" (clear-all) endpoints
#   Parish pastor can wipe everything; a church pastor is scoped to
#   their own church for members + messages. Churches clear-all is
#   parish-only (a church pastor only ever owns one church).
# ##################################################################
@app.route("/api/members/clear-all", methods=["POST"])
@require_parish_or_church_pastor_or_zone
def api_members_clear_all():
    user = request._user
    role = user.get("role", "")
    # Church pastors are forced to their own church; parish pastors wipe all;
    # zone readers are scoped to their own zone only.
    church_id = user.get("church_id") if role == "CHURCH_PASTOR" else None
    zone_id = user.get("zone_id") if role == "ZONE_READER" else None
    if role == "CHURCH_PASTOR" and not church_id:
        return jsonify({"error": "Konti yawe ntabwo iyobewe itorero."}), 400
    if role == "ZONE_READER" and not zone_id:
        return jsonify({"error": "Konti yawe ntabwo iyobewe zone."}), 400
    # V1.21 — optional category filter (for per-category delete-all).
    category = (request.args.get("category") or "").strip() or None
    result = db.clear_all_members(church_id=church_id, category=category,
                                  zone_id=zone_id)
    return jsonify({"ok": True, "result": result})


@app.route("/api/churches/clear-all", methods=["POST"])
@require_parish
def api_churches_clear_all():
    result = db.clear_all_churches()
    return jsonify({"ok": True, "result": result})


@app.route("/api/messages/clear-all", methods=["POST"])
@require_parish_or_church_pastor
def api_messages_clear_all():
    user = request._user
    church_id = user.get("church_id") if user.get("role") == "CHURCH_PASTOR" else None
    if not church_id and user.get("role") == "CHURCH_PASTOR":
        return jsonify({"error": "Konti yawe ntabwo iyobewe itorero."}), 400
    result = db.clear_all_sent_messages(church_id=church_id)
    return jsonify({"ok": True, "result": result})


@app.route("/api/users/clear-all", methods=["POST"])
@require_parish
def api_users_clear_all():
    """V1.21 — Delete all users of a given role (or all if no role filter).
    Never deletes the currently-logged-in parish account."""
    role = (request.args.get("role") or "").upper() or None
    rows = db.list_users(active_only=False)
    me = request._user.get("id")
    targets = [u for u in rows if u.get("id") != me]
    if role:
        targets = [u for u in targets if (u.get("role") or "").upper() == role]
    deleted = 0
    for u in targets:
        if db.delete_user_hard(u.get("id")):
            deleted += 1
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/api/assets/clear-all", methods=["POST"])
@require_parish_or_church_pastor
def api_assets_clear_all():
    """V1.21 — Delete all assets. Church pastors scoped to own church."""
    user = request._user
    church_id = user.get("church_id") if user.get("role") == "CHURCH_PASTOR" else None
    if not church_id and user.get("role") == "CHURCH_PASTOR":
        return jsonify({"error": "Konti yawe ntabwo iyobewe itorero."}), 400
    removed = db.clear_all_assets(church_id=church_id)
    return jsonify({"ok": True, "deleted": removed})


@app.route("/api/schedules/clear-all", methods=["POST"])
@require_auth
def api_schedules_clear_all():
    """V1.21 — Delete all schedules. Non-parish roles scoped to own creations."""
    user = request._user
    role = (user.get("role") or "").upper()
    if role in ("PARISH_PASTOR", "PARISH_MANAGER"):
        removed = db.clear_all_schedules()
    else:
        removed = db.clear_all_schedules(scheduled_by=user.get("id"))
    return jsonify({"ok": True, "deleted": removed})


# ##################################################################
# V1.13 — Per-role enhancements
#   * profile editing for ALL roles (name/phone/email/photo, reflects
#     immediately via session refresh)
#   * member deletion requests (zone/ministry → church pastor approve)
#   * manager change-request gate (read-only writes become approval
#     requests when no delegation is active)
#   * Tracar SMS gateway config + test
#   * thank-you SMS log + send
#   * service-request escalation + delegation
#   * reception overview (parish) — requests/approved/baptized
#   * schedules accept a `category` (group events by category)
# ##################################################################
import db_v13 as v13


# ---------- Profile (all roles) ----------
@app.route("/api/me/profile", methods=["PUT"])
@require_auth
def api_me_profile_update():
    """Self-service profile edit for every role: name, phone, email,
    photo (base64). Changes reflect immediately on the page because the
    client refreshes the session after a 200."""
    user = request._user
    data = request.get_json(silent=True) or {}
    photo = data.get("photo", "")
    if isinstance(photo, str) and len(photo) > 600_000:
        return jsonify({"error": "Ifoto ni nnini cyane (max 600KB base64)."}), 400
    updated = v13.update_user_profile(user["id"], data)
    if not updated:
        return jsonify({"error": "Byanze."}), 500
    return jsonify({"ok": True, "user": updated})


# ---------- Member deletion requests ----------
@app.route("/api/deletion-requests", methods=["GET"])
@require_auth
def api_deletion_requests_list():
    user = request._user
    status = request.args.get("status")
    cid = user.get("church_id") or ""
    role = (user.get("role") or "").upper()
    if role in ("PARISH_PASTOR", "PARISH_MANAGER"):
        cid = request.args.get("church_id") or ""
    elif not cid:
        return jsonify([])
    return jsonify(v13.list_deletion_requests(church_id=cid or None, status=status))


@app.route("/api/deletion-requests", methods=["POST"])
@require_auth
def api_deletion_requests_submit():
    """Zone reader / ministry leader / church pastor asks to remove a
    member. The member is NOT removed — the church pastor must approve,
    and the requester must give a reason + their signature."""
    user = request._user
    role = (user.get("role") or "").upper()
    if role not in ("ZONE_READER", "MINISTRY_LEADER", "CHURCH_PASTOR",
                    "CHURCH_FINANCE"):
        return jsonify({"error": "Ntibyemewe gusaba gukuramo umukristo."}), 403
    data = request.get_json(silent=True) or {}
    mid = data.get("member_id")
    m = db.find_member(mid) if mid else None
    if not m:
        return jsonify({"error": "Umukristo ntabonetse."}), 404
    if m.get("church_id") != user.get("church_id"):
        return jsonify({"error": "Ntibyemewe kuri uyu mukristo."}), 403
    if not (data.get("reason") or "").strip():
        return jsonify({"error": "Impamvu irakenewe."}), 400
    rec = v13.insert_deletion_request({
        "member_id": mid,
        "requester_id": user["id"],
        "requester_name": user.get("name", ""),
        "requester_role": role,
        "reason": data["reason"],
        "signature": data.get("signature", ""),
    })
    if not rec:
        return jsonify({"error": "Byanze."}), 500
    db.send_notification({
        "sender_id": user["id"],
        "sender_name": user.get("name", ""),
        "sender_role": role,
        "recipient_role": "ALL_CHURCH",
        "church_id": m.get("church_id", ""),
        "title": f"Gusaba gukuramo umukristo: {m.get('name','')}",
        "body": (f"{user.get('name','')} yasabye gukuramo {m.get('name','')} "
                 f"mu itorero. Impamvu: {rec['reason'][:80]}."),
        "category": "service",
    })
    return jsonify(rec), 201


@app.route("/api/deletion-requests/<req_id>/approve", methods=["POST"])
@require_church
def api_deletion_requests_approve(req_id):
    rec = v13.find_deletion_request(req_id)
    if not rec:
        return jsonify({"error": "Isabye ntabonetse."}), 404
    if rec.get("church_id") != request._user.get("church_id"):
        return jsonify({"error": "Ntibyemewe."}), 403
    out = v13.approve_deletion_request(req_id, request._user)
    db.send_notification({
        "sender_id": request._user["id"],
        "sender_name": request._user.get("name", ""),
        "sender_role": request._user.get("role", ""),
        "recipient_role": "PARISH_PASTOR",
        "church_id": rec.get("church_id", ""),
        "title": f"Umukristo yakuwe ho: {rec.get('member_name','')}",
        "body": (f"{rec.get('member_name','')} yakuweho mu itorero "
                 f"— yemejwe na {request._user.get('name','')}."),
        "category": "service",
    })
    return jsonify(out)


@app.route("/api/deletion-requests/<req_id>/reject", methods=["POST"])
@require_church
def api_deletion_requests_reject(req_id):
    data = request.get_json(silent=True) or {}
    rec = v13.find_deletion_request(req_id)
    if not rec:
        return jsonify({"error": "Isabye ntabonetse."}), 404
    if rec.get("church_id") != request._user.get("church_id"):
        return jsonify({"error": "Ntibyemewe."}), 403
    out = v13.reject_deletion_request(req_id, request._user, data.get("feedback", ""))
    return jsonify(out)


# ---------- Manager change-request gate ----------
@app.route("/api/change-requests", methods=["GET"])
@require_parish
def api_change_requests_list():
    status = request.args.get("status")
    feature = request.args.get("feature")
    return jsonify(v13.list_change_requests(status=status, feature=feature))


@app.route("/api/change-requests/probe", methods=["POST"])
@require_parish_manager
def api_change_requests_probe():
    """Manager asks: 'if I try to write feature X, will it be gated?'
    Returns {gated: bool}. Used by the client to show the right button."""
    data = request.get_json(silent=True) or {}
    feature = data.get("feature", "")
    gated = not v13.manager_has_delegation(request._user, feature)
    return jsonify({"gated": gated, "feature": feature})


@app.route("/api/change-requests", methods=["POST"])
@require_parish_manager
def api_change_requests_submit():
    """Manager submits a proposed write as a change request. The parish
    pastor approves it from the manager_changes panel."""
    data = request.get_json(silent=True) or {}
    if not data.get("feature") or not data.get("action"):
        return jsonify({"error": "feature + action birakenewe."}), 400
    rec = v13.insert_change_request({
        "feature": data["feature"],
        "action": data["action"],
        "target_type": data.get("target_type", ""),
        "target_id": data.get("target_id", ""),
        "proposed": data.get("proposed", {}),
        "reason": data.get("reason", ""),
        "requester_id": request._user["id"],
        "requester_name": request._user.get("name", ""),
    })
    db.send_notification({
        "sender_id": request._user["id"],
        "sender_name": request._user.get("name", ""),
        "sender_role": request._user.get("role", ""),
        "recipient_role": "PARISH_PASTOR",
        "title": f"Isabye ryo guhindura: {data['action']} {data.get('target_type','')}",
        "body": (f"{request._user.get('name','')} yasabye {data['action']} "
                 f"{data.get('target_type','')}. Impamvu: {data.get('reason','—')[:80]}."),
        "category": "service",
    })
    return jsonify(rec), 201


@app.route("/api/change-requests/<req_id>/approve", methods=["POST"])
@require_parish
def api_change_requests_approve(req_id):
    rec = v13.find_change_request(req_id)
    if not rec:
        return jsonify({"error": "Isabye ntabonetse."}), 404
    if rec.get("status") != "pending":
        return jsonify({"error": "Isabye ritakomeje."}), 400
    out = v13.approve_change_request(req_id, request._user)
    return jsonify(out)


@app.route("/api/change-requests/<req_id>/reject", methods=["POST"])
@require_parish
def api_change_requests_reject(req_id):
    data = request.get_json(silent=True) or {}
    rec = v13.find_change_request(req_id)
    if not rec:
        return jsonify({"error": "Isabye ntabonetse."}), 404
    out = v13.reject_change_request(req_id, request._user, data.get("feedback", ""))
    return jsonify(out)


# ---------- Tracar SMS gateway config ----------
@app.route("/api/sms-gateway", methods=["GET"])
@require_parish
def api_sms_gateway_get():
    return jsonify(v13.load_sms_gateway())


@app.route("/api/sms-gateway", methods=["PUT"])
@require_parish
def api_sms_gateway_put():
    data = request.get_json(silent=True) or {}
    cur = v13.save_sms_gateway(data)
    # V1.14: Save just flipped the config — if auto_send is now ON and the
    # gateway is live (endpoint + not dry_run), drain the thank-you queue
    # immediately. This is the "anytime gateway ibaye connected" path: the
    # parish pastor doesn't have to wait for the 2-min scheduler tick.
    if cur.get("auto_send_enabled") and not cur.get("dry_run") \
            and cur.get("endpoint"):
        try:
            import scheduler as _sched
            _sched.process_thank_you_queue()
        except Exception:
            pass
    return jsonify({"ok": True, "gateway": cur})


@app.route("/api/sms-gateway/test", methods=["POST"])
@require_parish
def api_sms_gateway_test():
    """Send a test message through the configured Tracar gateway.

    Routes the real send through sms.send_one_sms() — the SAME code path
    production broadcasts and thank-you SMS use — so a passing test means
    a real send will work. Dry-run (or empty endpoint) returns a friendly
    synthetic OK without touching the network.

    The caller may supply a custom test message in the body (`message`);
    if absent we use a sensible default. The gateway's raw HTTP reply is
    recorded so the panel can show exactly what the gateway said — that
    is the key to telling a real send from a silent rejection.
    """
    import sms
    gw = v13.load_sms_gateway()
    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or gw.get("phone") or "").strip()
    endpoint = (gw.get("endpoint") or "").strip()
    default_msg = "[TEST] Traccar SMS gateway test — ADEPR MIS."
    message = (data.get("message") or "").strip() or default_msg
    if not phone:
        rec = v13.record_sms_gateway_test(False, 400, "Namba ya telefone ntabonetse.")
        return jsonify(rec), 400
    if gw.get("dry_run") or not endpoint:
        msg = ("[DRY RUN] Traccar SMS gateway yagenwe neza — nta message igenda. "
               "Kugira ngo igende, kuramo endpoint + token hanyuma usibe dry_run.")
        # Apply the gateway's phone format so the recorded `to` matches what
        # a real send would actually deliver (e.g. +250788… for Traccar).
        to_display = sms._format_phone_for_gateway(
            sms.normalize_phone(phone), gw.get("phone_format", "intl"))
        rec = v13.record_sms_gateway_test(
            True, 200, msg, sent=message, to=to_display,
            request_url=sms._build_send_url(endpoint, gw.get("url_trailing_slash", True)) or "",
            auth_mode=gw.get("auth_mode", "header_raw"),
            http_method=gw.get("http_method", "POST"),
            body_format=gw.get("body_format", "json"),
            phone_format=gw.get("phone_format", "intl"))
        return jsonify(rec)
    # Real send via the production path. dry_run=False forces a network call
    # even if the panel later flips back to dry_run.
    res = sms.send_one_sms(phone, message, dry_run=False)
    rec = v13.record_sms_gateway_test(
        bool(res.get("ok")), int(res.get("status", 0) or 0),
        str(res.get("response", "")),
        sent=message, to=res.get("to", ""),
        request_url=res.get("request_url", ""),
        auth_mode=res.get("auth_mode", gw.get("auth_mode", "header_raw")),
        http_method=res.get("http_method", gw.get("http_method", "POST")),
        body_format=res.get("body_format", gw.get("body_format", "json")),
        phone_format=res.get("phone_format", gw.get("phone_format", "intl")))
    if rec["last_test"]["ok"]:
        # V1.14: Test succeeded → gateway is live. If auto_send_enabled,
        # immediately drain the thank-you queue so any dry_run messages
        # the parish pastor queued earlier fire NOW (no 2-min wait).
        try:
            gw_now = v13.load_sms_gateway()
            if gw_now.get("auto_send_enabled") and not gw_now.get("dry_run") \
                    and gw_now.get("endpoint"):
                import scheduler as _sched
                _sched.process_thank_you_queue()
        except Exception:
            pass
        return jsonify(rec)
    return jsonify(rec), 502


# ---------- Thank-you SMS log + send ----------
@app.route("/api/thank-you-sms", methods=["GET"])
@require_auth
def api_thank_you_sms_list():
    user = request._user
    role = (user.get("role") or "").upper()
    cid = user.get("church_id") or ""
    if role in ("PARISH_PASTOR", "PARISH_MANAGER"):
        cid = request.args.get("church_id") or ""
    return jsonify(v13.list_thank_you_sms(church_id=cid or None))


@app.route("/api/thank-you-sms", methods=["POST"])
@require_auth
def api_thank_you_sms_send():
    """Send (or queue) a thank-you SMS to a church for the offerings
    received on a given week. Uses the Tracar gateway when configured,
    otherwise records a dry_run entry so the audit log is intact."""
    user = request._user
    role = (user.get("role") or "").upper()
    data = request.get_json(silent=True) or {}
    church_id = data.get("church_id") or user.get("church_id") or ""
    if not church_id:
        return jsonify({"error": "Itorero ntiribonetse."}), 400
    if role not in ("PARISH_PASTOR", "PARISH_MANAGER") and \
            church_id != user.get("church_id"):
        return jsonify({"error": "Ntibyemewe."}), 403
    church = db.find_church(church_id)
    church_name = church.get("name", "") if church else ""
    parish_name = (church.get("parish", "") if church else "") or None
    week_date = data.get("week_date", "")
    total = float(data.get("total_offering", 0) or 0)
    recipient_phone = (data.get("recipient_phone")
                       or (church.get("pastor_phone") if church else "")
                       or "").strip()
    recipient_name = (data.get("recipient_name")
                      or (church.get("leader_name") if church else "")
                      or "").strip()
    # Ubutumwa: client ashobora kohereza message ye (override). Bitabaye
    # ibyo, tukora builder ya message2.py-style — yuzuye n'imibare yose,
    # ranking, ijanisha, umugisha — ikomoka kuri db.rankings() ya icyumweru
    # cyo. Iyo data itabonetse (nta offering cyangwa itorero ritabonetse),
    # builder isubiza flat fallback, endpoint ntigereke.
    if data.get("message"):
        message = data["message"]
    else:
        import thank_you_message as _tym
        built = _tym.build(church_id, week_date, parish_name=parish_name)
        message = built["message"]
        # Ubutumwa bwa builder bukorwamo recipient_name (izina) n'itorero.
        # Update recipient_name ukomoka kuri data niba client atayahereje.
        if not recipient_name and built.get("meta", {}).get("izina"):
            recipient_name = built["meta"]["izina"]
        if not recipient_phone:
            # Shake telefone kuva kuri church record (leader_phone).
            recipient_phone = (church.get("leader_phone") if church else "") or ""
    # V1.14: Custom contacts — parish pastor ashobora kohereza kontakte
    # z'inyongera zidahari ku rutonde (extra_contacts: list of {name, phone}).
    # Tubaka recipients = [{name, phone}] kuva kuri leader/recipient + extra.
    extra_contacts = data.get("extra_contacts") or []
    if not isinstance(extra_contacts, list):
        extra_contacts = []
    # Clean: keep only dicts with a non-empty phone.
    extra_contacts = [
        {"name": str(c.get("name", "")).strip(),
         "phone": str(c.get("phone", "")).strip()}
        for c in extra_contacts
        if isinstance(c, dict) and str(c.get("phone", "")).strip()
    ]
    # Primary recipient (leader/pastor) — only included if a phone exists.
    primary = []
    if recipient_phone:
        primary = [{"name": recipient_name or church_name, "phone": recipient_phone}]
    recipients = primary + extra_contacts
    gw = v13.load_sms_gateway()
    status = "dry_run"
    gateway_response = "dry_run (no endpoint or dry_run flag set)"
    send_results = []
    if gw.get("endpoint") and not gw.get("dry_run") and recipients:
        # V1.14: Route through sms.broadcast() so the thank-you SMS reaches
        # ALL recipients (leader + extra_contacts) in one call, with the
        # same auth/param path as a panel broadcast. Previously this used
        # send_one_sms() which only reached one phone.
        import sms as _sms_mod
        bres = _sms_mod.broadcast(recipients, message, dry_run=False)
        send_results = bres.get("results", [])
        if bres.get("sent", 0) > 0 and bres.get("failed", 0) == 0:
            status = "sent"
            gateway_response = (f"broadcast: {bres.get('sent',0)}/{bres.get('total',0)} "
                                f"sent — {bres.get('results', '')}")[:500]
        elif bres.get("sent", 0) > 0:
            status = "sent"
            gateway_response = (f"broadcast partial: {bres.get('sent',0)} sent, "
                                f"{bres.get('failed',0)} failed")[:500]
        else:
            status = "failed"
            gateway_response = (f"broadcast failed (0/{bres.get('total',0)}): "
                                f"{bres.get('results', '')}")[:500]
    elif not recipients:
        status = "failed"
        gateway_response = "no recipients (leader has no phone and no extra_contacts given)"
    # Log: one row per recipient so the panel can show delivery per phone.
    # The first row is returned to the client as the canonical record.
    recs = []
    for idx, r in enumerate(recipients):
        rec = v13.insert_thank_you_sms({
            "church_id": church_id,
            "church_name": church_name,
            "week_date": week_date,
            "total_offering": total,
            "recipient_phone": r["phone"],
            "recipient_name": r["name"],
            "extra_contacts": (extra_contacts if idx == 0 else []),
            "message": message,
            "sent_by": user["id"],
            "sent_by_name": user.get("name", ""),
            "status": status,
            "gateway_response": (gateway_response if idx == 0
                                 else f"(same broadcast as {recipients[0]['phone']}) "
                                      + gateway_response)[:500],
        })
        recs.append(rec)
    # No recipients at all → still log one row so the audit trail is intact.
    if not recs:
        recs.append(v13.insert_thank_you_sms({
            "church_id": church_id,
            "church_name": church_name,
            "week_date": week_date,
            "total_offering": total,
            "recipient_phone": "",
            "recipient_name": "",
            "extra_contacts": [],
            "message": message,
            "sent_by": user["id"],
            "sent_by_name": user.get("name", ""),
            "status": status,
            "gateway_response": gateway_response,
        }))
    # V1.14: if dry_run (gateway not live) but auto_send_enabled is ON,
    # immediately try to drain the queue — covers the "parish pastor just
    # enabled auto_send after a dry_run send" edge case without waiting
    # up to 2 minutes for the scheduler tick.
    if status == "dry_run" and gw.get("auto_send_enabled"):
        try:
            import scheduler as _sched
            _sched.process_thank_you_queue()
        except Exception:
            pass
    return jsonify(recs[0]), 201


@app.route("/api/thank-you-sms/preview", methods=["GET"])
@require_auth
def api_thank_you_sms_preview():
    """Kora ubutumwa bwo gushimira bwa message2.py-style NTA ko koherereza.
    Ikoreshwa n'UI kugirango yerekane user message mbere yo kanda "Tumiza".

    Query params:
        church_id — id y'itorero (bitarenze: user agomba kuba muri iryo
                    torero cyangwa aba parish pastor/manager)
        week_date — tariki y'icyumweru ("YYYY-MM-DD")
    """
    user = request._user
    role = (user.get("role") or "").upper()
    church_id = request.args.get("church_id") or user.get("church_id") or ""
    if not church_id:
        return jsonify({"error": "Itorero ntiribonetse."}), 400
    if role not in ("PARISH_PASTOR", "PARISH_MANAGER") and \
            church_id != user.get("church_id"):
        return jsonify({"error": "Ntibyemewe."}), 403
    week_date = request.args.get("week_date", "")
    church = db.find_church(church_id)
    parish_name = (church.get("parish", "") if church else "") or None
    church_name = (church.get("name", "") if church else "")
    recipient_phone = ((church.get("leader_phone") if church else "")
                       or (church.get("pastor_phone") if church else "")
                       or "").strip()
    recipient_name = ((church.get("leader_name") if church else "")
                      or "").strip()
    import thank_you_message as _tym
    built = _tym.build(church_id, week_date, parish_name=parish_name)
    return jsonify({
        "available": built["available"],
        "message": built["message"],
        "meta": built["meta"],
        "church_id": church_id,
        "church_name": church_name,
        "week_date": week_date,
        "recipient_phone": recipient_phone,
        "recipient_name": recipient_name,
        "char_count": len(built["message"]),
        # SMS segment estimate: ~153 chars/segment for concatenated SMS
        # (GSM 7-bit). Long message ya message2.py = 3-4 segments bisanzwe.
        "sms_segments": max(1, (len(built["message"]) + 152) // 153),
    })


# ---------- V1.14: Thank-you SMS auto-send queue ----------
@app.route("/api/thank-you-sms/queue", methods=["GET"])
@require_auth
def api_thank_you_sms_queue():
    """Status of the thank-you SMS auto-send queue. Returns:
        - count: number of rows still pending (queued/dry_run)
        - auto_send_enabled: whether the parish pastor toggled auto-send ON
        - gateway_live: whether the gateway is configured to send for real
          (endpoint + not dry_run) — if False, the queue won't drain until
          the pastor connects the gateway.
        - next_tick_in_sec: approx seconds until the next scheduler tick.
    """
    user = request._user
    role = (user.get("role") or "").upper()
    if role not in ("PARISH_PASTOR", "PARISH_MANAGER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    gw = v13.load_sms_gateway()
    pending = v13.list_pending_thank_you_sms(limit=500)
    return jsonify({
        "count": len(pending),
        "auto_send_enabled": bool(gw.get("auto_send_enabled")),
        "gateway_live": bool(gw.get("endpoint") and not gw.get("dry_run")),
        "next_tick_in_sec": 120,  # scheduler runs every 2 minutes
        "pending": [{"id": r.get("id"),
                     "church_name": r.get("church_name"),
                     "recipient_phone": r.get("recipient_phone"),
                     "recipient_name": r.get("recipient_name"),
                     "week_date": r.get("week_date"),
                     "status": r.get("status"),
                     "attempts": r.get("attempts", 0),
                     "queued_at": r.get("queued_at")}
                    for r in pending],
    })


@app.route("/api/thank-you-sms/queue/drain", methods=["POST"])
@require_auth
def api_thank_you_sms_queue_drain():
    """Manually trigger the auto-send queue processor now. Useful when the
    parish pastor just connected the gateway and wants to fire the queue
    without waiting up to 2 minutes for the scheduler tick. Requires
    parish pastor/manager role."""
    user = request._user
    role = (user.get("role") or "").upper()
    if role not in ("PARISH_PASTOR", "PARISH_MANAGER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    try:
        import scheduler as _sched
        result = _sched.process_thank_you_queue()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500
    return jsonify({"ok": True, "result": result})


# ==================================================================
# BULK MESSAGING (V1.14) — thank-you SMS to ALL submitters at once.
# Three send modes: auto / manual / scheduled. Plus reminder SMS for
# churches that have NOT submitted, with a configurable schedule.
# ==================================================================

@app.route("/api/bulk-send/preview", methods=["GET"])
@require_auth
def api_bulk_send_preview():
    """Preview the bulk thank-you send for a week. Returns submitters
    (with their messages) + non-submitters (the reminder candidates).
    Query: week_date (YYYY-MM-DD, default = current week's Monday).
    Church pastors are scoped to their own church only."""
    user = request._user
    role = (user.get("role") or "").upper()
    if role not in ("PARISH_PASTOR", "PARISH_MANAGER", "CHURCH_PASTOR"):
        return jsonify({"error": "Ntibyemewe."}), 403
    import bulk_messaging as bm
    week_date = request.args.get("week_date", "") or bm.week_start()
    message_override = request.args.get("message_override", "") or None
    out = bm.preview_bulk(week_date, parish=None,
                          message_override=message_override)
    # Church pastors only see their own church's preview.
    if role == "CHURCH_PASTOR" and user.get("church_id"):
        cid = user.get("church_id")
        out["messages"] = [m for m in out.get("messages", [])
                           if str(m.get("church_id", "")) == str(cid)]
        out["non_submitters"] = [c for c in out.get("non_submitters", [])
                                 if str(c.get("id", "")) == str(cid)]
        out["submitters_count"] = len(out["messages"])
        out["non_submitters_count"] = len(out["non_submitters"])
    return jsonify(out)


@app.route("/api/bulk-send", methods=["POST"])
@require_auth
def api_bulk_send():
    """Fire a bulk thank-you send. Body:
        week_date (str, default current Monday)
        mode ("auto"|"manual"|"scheduled")
        message_override (str, optional — one custom message for all churches)
        scheduled_at (ISO datetime, required when mode="scheduled")
    Returns: batch_id (for scheduled) or send summary (for auto/manual)."""
    user = request._user
    role = (user.get("role") or "").upper()
    if role not in ("PARISH_PASTOR", "PARISH_MANAGER", "CHURCH_PASTOR"):
        return jsonify({"error": "Ntibyemewe."}), 403
    import bulk_messaging as bm
    data = request.get_json(silent=True) or {}
    week_date = data.get("week_date", "") or bm.week_start()
    mode = (data.get("mode") or "manual").lower()
    message_override = data.get("message_override", "") or None
    if mode not in ("auto", "manual", "scheduled"):
        return jsonify({"error": "Mode ntabwo izwi (auto/manual/scheduled)."}), 400
    # Build the per-church messages once.
    messages = bm.build_bulk_messages(week_date, parish=None,
                                      message_override=message_override)
    # V1.20: apply per-church edits (overrides) coming from the thank-you
    # view. The user can tweak each church's message before sending; those
    # tweaks take precedence over both the auto-generated message and the
    # single message_override.
    per_church_overrides = data.get("per_church_overrides") or {}
    if isinstance(per_church_overrides, dict) and per_church_overrides:
        for m in messages:
            cid = str(m.get("church_id", ""))
            if cid and cid in per_church_overrides:
                edited = per_church_overrides[cid]
                if isinstance(edited, str) and edited.strip():
                    m["message"] = edited
                    m["edited"] = True
    # Church pastors are scoped to their own church only.
    if role == "CHURCH_PASTOR" and user.get("church_id"):
        cid = str(user.get("church_id"))
        messages = [m for m in messages if str(m.get("church_id", "")) == cid]
    if not messages:
        return jsonify({"error": "Nta matorero yatanze amaturo ku cyumweru cyo."}), 400
    if mode == "scheduled":
        scheduled_at = (data.get("scheduled_at") or "").strip()
        if not scheduled_at:
            return jsonify({"error": "Sabye igihe cyo kohereza (scheduled_at)."}), 400
        # Validate it's a future datetime.
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(scheduled_at.replace("Z", ""))
            if dt <= datetime.now():
                return jsonify({"error": "Igihe cyo kohereza kigomba kuba kizaza."}), 400
        except ValueError:
            return jsonify({"error": "scheduled_at ntabwo format nziza (YYYY-MM-DDTHH:MM)."}), 400
        res = bm.schedule_bulk(
            messages, scheduled_at,
            sent_by=user["id"], sent_by_name=user.get("name", ""),
            week_date=week_date, parish="",
        )
        return jsonify(res), 201
    # auto / manual — both fire immediately. (auto is "fire now through
    # the gateway"; manual is "I reviewed the messages, fire now". The
    # distinction is UI-side; the backend path is the same.)
    # Record the batch first so the audit trail has a parent row.
    import db_v14 as v14
    batch = v14.insert_bulk_send_batch({
        "week_date": week_date, "parish": "",
        "mode": mode, "status": "sending",
        "sent_by": user["id"], "sent_by_name": user.get("name", ""),
        "message_override": message_override or "",
        "total": len(messages),
    })
    res = bm.send_bulk_now(
        messages,
        sent_by=user["id"], sent_by_name=user.get("name", ""),
        batch_id=batch["id"], week_date=week_date, parish="",
    )
    res["batch_id"] = batch["id"]
    return jsonify(res), 201


@app.route("/api/bulk-send/log", methods=["GET"])
@require_auth
def api_bulk_send_log():
    """List recent bulk-send batches (newest first). Church pastors see
    only batches they fired themselves."""
    user = request._user
    role = (user.get("role") or "").upper()
    if role not in ("PARISH_PASTOR", "PARISH_MANAGER", "CHURCH_PASTOR"):
        return jsonify({"error": "Ntibyemewe."}), 403
    import db_v14 as v14
    rows = v14.list_bulk_send_log(limit=50)
    if role == "CHURCH_PASTOR":
        rows = [r for r in rows if r.get("sent_by") == user.get("id")]
    return jsonify(rows)


@app.route("/api/bulk-send/<batch_id>/cancel", methods=["POST"])
@require_auth
def api_bulk_send_cancel(batch_id):
    """Cancel a scheduled batch that hasn't fired yet."""
    user = request._user
    role = (user.get("role") or "").upper()
    if role not in ("PARISH_PASTOR", "PARISH_MANAGER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    import db_v14 as v14
    batch = v14.find_bulk_batch(batch_id)
    if not batch:
        return jsonify({"error": "Batch ntabonetse."}), 404
    if batch.get("status") not in ("scheduled", "pending"):
        return jsonify({"error": "Batch ntishobora gukurwaho (yari guhera)."}), 400
    updated = v14.mark_bulk_batch_status(batch_id, {
        "status": "cancelled",
        "notes": f"cancelled by {user.get('name','')} at {db._now_iso()}",
    })
    return jsonify(updated)


# ---------- REMINDER (kwibutsa amatorero ataratanga amaturo) ----------

@app.route("/api/bulk-send/reminder/preview", methods=["GET"])
@require_auth
def api_bulk_send_reminder_preview():
    """Preview the reminder send for a week. Returns non-submitters with
    the reminder message built from the configured template (or a custom
    one passed as ?custom_message=)."""
    user = request._user
    role = (user.get("role") or "").upper()
    if role not in ("PARISH_PASTOR", "PARISH_MANAGER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    import bulk_messaging as bm
    week_date = request.args.get("week_date", "") or bm.week_start()
    custom = request.args.get("custom_message", "") or None
    return jsonify(bm.preview_reminder(week_date, parish=None,
                                       custom_message=custom))


@app.route("/api/bulk-send/reminder", methods=["POST"])
@require_auth
def api_bulk_send_reminder_send():
    """Fire reminder SMS to all non-submitters for a week. Body:
        week_date (str, default current Monday)
        custom_message (str, optional — overrides the configured template)
    Returns: send summary."""
    user = request._user
    role = (user.get("role") or "").upper()
    if role not in ("PARISH_PASTOR", "PARISH_MANAGER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    import bulk_messaging as bm
    data = request.get_json(silent=True) or {}
    week_date = data.get("week_date", "") or bm.week_start()
    custom = data.get("custom_message", "") or None
    messages = bm.build_reminder_messages(week_date, parish=None,
                                          custom_message=custom)
    if not messages:
        return jsonify({"error": "Amatorero yose yatanze amaturo (nta kwibutsa)."}), 400
    res = bm.send_reminders_now(
        messages,
        sent_by=user["id"], sent_by_name=user.get("name", ""),
        week_date=week_date, parish="",
    )
    return jsonify(res), 201


@app.route("/api/bulk-send/reminder/log", methods=["GET"])
@require_auth
def api_bulk_send_reminder_log():
    """List recent reminder SMS rows (newest first)."""
    user = request._user
    role = (user.get("role") or "").upper()
    if role not in ("PARISH_PASTOR", "PARISH_MANAGER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    import db_v14 as v14
    return jsonify(v14.list_reminder_log(limit=100))


# ---------- REMINDER CONFIG (parish pastor sets the auto-fire schedule) ----------

@app.route("/api/bulk-send/reminder/config", methods=["GET"])
@require_auth
def api_bulk_send_reminder_config_get():
    user = request._user
    role = (user.get("role") or "").upper()
    if role not in ("PARISH_PASTOR", "PARISH_MANAGER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    import db_v14 as v14
    return jsonify(v14.load_reminder_config())


@app.route("/api/bulk-send/reminder/config", methods=["PUT"])
@require_auth
def api_bulk_send_reminder_config_put():
    """Update the reminder auto-fire schedule. Body fields:
        enabled (bool), days_after_week_start (0-6), hour (0-23),
        minute (0-59), message_template (str), auto_send_enabled (bool)."""
    user = request._user
    role = (user.get("role") or "").upper()
    if role != "PARISH_PASTOR":
        return jsonify({"error": "Ntibyemewe (parish pastor gusa)."}), 403
    import db_v14 as v14
    data = request.get_json(silent=True) or {}
    updated = v14.save_reminder_config(data)
    db.log_activity({
        "actor_id": user["id"], "actor_name": user.get("name", ""),
        "actor_role": "PARISH_PASTOR", "church_id": "",
        "action": "REMINDER_CONFIG_UPDATED",
        "target": f"enabled={updated.get('enabled')} day+{updated.get('days_after_week_start')} {updated.get('hour')}:{updated.get('minute'):02d}",
        "detail": "auto_send=" + str(updated.get("auto_send_enabled")),
        "scope": "parish",
    })
    return jsonify(updated)


@app.route("/api/bulk-send/reminder/run-now", methods=["POST"])
@require_auth
def api_bulk_send_reminder_run_now():
    """Manually trigger the reminder scheduler now (ignores the day/time
    gate, but still respects enabled + auto_send_enabled). Useful when
    the parish pastor wants to fire reminders outside the scheduled slot."""
    user = request._user
    role = (user.get("role") or "").upper()
    if role not in ("PARISH_PASTOR", "PARISH_MANAGER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    try:
        import scheduler as _sched
        result = _sched.process_reminders()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500
    return jsonify({"ok": True, "result": result})


# ---------- Scheduled-bulk scheduler drain (manual trigger) ----------

@app.route("/api/bulk-send/scheduled/drain", methods=["POST"])
@require_auth
def api_bulk_send_scheduled_drain():
    """Manually trigger the scheduled-bulk processor now. Fires any
    scheduled batches whose scheduled_at has arrived, without waiting
    up to 60s for the next scheduler tick."""
    user = request._user
    role = (user.get("role") or "").upper()
    if role not in ("PARISH_PASTOR", "PARISH_MANAGER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    try:
        import scheduler as _sched
        result = _sched.process_scheduled_bulk_sends()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500
    return jsonify({"ok": True, "result": result})


# ==================================================================
# V1.16 — WEEKLY OFFERINGS RESET + MANUAL CATEGORY RESET + PROOF AUDIT
# ==================================================================

# ---- Weekly reset config (parish pastor only) ----
@app.route("/api/weekly-reset/config", methods=["GET"])
@require_parish
def api_weekly_reset_config_get():
    """Read the weekly auto-finalize config."""
    import db_v14 as v14
    return jsonify(v14.load_weekly_reset_config())


@app.route("/api/weekly-reset/config", methods=["PUT"])
@require_parish
def api_weekly_reset_config_put():
    """Update the weekly auto-finalize config."""
    import db_v14 as v14
    data = request.get_json(silent=True) or {}
    try:
        cur = v14.save_weekly_reset_config(data)
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500
    return jsonify(cur)


@app.route("/api/weekly-reset/run-now", methods=["POST"])
@require_parish
def api_weekly_reset_run_now():
    """Manually trigger the weekly-reset scheduler tick (finalizes the
    ended week if its grace period has elapsed). Lets the parish pastor
    force the roll-over without waiting up to 5 minutes for the next
    scheduler tick."""
    try:
        import scheduler as _sched
        result = _sched.process_weekly_reset()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500
    return jsonify({"ok": True, "result": result})


@app.route("/api/weekly-reset/log", methods=["GET"])
@require_parish
def api_weekly_reset_log():
    """Audit log of finalized weeks (auto + manual)."""
    import db_v14 as v14
    limit = int(request.args.get("limit", 100) or 100)
    return jsonify(v14.list_weekly_reset_log(limit=limit))


# ---- Manual finalize of a specific week (parish pastor) ----
@app.route("/api/weekly-reset/finalize", methods=["POST"])
@require_parish
def api_weekly_reset_finalize():
    """Manually finalize a specific week (lock it read-only). Used when
    the parish pastor is satisfied a week is complete and wants to lock
    it before the auto-fire date."""
    import db_v14 as v14
    data = request.get_json(silent=True) or {}
    week_date = (data.get("week_date") or "").strip()
    if not week_date:
        return jsonify({"error": "week_date irakenewe."}), 400
    user = request._user
    res = v14.finalize_week(
        week_date,
        finalized_by=user.get("id", ""),
        finalized_by_name=user.get("name", ""),
        trigger="manual",
    )
    return jsonify(res)


@app.route("/api/weekly-reset/finalized-weeks", methods=["GET"])
@require_parish
def api_weekly_reset_finalized_weeks():
    """List of week_dates that are already finalized (locked)."""
    import db_v14 as v14
    return jsonify(v14.list_finalized_weeks())


# ---- Manual category reset (parish + church-finance for own church) ----
@app.route("/api/offerings/reset-category", methods=["POST"])
@require_auth
def api_offerings_reset_category():
    """Delete every ITEMS row for (church_id, week_date, category) and
    recompute the parent offering's total. Lets a finance officer start
    ONE category over from zero without touching the others.

    Permission: parish pastor (any church) OR church pastor/finance
    (own church only). Refuses if the week is finalized.
    """
    import db_v14 as v14
    user = request._user
    role = (user.get("role") or "").upper()
    data = request.get_json(silent=True) or {}
    church_id = (data.get("church_id") or "").strip()
    week_date = (data.get("week_date") or "").strip()
    category = (data.get("category") or "").strip()
    reason = (data.get("reason") or "").strip()
    if not church_id or not week_date or not category:
        return jsonify({"error": "church_id, week_date na category bikenewe."}), 400
    # Permission check.
    if role in ("CHURCH_PASTOR", "CHURCH_FINANCE"):
        if church_id != user.get("church_id"):
            return jsonify({"error": "Ushobora gushyira ah'itorero ryawe gusa."}), 403
    elif role not in ("PARISH_PASTOR", "PARISH_MANAGER"):
        return jsonify({"error": "Ntibyemewe."}), 403
    try:
        res = v14.reset_offering_category(
            church_id, week_date, category,
            reset_by=user.get("id", ""),
            reset_by_name=user.get("name", ""),
            reason=reason or "manual_category_reset",
        )
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500
    if res.get("error"):
        return jsonify(res), 400
    return jsonify(res)


@app.route("/api/offerings/reset-log", methods=["GET"])
@require_parish
def api_offerings_reset_log():
    """Audit log of manual category resets (parish view)."""
    import db_v14 as v14
    church_id = request.args.get("church_id")
    week_date = request.args.get("week_date")
    limit = int(request.args.get("limit", 200) or 200)
    return jsonify(v14.list_offering_reset_log(
        church_id=church_id, week_date=week_date, limit=limit))


# ---- Proof-file audit (parish browses all uploaded proofs) ----
@app.route("/api/offerings/proof-audit", methods=["GET"])
@require_parish
def api_offerings_proof_audit():
    """Enriched flat list of every proof-file attachment, with church
    name, week date, kind label, and a view URL — so the parish pastor
    can audit MoMo/bank proofs in one place. Filters: ?church_id=,
    ?start_date=, ?end_date=, ?kind=(momo_sms|bank_slip|other)."""
    import db_v14 as v14
    rows = v14.list_proof_attachments_enriched(
        church_id=request.args.get("church_id"),
        start_date=request.args.get("start_date"),
        end_date=request.args.get("end_date"),
        kind=request.args.get("kind"),
    )
    return jsonify(rows)


# ---------- Service-request escalation + delegation ----------
@app.route("/api/service-requests/<req_id>/escalate", methods=["POST"])
@require_parish
def api_service_requests_escalate(req_id):
    data = request.get_json(silent=True) or {}
    assignee = None
    if data.get("assignee_user_id"):
        assignee = db.find_user_by_id(data["assignee_user_id"])
    out = v13.escalate_service_request(
        req_id, request._user, assignee_user=assignee,
        feedback=data.get("feedback", ""))
    if not out:
        return jsonify({"error": "Isabye ntabonetse."}), 404
    if assignee:
        db.send_notification({
            "sender_id": request._user["id"],
            "sender_name": request._user.get("name", ""),
            "sender_role": request._user.get("role", ""),
            "recipient_id": assignee["id"],
            "title": f"Wahawe igikorwa: {out.get('christian_name','')}",
            "body": (f"Umushumba wa Paruwasi yakuyejeje isabye ryo kwakira "
                     f"{out.get('christian_name','')} akagishyira ku maboko yawe. "
                     f"Ibyo ukora: {data.get('feedback','—')}"),
            "category": "service",
        })
    return jsonify(out)


# ---------- Reception overview (parish) ----------
@app.route("/api/reception/overview", methods=["GET"])
@require_parish
def api_reception_overview():
    return jsonify(v13.reception_overview())


# ---------- Schedules with category ----------
@app.route("/api/schedules/categorized", methods=["POST"])
@require_auth
def api_schedules_categorized_create():
    """Create a schedule with an optional `category` so the parish can
    group events by category (e.g. Abana, Urubyerero, Ibyishimo)."""
    user = request._user
    data = request.get_json(silent=True) or {}
    if not data.get("title") or not data.get("datetime"):
        return jsonify({"error": "Umutwe n'amakuru y'igihe birakenewe."}), 400
    payload = {
        "title": data["title"],
        "description": data.get("description", ""),
        "datetime": data["datetime"],
        "location": data.get("location", ""),
        "church_id": user.get("church_id") or data.get("church_id", ""),
        "ministry_id": data.get("ministry_id", ""),
        "created_by": user["id"],
        "creator_name": user.get("name", ""),
        "creator_role": user.get("role", ""),
        "category": data.get("category", ""),
    }
    rec = v13.create_categorized_schedule(payload)
    if not rec:
        return jsonify({"error": "Byanze."}), 500
    return jsonify(rec), 201


# ==================================================================
# Main
# ==================================================================
if __name__ == "__main__":
    try:
        db._prewarm_cache()
    except Exception as e:
        print(f"⚠️ Pre-warm failed: {e}")
    # V1.15: Auto-seed on a fresh install. If no users exist (empty data dir
    # — e.g. the user just extracted the zip and ran app.py for the first
    # time), run seed.main() so the demo accounts + sample churches exist
    # and login works immediately. seed.py is idempotent (it checks
    # find_user_by_username before inserting), so this is safe even if the
    # user later runs `python3 seed.py` manually.
    try:
        if not db.list_users():
            print("   🌱 Nta konti zibonetse — turiko turaseed demo data...")
            import seed
            seed.main()
            db._prewarm_cache()
    except Exception as e:
        print(f"   ⚠️ Auto-seed ntiyagenze neza: {e}")
        print(f"      Reka ukore: python3 seed.py")
    try:
        import scheduler
        scheduler.start()
        print("   ⏰ Background scheduler started (queue processor + weekly email + thank-you auto-send)")
    except Exception as e:
        print(f"   ⚠️ Scheduler ntabwo yatangiye: {e}")
    print("🚀 ADEPR Paruwasi ya Ruhango MIS — http://127.0.0.1:5000")
    print("   Logins:")
    print("   - parish / parish123  (Umushumba wa Paruwasi)")
    print("   - ruhango / church123 (Umushumba w'itorero)")
    print("   - leader_abana / leader123 (Umuyobozi wa ministeur)")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
