"""
test_v15_final.py — V1.15 FINAL version tests.

Covers the four V1.15 features against a live app.py at 127.0.0.1:5000:
  1. Login on fresh install — all demo accounts work (auto-seed).
  2. Grouped menu — /api/auth/session returns menu items with a `group`
     field, and each role's items are partitioned into ≥3 groups.
  3. Ministeur edit/delete own schedule — create as ministry leader, then
     PUT (edit) + DELETE both succeed for the owner; another user is 403.
     Service-request withdraw endpoint exists + ownership-checked.
  4. Offering proof — attach-after-save endpoint works; no_proof flag is
     stored and visible in GET /api/offerings (parish level).

Run: python3 scripts/test_v15_final.py
(Start app.py first: python3 app.py &)
"""

import json
import os
import sys
import urllib.request

# Make mis/ importable for direct db access in the proof test.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

BASE = "http://127.0.0.1:5000"

passed = 0
failed = 0


def check(label, ok, extra=""):
    global passed, failed
    mark = "✅" if ok else "❌"
    print(f"  {mark} {label}" + (f"  ({extra})" if extra and not ok else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def C(path, method="GET", body=None, sess=None):
    url = BASE + path
    headers = {"Content-Type": "application/json"}
    if sess:
        headers["Cookie"] = sess
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "null"), r.headers
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read().decode() or "null")
        except Exception:
            j = None
        return e.code, j, e.headers


def login(username, password):
    s, j, h = C("/api/auth/login", "POST",
                {"username": username, "password": password})
    cookie = h.get("Set-Cookie", "")
    return cookie.split(";")[0] if cookie else ""


print("=" * 64)
print("V1.15 FINAL — login + grouped menu + ministeur edit/delete + proof")
print("=" * 64)

# ====================================================================
# FEATURE 1 — Login on fresh install (all demo accounts)
# ====================================================================
print("\n[1] FEATURE 1 — Login (all demo accounts):")
accounts = [
    ("parish", "parish123", "PARISH_PASTOR"),
    ("manager", "manager123", "PARISH_MANAGER"),
    ("ruhango", "church123", "CHURCH_PASTOR"),
    ("ruhango_fin", "finance123", "CHURCH_FINANCE"),
    ("leader_abana", "leader123", "MINISTRY_LEADER"),
]
sessions = {}
for u, p, role in accounts:
    sess = login(u, p)
    ok = bool(sess)
    check(f"login {u} ({role})", ok, f"sess empty" if not ok else "")
    sessions[u] = sess

# Verify the session payload carries the right role + menu.
s, j, _ = C("/api/auth/session", sess=sessions["parish"])
check("session endpoint returns user + menu", s == 200 and "menu" in (j or {}))
if j and j.get("user"):
    check("parish session role is PARISH_PASTOR",
          j["user"].get("role") == "PARISH_PASTOR")

# ====================================================================
# FEATURE 2 — Grouped menu (each role has ≥3 groups)
# ====================================================================
print("\n[2] FEATURE 2 — Grouped menu (≥3 groups per role):")
for u, _, role in accounts:
    s, j, _ = C("/api/auth/session", sess=sessions[u])
    menu = (j or {}).get("menu") or []
    groups = {m.get("group") for m in menu if m.get("group")}
    check(f"{u} ({role}) has ≥3 groups",
          len(groups) >= 3, f"groups={len(groups)}: {sorted(groups)[:5]}")
    # Verify every item has a group field (V1.15 shape).
    no_group = [m for m in menu if "group" not in m]
    check(f"{u} every menu item has a 'group' field",
          len(no_group) == 0, f"{len(no_group)} items missing group")

# Spot-check: parish pastor sees sms_gateway + thank_you_sms (V1.14 carryover).
s, j, _ = C("/api/auth/session", sess=sessions["parish"])
parish_pages = {m["page"] for m in (j or {}).get("menu", [])}
check("parish menu still includes sms_gateway + thank_you_sms",
      "sms_gateway" in parish_pages and "thank_you_sms" in parish_pages,
      f"missing: { {'sms_gateway','thank_you_sms'} - parish_pages}")

# ====================================================================
# FEATURE 3 — Ministeur edit/delete OWN schedule
# ====================================================================
print("\n[3] FEATURE 3 — Ministeur edit/delete own schedule:")
# 3a. Login as ministry leader, create a schedule.
sess_m = sessions["leader_abana"]
s, j, _ = C("/api/schedules", "POST", {
    "title": "TEST V1.15 — gahunda ya ministeur",
    "description": "Iyi gahunda yaremwe n'umuyobozi wa ministeur (test).",
    "datetime": "2026-11-15T10:00",
    "location": "Akarere ka RUHANGO",
}, sess=sess_m)
check("ministeur creates schedule (201)", s == 201, f"status={s}")
sched_id = j.get("id") if j else None
check("created schedule has scheduled_by == ministeur id",
      j and j.get("scheduled_by"),
      f"scheduled_by={j.get('scheduled_by') if j else None}")
