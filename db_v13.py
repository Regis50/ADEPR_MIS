"""
db_v13.py — V1.13 extensions to db.py.

Adds the entities + helpers requested in the V1.13 brief, without
touching the existing 3200-line db.py. Everything here reuses db's
JSON persistence helpers (_read_tab / _write_tab / _read_obj /
_write_obj / _new_id / _now_iso / _to_bool / _to_float / log_activity)
and the existing entities (users, members, service_requests,
delegations, signatures, offerings).

Entities introduced here:
  member_deletion_requests.json — zone/ministry asks to remove a
        member; church pastor approves (with reason + signature);
        the member is DEACTIVATED (not hard-deleted) so history is
        kept.
  change_requests.json          — PARISH_MANAGER proposes a write
        (create/update/delete) when they lack an active delegation
        for that feature; PARISH_PASTOR approves → the change is
        applied by replaying it against the real db function.
  sms_gateway.json              — single-object Tracar SMS gateway
        config (endpoint, token, sender_id) + last-test result.
  thank_you_sms_log.json        — thank-you SMS sent per church per
        week for offerings received (auditable log).

Extended (no new file):
  service_requests  — escalation fields (escalated_to_user_id,
        escalated_to_name, escalation_feedback, escalated_at).
  schedules         — category field (which ministry/category the
        event belongs to) so the parish can group events by category.
  users             — photo (base64) + status, set via update_user.
"""

import os
import json
import db
from db import (
    _read_tab, _write_tab,
    _new_id, _now_iso, _to_bool, _to_float, log_activity,
    USERS_TAB, MEMBERS_TAB, SERVICE_REQUESTS_TAB, DELEGATIONS_TAB,
    SCHEDULES_TAB,
    find_member, find_user_by_id, find_church, update_member,
    find_service_request, insert_member,
)