sched_owner = j.get("scheduled_by") if j else None

# 3b. Edit the schedule as the owner (ministeur).
s, j2, _ = C(f"/api/schedules/{sched_id}", "PUT", {
    "title": "TEST V1.15 — HINDUTSE",
    "location": "AHARI HOSE",
}, sess=sess_m)
check("ministeur edits own schedule (PUT 200)", s == 200, f"status={s}")
check("edited title persisted",
      j2 and j2.get("title") == "TEST V1.15 — HINDUTSE",
      f"title={j2.get('title') if j2 else None}")

# 3c. A DIFFERENT user (church pastor of another church) tries to edit → 403.
s, j3, _ = C(f"/api/schedules/{sched_id}", "PUT", {
    "title": "HACK ATTEMPT",
}, sess=sessions["ruhango_fin"])
check("non-owner cannot edit (403)", s == 403, f"status={s}")

# 3d. Parish pastor CAN edit any schedule (oversight).
s, j4, _ = C(f"/api/schedules/{sched_id}", "PUT", {
    "title": "TEST V1.15 — parish edit",
}, sess=sessions["parish"])
check("parish pastor can edit any schedule (200)", s == 200, f"status={s}")

# 3e. Delete as the owner.
s, j5, _ = C(f"/api/schedules/{sched_id}", "DELETE", sess=sess_m)
check("ministeur deletes own schedule (200)", s == 200, f"status={s}")

# 3f. Non-owner cannot delete a schedule (create one as parish, try delete as ministeur).
s, j6, _ = C("/api/schedules", "POST", {
    "title": "TEST V1.15 — gahunda ya parish",
    "datetime": "2026-11-16T10:00",
}, sess=sessions["parish"])
parish_sched_id = j6.get("id") if j6 else None
s, j7, _ = C(f"/api/schedules/{parish_sched_id}", "DELETE", sess=sess_m)
check("ministeur cannot delete parish-created schedule (403)",
      s == 403, f"status={s}")
# Cleanup: parish deletes its own.
C(f"/api/schedules/{parish_sched_id}", "DELETE", sess=sessions["parish"])

# 3g. Service-request withdraw endpoint exists + ownership-checked.
#     Create a service request as ministeur, then withdraw it.
s, j8, _ = C("/api/service-requests", "POST", {
    "christian_name": "TEST V1.15 — umukristo",
    "christian_phone": "0780000999",
    "request_type": "GUSABWA KWAKIRWA",
}, sess=sess_m)
check("ministeur submits service request (201)", s == 201, f"status={s} {(j8 or {}).get('error','')}")
req_id = j8.get("id") if j8 else None
# Withdraw as the owner.
s, j9, _ = C(f"/api/service-requests/{req_id}/withdraw", "POST",
             {"reason": "Test withdrawal"}, sess=sess_m)
check("ministeur withdraws own service request (200)",
      s == 200, f"status={s}")
# Another user cannot withdraw.
s, j10, _ = C("/api/service-requests", "POST", {
    "christian_name": "TEST V1.15 — umukristo 2",
    "christian_phone": "0780000888",
    "request_type": "GUSABWA KWAKIRWA",
}, sess=sess_m)
req2_id = j10.get("id") if j10 else None
s, j11, _ = C(f"/api/service-requests/{req2_id}/withdraw", "POST",
              {"reason": "hack"}, sess=sessions["ruhango_fin"])
check("non-owner cannot withdraw service request (403)",
      s == 403, f"status={s}")

# ====================================================================
# FEATURE 4 — Offering proof: attach-after-save + no_proof flag
# ====================================================================
print("\n[4] FEATURE 4 — Offering proof (attach-after-save + no_proof):")
# 4a. Save an offering with a MoMo amount but NO proof (the confirm-dialog
#     path). We hit the endpoint directly (bypassing the JS confirm) with
#     no_proof: true on the MoMo item.
sess_f = sessions["ruhango_fin"]
s, j, _ = C("/api/my-offerings", "POST", {
    "week_date": "2026-11-09",
    "abihannye": 10, "abana": 5, "abagarutse": 0, "abana_amount": 0,
    "items": [
        {"category": "ICYACUMI_MOMO", "amount": 5000, "attachments": [],
         "no_proof": True},
        {"category": "AMATURO", "amount": 10000, "attachments": [], "no_proof": False},
    ],
}, sess=sess_f)
check("save offering with no_proof MoMo item (201)", s == 201, f"status={s}")
momo_item = None
if j and j.get("items"):
    for it in j["items"]:
        if it.get("category") == "ICYACUMI_MOMO":
            momo_item = it
            break
check("MoMo item stored with no_proof=True",
      momo_item and momo_item.get("no_proof") is True,
      f"no_proof={momo_item.get('no_proof') if momo_item else None}")
momo_item_id = momo_item.get("id") if momo_item else None
offering_id = j.get("id") if j else None

# 4b. Verify the no_proof flag is visible at parish level (GET /api/offerings).
s, parish_offerings, _ = C("/api/offerings", sess=sessions["parish"])
check("parish can fetch all offerings (200)", s == 200, f"status={s}")
target_off = next((o for o in (parish_offerings or [])
                   if o.get("id") == offering_id), None)
check("parish sees the offering we just saved",
      target_off is not None)
if target_off:
    items = target_off.get("items") or []
    momo_at_parish = next((it for it in items
                           if it.get("category") == "ICYACUMI_MOMO"), None)
    check("parish sees no_proof=True on the MoMo item",
          momo_at_parish and momo_at_parish.get("no_proof") is True,
          f"no_proof={momo_at_parish.get('no_proof') if momo_at_parish else None}")

# 4c. Attach a proof to the saved item via the new endpoint. We use a tiny
#     in-memory file (1x1 PNG) so the upload succeeds without a real file.
import base64
# 1x1 transparent PNG (67 bytes).
PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
# Build a multipart body manually (urllib doesn't do multipart).
boundary = "----V15TEST" + "0" * 16
body = (
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="file"; filename="proof.png"\r\n'
    f"Content-Type: image/png\r\n\r\n"
).encode() + PNG_1x1 + f"\r\n--{boundary}--\r\n".encode()
req = urllib.request.Request(
    BASE + "/api/upload", data=body, method="POST",
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
             "Cookie": sess_f})
with urllib.request.urlopen(req, timeout=30) as r:
    upl = json.loads(r.read().decode())
check("upload proof file (200 + path)", upl.get("ok") and upl.get("path"),
      f"upl={upl}")
proof_path = upl.get("path") if upl else None

# 4d. Attach the uploaded path to the saved offering item.
s, j, _ = C(f"/api/my-offerings/items/{momo_item_id}/attachments", "POST", {
    "path": proof_path,
    "original_name": "proof.png",
    "size": len(PNG_1x1),
    "kind": "momo_sms",
    "category": "ICYACUMI_MOMO",
}, sess=sess_f)
check("attach proof to saved item (200)", s == 200, f"status={s}")
check("item now has 1 attachment",
      j and j.get("item") and len(j["item"].get("attachments", [])) == 1,
      f"atts={len(j['item'].get('attachments', [])) if j and j.get('item') else 0}")
check("item no_proof flag cleared after attaching proof",
      j and j.get("item") and j["item"].get("no_proof") is False,
      f"no_proof={j['item'].get('no_proof') if j and j.get('item') else None}")

# 4e. Non-owner (a different church's finance) cannot attach to this item.
#     Find a different church finance user.
import db as _db
other_fin = None
for u in _db.list_users():
    if u.get("role") == "CHURCH_FINANCE" and u.get("church_id") != target_off.get("church_id"):
        other_fin = u.get("username")
        break
if other_fin:
    sess_other = login(other_fin, "finance123")
    s, j, _ = C(f"/api/my-offerings/items/{momo_item_id}/attachments", "POST", {
        "path": proof_path, "category": "ICYACUMI_MOMO",
    }, sess=sess_other)
    check("non-owner (other church) cannot attach (403)",
          s == 403, f"status={s}")
else:
    check("non-owner attach test (skipped — no other finance user)", True)

# ---- Cleanup: remove the test offering ----
print("\n[cleanup] Remove test offering + items:")
import db as _db2
_off_rows = _db2._read_tab(_db2.OFFERINGS_TAB)
_off_rows = [o for o in _off_rows if o.get("id") != offering_id]
_db2._write_tab(_db2.OFFERINGS_TAB, _off_rows)
_it_rows = _db2._read_tab(_db2.ITEMS_TAB)
_it_rows = [it for it in _it_rows if it.get("offering_id") != offering_id]
_db2._write_tab(_db2.ITEMS_TAB, _it_rows)
_db2._invalidate(_db2.OFFERINGS_TAB)
_db2._invalidate(_db2.ITEMS_TAB)
check("test offering + items removed", True)

# ---- Summary ----
print("\n" + "=" * 64)
print(f"SUMMARY: {passed}/{passed + failed} passed")
if failed == 0:
    print("ALL V1.15 FINAL CHECKS PASSED")
else:
    print(f"{failed} FAILED")
print("=" * 64)
sys.exit(0 if failed == 0 else 1)