# ------------------------------------------------------------------
# Single-object JSON helpers (parish_profile-style): these entities
# live in one JSON file holding a dict, not a list of rows.
# ------------------------------------------------------------------
def _read_obj(name):
    """Read a single-object JSON file. Returns {} if missing/invalid."""
    p = db._path(name)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_obj(name, obj):
    """Write a single-object JSON file (atomic-ish: tmp + replace)."""
    p = db._path(name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


# ==================================================================
# 1. PROFILE — name / phone / email / photo (all roles)
# ==================================================================
PROFILE_SAFE_FIELDS = ("name", "phone", "email", "photo")


def update_user_profile(user_id, updates):
    """Whitelisted self-profile update. Only name/phone/email/photo.
    Returns the patched user (with secret fields stripped) or None."""
    safe = {k: v for k, v in (updates or {}).items()
            if k in PROFILE_SAFE_FIELDS}
    if not safe:
        u = db.find_user_by_id(user_id) if hasattr(db, "find_user_by_id") else None
        return u
    ok = db.update_user(user_id, safe)
    if not ok:
        return None
    # Return the fresh record (without secrets).
    rows = _read_tab(USERS_TAB)
    for r in rows:
        if r.get("id") == user_id:
            return {k: v for k, v in r.items()
                    if k not in db.SECRET_FIELDS}
    return None


# ==================================================================
# 2. MEMBER DELETION REQUESTS (zone/ministry → church pastor)
# ==================================================================
DELETION_REQUESTS_TAB = "member_deletion_requests"


def list_deletion_requests(church_id=None, status=None, requester_id=None):
    rows = _read_tab(DELETION_REQUESTS_TAB)
    if church_id:
        rows = [r for r in rows if r.get("church_id") == church_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if requester_id:
        rows = [r for r in rows if r.get("requester_id") == requester_id]
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return rows


def find_deletion_request(req_id):
    for r in _read_tab(DELETION_REQUESTS_TAB):
        if r.get("id") == req_id:
            return r
    return None


def insert_deletion_request(payload):
    """A zone reader or ministry leader asks to remove a member.
    The member is NOT removed here — the church pastor must approve."""
    member_id = payload.get("member_id", "")
    member = find_member(member_id)
    if not member:
        return None
    rec = {
        "id": _new_id("DR"),
        "member_id": member_id,
        "member_name": member.get("name", ""),
        "church_id": member.get("church_id", "") or payload.get("church_id", ""),
        "category": member.get("category", ""),
        "requester_id": payload.get("requester_id", ""),
        "requester_name": payload.get("requester_name", ""),
        "requester_role": payload.get("requester_role", ""),
        "reason": (payload.get("reason") or "").strip(),
        "signature": payload.get("signature", ""),    # base64 PNG of requester's signature
        "status": "pending",
        "created_at": _now_iso(),
    }
    rows = _read_tab(DELETION_REQUESTS_TAB)
    rows.append(rec)
    _write_tab(DELETION_REQUESTS_TAB, rows)
    log_activity({
        "actor_id": payload.get("requester_id", ""),
        "actor_name": payload.get("requester_name", ""),
        "actor_role": payload.get("requester_role", ""),
        "church_id": rec["church_id"],
        "action": "DELETION_REQUESTED",
        "target": member.get("name", ""),
        "detail": rec["reason"][:80],
        "scope": "church",
    })
    return rec


def approve_deletion_request(req_id, approver):
    """Church pastor approves. The member is DEACTIVATED (active=False,
    deletion_approved=True) so the roster no longer counts them but the
    historical records (offerings, etc.) stay intact."""
    rows = _read_tab(DELETION_REQUESTS_TAB)
    rec = None
    for r in rows:
        if r.get("id") == req_id:
            r["status"] = "approved"
            r["approved_by"] = approver.get("id", "")
            r["approved_by_name"] = approver.get("name", "")
            r["approved_at"] = _now_iso()
            rec = r
            break
    if not rec:
        return None
    _write_tab(DELETION_REQUESTS_TAB, rows)
    # Deactivate the member (keep the record for history).
    update_member(rec["member_id"], {
        "active": False,
        "deletion_approved": True,
        "deletion_approved_at": _now_iso(),
        "deletion_approved_by": approver.get("name", ""),
    })
    log_activity({
        "actor_id": approver.get("id", ""),
        "actor_name": approver.get("name", ""),
        "actor_role": approver.get("role", ""),
        "church_id": rec.get("church_id", ""),
        "action": "DELETION_APPROVED",
        "target": rec.get("member_name", ""),
        "detail": "Member deactivated (roster history kept)",
        "scope": "church",
    })
    return rec


def reject_deletion_request(req_id, approver, feedback=""):
    rows = _read_tab(DELETION_REQUESTS_TAB)
    rec = None
    for r in rows:
        if r.get("id") == req_id:
            r["status"] = "rejected"
            r["approved_by"] = approver.get("id", "")
            r["approved_by_name"] = approver.get("name", "")
            r["approved_at"] = _now_iso()
            r["feedback"] = feedback
            rec = r
            break
    if not rec:
        return None
    _write_tab(DELETION_REQUESTS_TAB, rows)
    log_activity({
        "actor_id": approver.get("id", ""),
        "actor_name": approver.get("name", ""),
        "actor_role": approver.get("role", ""),
        "church_id": rec.get("church_id", ""),
        "action": "DELETION_REJECTED",
        "target": rec.get("member_name", ""),
        "detail": feedback[:80],
        "scope": "church",
    })
    return rec


# ==================================================================
# 3. MANAGER CHANGE-REQUEST GATE
#    A PARISH_MANAGER may READ everything but cannot WRITE unless the
#    PARISH_PASTOR has granted an active delegation for that feature.
#    Without a delegation, the manager's write becomes a "change
#    request" the parish pastor approves; on approval the change is
#    replayed against the real db function.
# ==================================================================
CHANGE_REQUESTS_TAB = "change_requests"


def manager_has_delegation(manager_user, feature):
    """True if the parish pastor has granted this manager an active
    delegation for `feature` (e.g. 'churches', 'budgets', 'offerings')."""
    if not manager_user:
        return False
    uid = manager_user.get("id", "")
    now = _now_iso()[:10]
    for d in _read_tab(DELEGATIONS_TAB):
        if d.get("status") != "ACTIVE":
            continue
        if d.get("feature") != feature:
            continue
        if d.get("delegate_user_id") and d.get("delegate_user_id") != uid:
            continue
        end = (d.get("end_date") or "9999")[:10]
        if end < now:
            continue
        # If delegate_user_id is empty the delegation is by name; accept
        # if the name matches (case-insensitive) — covers legacy records.
        dn = (d.get("delegate_name") or "").strip().lower()
        un = (manager_user.get("name") or "").strip().lower()
        if d.get("delegate_user_id") or dn == un or not dn:
            return True
    return False


def list_change_requests(status=None, feature=None):
    rows = _read_tab(CHANGE_REQUESTS_TAB)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if feature:
        rows = [r for r in rows if r.get("feature") == feature]
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return rows


def find_change_request(req_id):
    for r in _read_tab(CHANGE_REQUESTS_TAB):
        if r.get("id") == req_id:
            return r
    return None


def insert_change_request(payload):
    """Record a manager's proposed write. `payload` carries:
       feature, action (create/update/delete), target_type, target_id,
       proposed (the body the manager wanted to save)."""
    rec = {
        "id": _new_id("CR"),
        "feature": payload.get("feature", ""),
        "action": payload.get("action", ""),         # create/update/delete
        "target_type": payload.get("target_type", ""),
        "target_id": payload.get("target_id", ""),
        "proposed": payload.get("proposed", {}),      # the change body
        "requester_id": payload.get("requester_id", ""),
        "requester_name": payload.get("requester_name", ""),
        "reason": payload.get("reason", ""),
        "status": "pending",
        "created_at": _now_iso(),
    }
    rows = _read_tab(CHANGE_REQUESTS_TAB)
    rows.append(rec)
    _write_tab(CHANGE_REQUESTS_TAB, rows)
    log_activity({
        "actor_id": rec["requester_id"],
        "actor_name": rec["requester_name"],
        "actor_role": "PARISH_MANAGER",
        "church_id": "",
        "action": "CHANGE_REQUESTED",
        "target": f"{rec['action']} {rec['target_type']}",
        "detail": rec["reason"][:80],
        "scope": "parish",
    })
    return rec


def _apply_change_request(rec):
    """Replay the proposed change against the real db function.
    Returns the created/updated record id, or True for delete."""
    feat = rec.get("feature", "")
    action = rec.get("action", "")
    proposed = rec.get("proposed", {}) or {}
    target_id = rec.get("target_id", "")
    if feat == "churches":
        if action == "create":
            r = db.insert_church(proposed)
            return r.get("id") if r else ""
        if action == "update":
            db.update_church(target_id, proposed)
            return target_id
        if action == "delete":
            db.delete_church(target_id)
            return True
    if feat == "budgets":
        # proposed = {church_id, week_date, amount, set_by}
        db.set_church_budget(
            proposed.get("church_id", ""),
            proposed.get("week_date", ""),
            proposed.get("amount", 0),
            proposed.get("set_by", ""),
        )
        return True
    if feat == "members":
        if action == "create":
            r = insert_member(proposed)
            return r.get("id") if r else ""
        if action == "update":
            update_member(target_id, proposed)
            return target_id
        if action == "delete":
            db.delete_member(target_id)
            return True
    if feat == "offerings":
        r = db.insert_offering(proposed)
        return r.get("id") if r else ""
    if feat == "assets":
        if action == "create":
            r = db.insert_asset(proposed)
            return r.get("id") if r else ""
        if action == "update":
            db.update_asset(target_id, proposed)
            return target_id
        if action == "delete":
            db.delete_asset(target_id)
            return True
    if feat == "schedules":
        if action == "create":
            r = db.create_schedule(proposed)
            return r.get("id") if r else ""
        if action == "update":
            db.update_schedule_status(target_id, proposed.get("status", ""))
            return target_id
    return None


def approve_change_request(req_id, approver):
    rows = _read_tab(CHANGE_REQUESTS_TAB)
    rec = None
    for r in rows:
        if r.get("id") == req_id:
            r["status"] = "approved"
            r["approved_by"] = approver.get("id", "")
            r["approved_by_name"] = approver.get("name", "")
            r["approved_at"] = _now_iso()
            rec = r
            break
    if not rec:
        return None
    _write_tab(CHANGE_REQUESTS_TAB, rows)
    try:
        result = _apply_change_request(rec)
        rec["applied_result"] = result
        _write_tab(CHANGE_REQUESTS_TAB, rows)
    except Exception as exc:  # noqa: BLE001 — record the failure
        rec["apply_error"] = str(exc)
        _write_tab(CHANGE_REQUESTS_TAB, rows)
    log_activity({
        "actor_id": approver.get("id", ""),
        "actor_name": approver.get("name", ""),
        "actor_role": approver.get("role", ""),
        "church_id": "",
        "action": "CHANGE_APPROVED",
        "target": f"{rec.get('action')} {rec.get('target_type')}",
        "detail": rec.get("reason", "")[:80],
        "scope": "parish",
    })
    return rec


def reject_change_request(req_id, approver, feedback=""):
    rows = _read_tab(CHANGE_REQUESTS_TAB)
    rec = None
    for r in rows:
        if r.get("id") == req_id:
            r["status"] = "rejected"
            r["approved_by"] = approver.get("id", "")
            r["approved_by_name"] = approver.get("name", "")
            r["approved_at"] = _now_iso()
            r["feedback"] = feedback
            rec = r
            break
    if not rec:
        return None
    _write_tab(CHANGE_REQUESTS_TAB, rows)
    log_activity({
        "actor_id": approver.get("id", ""),
        "actor_name": approver.get("name", ""),
        "actor_role": approver.get("role", ""),
        "church_id": "",
        "action": "CHANGE_REJECTED",
        "target": f"{rec.get('action')} {rec.get('target_type')}",
        "detail": feedback[:80],
        "scope": "parish",
    })
    return rec


def gate_manager_write(user, feature, action, target_type, target_id,
                       proposed, reason=""):
    """Called by write routes. If the caller is a PARISH_MANAGER without
    an active delegation for `feature`, record a change request and
    return (rec, True). Otherwise return (None, False) = caller may
    proceed with the real write."""
    role = (user.get("role") or "").upper()
    if role != "PARISH_MANAGER":
        return None, False
    if manager_has_delegation(user, feature):
        return None, False
    rec = insert_change_request({
        "feature": feature,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "proposed": proposed,
        "requester_id": user.get("id", ""),
        "requester_name": user.get("name", ""),
        "reason": reason,
    })
    return rec, True


# ==================================================================
# 4. SMS GATEWAY CONFIG (Tracar) — single-object
# ==================================================================
SMS_GATEWAY_OBJ = "sms_gateway"

_DEFAULT_GATEWAY = {
    "provider": "traccar",
    # Pre-filled with the user's real Traccar gateway (from settings.json) so
    # the panel works out-of-the-box: just flip dry_run off and hit "Tumiza
    # test". The endpoint already includes no trailing slash — url_trailing_slash
    # below adds it. The token is the Traccar device unique ID, sent raw in the
    # Authorization header (no "Bearer " prefix — that prefix is what causes
    # HTTP 401 against this gateway).
    "endpoint": "http://192.168.1.169:8082",
    "token": "7d6ed977-9415-4e0c-855a-820c76cbe2e5",
    "auth_mode": "header_raw", # bearer | x-api-key | query | header_raw | basic | none
    "basic_user": "",          # username for HTTP Basic auth (auth_mode=basic)
    "token_param": "password", # query-param name when auth_mode=query
    "http_method": "POST",     # POST | GET
    "phone_param": "to",       # JSON key / form param for destination number
    "message_param": "message",# JSON key / form param for message text
    "body_format": "json",     # json | form  (Traccar expects JSON {to, message})
    "phone_format": "intl",    # local (0788…) | intl (+250788…)  (Traccar expects +250)
    "url_trailing_slash": True,# append "/" to endpoint (Traccar requires it)
    "timeout": 15,             # seconds — matches settings.json gateway_timeout
    "delay_between": 1.0,      # seconds between sends in a broadcast — matches settings.json delay_between (prevents hammering the gateway)
    "sender_id": "",           # approved sender name
    "phone": "",               # gateway phone / SIM (default test destination)
    "app": "Traccar SMS Gateway",
    "dry_run": True,
    # V1.14: Auto-send queue — when True AND gateway is live (endpoint set +
    # dry_run=False), the background scheduler picks up thank-you SMS rows
    # still in 'dry_run'/'queued' status and sends them automatically. This
    # is what the user asked for: "anytime gateway ibaye connected message
    # ziyohereza automatically". Default OFF so nothing fires by surprise.
    "auto_send_enabled": False,
    "last_test": None,         # {ok, status, message, at, sent, to, request_url, auth_mode, http_method, body_format, phone_format}
}


def load_sms_gateway():
    obj = _read_obj(SMS_GATEWAY_OBJ)
    if not obj:
        return dict(_DEFAULT_GATEWAY)
    # Merge defaults so new fields appear on old records.
    merged = dict(_DEFAULT_GATEWAY)
    merged.update(obj)
    return merged


def save_sms_gateway(updates):
    cur = load_sms_gateway()
    for k in ("provider", "endpoint", "token", "auth_mode", "basic_user",
              "token_param", "http_method", "phone_param", "message_param",
              "body_format", "phone_format", "url_trailing_slash",
              "timeout", "delay_between",
              "sender_id", "phone", "app", "dry_run", "auto_send_enabled"):
        if k in updates:
            cur[k] = updates[k]
    # Normalize auth_mode so a bad value can't break sms.py.
    if cur.get("auth_mode") not in ("bearer", "x-api-key", "query",
                                     "header_raw", "basic", "none"):
        cur["auth_mode"] = "header_raw"
    # Normalize http_method.
    if str(cur.get("http_method", "POST")).upper() not in ("POST", "GET"):
        cur["http_method"] = "POST"
    else:
        cur["http_method"] = str(cur["http_method"]).upper()
    # body_format / phone_format must be valid enum values.
    if cur.get("body_format") not in ("json", "form"):
        cur["body_format"] = "json"
    if cur.get("phone_format") not in ("local", "intl"):
        cur["phone_format"] = "intl"
    cur["url_trailing_slash"] = bool(cur.get("url_trailing_slash", True))
    cur["auto_send_enabled"] = bool(cur.get("auto_send_enabled", False))
    # timeout / delay_between must be sane positive numbers (default to the
    # settings.json values if the user clears them or sends garbage).
    try:
        t = float(cur.get("timeout", 15))
        cur["timeout"] = t if t > 0 else 15
    except (TypeError, ValueError):
        cur["timeout"] = 15
    try:
        d = float(cur.get("delay_between", 1.0))
        cur["delay_between"] = d if d >= 0 else 1.0
    except (TypeError, ValueError):
        cur["delay_between"] = 1.0
    # token_param / phone_param / message_param must be non-empty strings.
    for f in ("token_param", "phone_param", "message_param"):
        if not str(cur.get(f, "")).strip():
            cur[f] = _DEFAULT_GATEWAY[f]
    cur["updated_at"] = _now_iso()
    _write_obj(SMS_GATEWAY_OBJ, cur)
    return cur


def record_sms_gateway_test(ok, status, message, sent=None, to=None,
                             request_url=None, auth_mode=None,
                             http_method=None, body_format=None,
                             phone_format=None):
    cur = load_sms_gateway()
    cur["last_test"] = {
        "ok": bool(ok),
        "status": status,
        "message": message,
        "at": _now_iso(),
    }
    # Echo what we actually sent + the destination so the panel can show
    # "Ubutumwa bwoherejwe" and the receiver, which makes a failed test much
    # easier to debug (the user can see the gateway's raw reply alongside the
    # exact message + phone that were sent).
    if sent is not None:
        cur["last_test"]["sent"] = sent
    if to is not None:
        cur["last_test"]["to"] = to
    # The exact URL we hit (token masked) + the auth scheme + HTTP method +
    # body format + phone format, so a 401/403/404 can be diagnosed: the user
    # sees exactly which request shape was tried.
    if request_url is not None:
        cur["last_test"]["request_url"] = request_url
    if auth_mode is not None:
        cur["last_test"]["auth_mode"] = auth_mode
    if http_method is not None:
        cur["last_test"]["http_method"] = http_method
    if body_format is not None:
        cur["last_test"]["body_format"] = body_format
    if phone_format is not None:
        cur["last_test"]["phone_format"] = phone_format
    _write_obj(SMS_GATEWAY_OBJ, cur)
    return cur




# ==================================================================
# 5. THANK-YOU SMS LOG (per church per week for offerings received)
# ==================================================================
THANK_YOU_SMS_TAB = "thank_you_sms_log"


def list_thank_you_sms(church_id=None, limit=200):
    rows = _read_tab(THANK_YOU_SMS_TAB)
    if church_id:
        rows = [r for r in rows if r.get("church_id") == church_id]
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return rows[:limit]


def insert_thank_you_sms(payload):
    status = payload.get("status", "queued")  # queued/sent/failed/dry_run
    rec = {
        "id": _new_id("TY"),
        "church_id": payload.get("church_id", ""),
        "church_name": payload.get("church_name", ""),
        "week_date": payload.get("week_date", ""),
        "total_offering": _to_float(payload.get("total_offering", 0)),
        "recipient_phone": payload.get("recipient_phone", ""),
        "recipient_name": payload.get("recipient_name", ""),
        # V1.14: extra recipients (custom contacts the parish pastor added
        # beyond the leader — list of {name, phone}). Empty list by default.
        "extra_contacts": payload.get("extra_contacts", []),
        "message": payload.get("message", ""),
        "sent_by": payload.get("sent_by", ""),
        "sent_by_name": payload.get("sent_by_name", ""),
        "status": status,  # queued/sent/failed/dry_run
        "gateway_response": payload.get("gateway_response", ""),
        "created_at": _now_iso(),
        # V1.14: Auto-send queue bookkeeping. queued_at is set when the row
        # is created in a not-yet-sent state; sent_at when the scheduler
        # (or a manual send) finally delivers it; attempts counts retries.
        "queued_at": _now_iso() if status in ("queued", "dry_run") else None,
        "sent_at": _now_iso() if status == "sent" else None,
        "attempts": 0,
    }
    rows = _read_tab(THANK_YOU_SMS_TAB)
    rows.append(rec)
    _write_tab(THANK_YOU_SMS_TAB, rows)
    return rec


def update_thank_you_sms(rec_id, updates):
    """Patch a thank-you SMS row by id (used by the auto-send scheduler
    and by manual re-send). Merges `updates` into the existing record.
    Returns the updated record, or None if not found."""
    if not rec_id:
        return None
    rows = _read_tab(THANK_YOU_SMS_TAB)
    for r in rows:
        if r.get("id") == rec_id:
            r.update(updates)
            _write_tab(THANK_YOU_SMS_TAB, rows)
            return r
    return None


def list_pending_thank_you_sms(limit=200):
    """Rows still awaiting delivery — status 'queued' or 'dry_run'.
    The auto-send scheduler drains this list when the gateway is live."""
    rows = _read_tab(THANK_YOU_SMS_TAB)
    pending = [r for r in rows if r.get("status") in ("queued", "dry_run")]
    # Oldest first — fair delivery order, and queued_at is set at insert.
    pending.sort(key=lambda x: x.get("queued_at") or x.get("created_at", ""))
    return pending[:limit]


# ==================================================================
# 6. SCHEDULE CATEGORY — extend create_schedule to accept category.
#    list_schedules already echoes whatever is stored, so we only need
#    a thin wrapper that injects the category before delegating.
# ==================================================================
def create_categorized_schedule(payload):
    """Create a schedule REQUEST with an optional `category`. The
    schedule starts in status 'pending' so the church pastor can approve
    or decline it; once approved it transitions to 'approved' (and the
    minister can later mark it 'done')."""
    cat = payload.get("category", "")
    rec = db.create_schedule(payload)
    if rec:
        # Patch the stored record: set status=pending (it defaulted to
        # 'upcoming') and attach the category.
        rows = _read_tab(SCHEDULES_TAB)
        for r in rows:
            if r.get("id") == rec.get("id"):
                r["status"] = "pending"
                if cat:
                    r["category"] = cat
                rec = r
                break
        _write_tab(SCHEDULES_TAB, rows)
    return rec


# ==================================================================
# 7. RECEPTION OVERVIEW (parish) — requests / approved / baptized
# ==================================================================
def list_baptized_members(church_id=None):
    """Members who have a baptism_date (i.e. have been baptized)."""
    rows = _read_tab(MEMBERS_TAB)
    out = []
    for m in rows:
        if m.get("deceased"):
            continue
        if not m.get("active", True):
            continue
        if not m.get("baptism_date"):
            continue
        if church_id and m.get("church_id") != church_id:
            continue
        out.append(m)
    out.sort(key=lambda x: x.get("baptism_date", ""), reverse=True)
    return out


def reception_overview():
    """Parish-wide reception summary: pending requests, approved (with
    member created), and baptized members grouped by church."""
    reqs = _read_tab(SERVICE_REQUESTS_TAB)
    pending = [r for r in reqs if r.get("status") == "pending"]
    approved = [r for r in reqs if r.get("status") == "approved"]
    baptized = list_baptized_members()
    # Group baptized by church.
    by_church = {}
    for m in baptized:
        cid = m.get("church_id", "")
        c = find_church(cid)
        cname = c.get("name", cid) if c else cid
        by_church.setdefault(cname, 0)
        by_church[cname] += 1
    return {
        "pending_count": len(pending),
        "approved_count": len(approved),
        "baptized_count": len(baptized),
        "baptized_by_church": by_church,
        "pending": pending,
        "approved": approved,
        "baptized": baptized,
    }


# ==================================================================
# 8. ESCALATION WITH DELEGATION — extend service_requests.
#    The parish pastor escalates a request and may ASSIGN it to another
#    user (delegate) with feedback. The assignee is recorded on the
#    request so the panel can show "followed up by X".
# ==================================================================
def escalate_service_request(req_id, parish_user, assignee_user=None,
                             feedback=""):
    """Parish escalates a service request and optionally delegates it to
    another user for follow-up. Sets status to 'escalated'."""
    rows = _read_tab(SERVICE_REQUESTS_TAB)
    rec = None
    for r in rows:
        if r.get("id") == req_id:
            r["status"] = "escalated"
            r["escalated_by"] = parish_user.get("id", "")
            r["escalated_by_name"] = parish_user.get("name", "")
            r["escalated_at"] = _now_iso()
            r["escalation_feedback"] = feedback
            if assignee_user:
                r["escalated_to_user_id"] = assignee_user.get("id", "")
                r["escalated_to_name"] = assignee_user.get("name", "")
                r["escalated_to_role"] = assignee_user.get("role", "")
            rec = r
            break
    if not rec:
        return None
    _write_tab(SERVICE_REQUESTS_TAB, rows)
    log_activity({
        "actor_id": parish_user.get("id", ""),
        "actor_name": parish_user.get("name", ""),
        "actor_role": parish_user.get("role", ""),
        "church_id": rec.get("church_id", ""),
        "action": "REQUEST_ESCALATED",
        "target": rec.get("christian_name", ""),
        "detail": (f"delegated to {assignee_user.get('name','—')}"
                   if assignee_user else feedback[:80]),
        "scope": "parish",
    })
    return rec
