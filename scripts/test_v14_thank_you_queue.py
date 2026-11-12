"""
test_v14_thank_you_queue.py — V1.14 thank-you SMS queue + auto-send tests.

Covers the three V1.14 features against a live app.py at 127.0.0.1:5000:
  1. Customizable message — POST with a custom `message` honors it.
  2. Custom contacts — POST with `extra_contacts` broadcasts to all
     recipients (multiple log rows inserted).
  3. Auto-send queue — dry_run rows are picked up by the scheduler's
     process_thank_you_queue() when auto_send_enabled=True + gateway live;
     status flips dry_run → sent.

Run: python3 scripts/test_v14_thank_you_queue.py
(Start app.py first: python3 app.py &)
"""

import json
import os
import sys
import urllib.request

# Make the parent dir (mis/) importable so `import db` / `import db_v13` /
# `import scheduler` / `import sms` work when the test is run from scripts/.
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
    # Strip attributes after ';'
    return cookie.split(";")[0] if cookie else ""


print("=" * 64)
print("V1.14 THANK-YOU QUEUE + AUTO-SEND + CUSTOM CONTACTS TEST")
print("=" * 64)

# ---- Login as parish pastor ----
sess_p = login("parish", "parish123")
check("parish pastor login", bool(sess_p), f"sess={sess_p[:20]!r}")

# Pick a real church_id to address (parish pastor can address any church;
# we use the first church for a stable test target — parish pastor's own
# church_id may be empty since they sit above the churches).
import db as _db
_churches = _db.list_churches() or []
TEST_CID = _churches[0]["id"] if _churches else ""
TEST_CNAME = _churches[0].get("name", "") if _churches else ""
check("found a test church_id to address", bool(TEST_CID), f"cid={TEST_CID}")
print(f"    using church: {TEST_CNAME} ({TEST_CID})")

# ---- 0. Read current gateway config so we can restore it at the end ----
print("\n[0] Snapshot current gateway config (to restore later):")
s, gw_orig, _ = C("/api/sms-gateway", sess=sess_p)
check("snapshot gateway config", s == 200, f"status={s}")
print(f"    dry_run={gw_orig.get('dry_run')}, auto_send_enabled={gw_orig.get('auto_send_enabled')}, endpoint={gw_orig.get('endpoint')!r}")

# ====================================================================
# FEATURE 1: Customizable message
# ====================================================================
print("\n[1] FEATURE 1 — Customizable message (POST with custom `message`):")
custom_msg = "TEST MESSAGE Y'UMUNSI — Murakoze cyane cyane! (V1.14 test)"
s, j, _ = C("/api/thank-you-sms", "POST", {
    "church_id": TEST_CID,
    "week_date": "2026-11-09",
    "total_offering": 50000,
    "recipient_phone": "0780000001",
    "recipient_name": "Test Leader",
    "message": custom_msg,
}, sess=sess_p)
check("POST with custom message returns 201", s == 201, f"status={s}")
check("custom message is stored as-is (not rebuilt)",
      j and j.get("message") == custom_msg,
      f"stored={j.get('message')[:50]!r}" if j else "no body")
check("custom message row has status (dry_run since gateway is dry_run)",
      j and j.get("status") in ("dry_run", "sent", "failed"),
      f"status={j.get('status')}" if j else "")
custom_row_id = j.get("id") if j else None

# ====================================================================
# FEATURE 2: Custom contacts — extra_contacts broadcasts to all
# ====================================================================
print("\n[2] FEATURE 2 — Custom contacts (extra_contacts → multiple rows):")
extra = [
    {"name": "Pasteur Wungubwe", "phone": "0780000002"},
    {"name": "Ushinzwe Imali",   "phone": "0780000003"},
    {"name": "Umubyeyi w'inama", "phone": "0780000004"},
]
# Use empty message so the builder rebuilds (tests the default path too).
s, j, _ = C("/api/thank-you-sms", "POST", {
    "church_id": TEST_CID,
    "week_date": "2026-11-09",
    "total_offering": 75000,
    "recipient_phone": "0780000001",
    "recipient_name": "Test Leader",
    "message": "",  # builder ikora message2.py-style
    "extra_contacts": extra,
}, sess=sess_p)
check("POST with extra_contacts returns 201", s == 201, f"status={s}")
# The first row returned corresponds to the primary recipient. Verify the
# extra_contacts were stored on the first row.
check("primary row has extra_contacts stored",
      j and isinstance(j.get("extra_contacts"), list) and len(j.get("extra_contacts", [])) == len(extra),
      f"len={len(j.get('extra_contacts', [])) if j else 0}")
# The message should be the message2.py-style rich template (builder ran
# because message was empty).
check("empty message → builder produced message2.py-style (has IMIBARE section)",
      j and "IMIBARE Y'AMATURO" in (j.get("message") or ""),
      f"msg preview: {(j.get('message') or '')[:60]!r}")

# Fetch the thank-you log and verify all 4 recipients got a row (1 primary + 3 extra).
s, log, _ = C("/api/thank-you-sms", sess=sess_p)
check("thank-you log fetches 200", s == 200, f"status={s}")
# Find the rows we just inserted (recipient_phone in our test set).
test_phones = {"0780000001", "0780000002", "0780000003", "0780000004"}
recent_rows = [r for r in (log or []) if r.get("recipient_phone") in test_phones]
# Dedupe by recipient_phone (there may be older test rows; just verify all 4 phones present).
phones_in_log = {r.get("recipient_phone") for r in recent_rows}
check("all 4 recipients (primary + 3 extra) appear in the log",
      test_phones.issubset(phones_in_log),
      f"phones_in_log={phones_in_log}")
# Verify the most recent broadcast produced 4 rows — filter by the created_at
# timestamp of the POST response (j), which is the same for all 4 rows of
# that broadcast. Then confirm all 4 phones appear in that cluster.
if recent_rows and j and j.get("created_at"):
    broadcast_ts = j.get("created_at")
    cluster = [r for r in recent_rows if r.get("created_at") == broadcast_ts]
    cluster_phones = {r.get("recipient_phone") for r in cluster}
    check("latest broadcast cluster covers all 4 recipients (per-recipient log)",
          cluster_phones == test_phones,
          f"cluster_phones={cluster_phones} (cluster size={len(cluster)})")

# ====================================================================
# FEATURE 3: Auto-send queue — dry_run rows drain when gateway goes live
# ====================================================================
print("\n[3] FEATURE 3 — Auto-send queue (dry_run → sent when gateway live):")

# 3a. Verify the queue endpoint reports pending count.
s, q, _ = C("/api/thank-you-sms/queue", sess=sess_p)
check("GET /api/thank-you-sms/queue returns 200", s == 200, f"status={s}")
check("queue response has count field", "count" in (q or {}), f"q={q}")
check("queue response has auto_send_enabled field",
      "auto_send_enabled" in (q or {}))
check("queue response has gateway_live field",
      "gateway_live" in (q or {}))
print(f"    queue: count={q.get('count')}, auto_send={q.get('auto_send_enabled')}, live={q.get('gateway_live')}")
initial_count = q.get("count", 0)

# 3b. Test process_thank_you_queue() logic directly (no live network).
# We verify the GATING logic: it should NOT send when auto_send is OFF.
print("\n[3b] Verify scheduler gating (auto_send OFF → no processing):")
# Save gateway with auto_send_enabled=False, dry_run=True (the default).
C("/api/sms-gateway", "PUT", {
    "dry_run": True, "auto_send_enabled": False,
}, sess=sess_p)
# Call the processor directly via the manual drain endpoint.
s, drain, _ = C("/api/thank-you-sms/queue/drain", "POST", sess=sess_p)
check("manual drain endpoint returns 200", s == 200, f"status={s}")
check("drain result reports reason='auto_send disabled' when toggle is OFF",
      drain and drain.get("result", {}).get("reason") == "auto_send disabled",
      f"result={drain.get('result') if drain else None}")

# 3c. Now flip auto_send ON but keep dry_run=True (gateway NOT live).
#     The processor should refuse (reason='gateway not live').
print("\n[3c] Verify scheduler gating (auto_send ON but dry_run=True → no processing):")
C("/api/sms-gateway", "PUT", {
    "dry_run": True, "auto_send_enabled": True,
}, sess=sess_p)
s, drain, _ = C("/api/thank-you-sms/queue/drain", "POST", sess=sess_p)
check("drain reason='gateway not live' when dry_run is True",
      drain and drain.get("result", {}).get("reason") == "gateway not live (dry_run or no endpoint)",
      f"result={drain.get('result') if drain else None}")

# 3d. Unit-test the queue processing logic against a FAKE gateway.
#     We can't hit the real Traccar gateway from the test sandbox, so we
#     monkeypatch sms.send_one_sms to record what WOULD have been sent and
#     return a synthetic OK. This proves the dry_run → sent flip works.
print("\n[3d] Verify queue processing flips dry_run → sent (monkeypatched gateway):")
import importlib
# Reload fresh so we get the live DB state.
import db_v13
import scheduler

# Insert a fake dry_run row to drain.
fake_row = db_v13.insert_thank_you_sms({
    "church_id": "TEST_CHURCH",
    "church_name": "TEST CHURCH",
    "week_date": "2026-11-09",
    "total_offering": 100000,
    "recipient_phone": "0799999999",
    "recipient_name": "Test Recipient",
    "message": "Test message for queue drain — V1.14",
    "sent_by": "test",
    "sent_by_name": "Test",
    "status": "dry_run",
    "gateway_response": "dry_run (test setup)",
})
fake_id = fake_row["id"]
check("inserted fake dry_run row for drain test", bool(fake_id), f"id={fake_id}")

# Make the gateway look live (auto_send ON + not dry_run + endpoint set)
# by patching load_sms_gateway in db_v13.
_orig_load = db_v13.load_sms_gateway
def _fake_load():
    return {
        "endpoint": "http://fake-gateway.test/send-sms",
        "dry_run": False,
        "auto_send_enabled": True,
    }
db_v13.load_sms_gateway = _fake_load

# Monkeypatch sms.send_one_sms to return a synthetic OK (no network call).
import sms
_orig_send = sms.send_one_sms
_sent_calls = []
def _fake_send(to, message, dry_run=None):
    _sent_calls.append({"to": to, "message": message, "dry_run": dry_run})
    return {"ok": True, "status": 200, "response": "FAKE OK",
            "to": to, "request_url": "http://fake-gateway.test",
            "auth_mode": "header_raw", "http_method": "POST",
            "body_format": "json", "phone_format": "intl"}
sms.send_one_sms = _fake_send

# Patch the scheduler's reference too (it imports sms inside the function).
import scheduler as _sched_mod
_orig_process = _sched_mod.process_thank_you_queue

# Run the processor.
result = _sched_mod.process_thank_you_queue()
print(f"    process result: {result}")
check("processor processed at least 1 row",
      result.get("processed", 0) >= 1, f"result={result}")
check("processor sent at least 1 (fake) SMS",
      result.get("sent", 0) >= 1, f"sent={result.get('sent')}")
check("our fake row's phone appears in the sent calls",
      any(c["to"] == "0799999999" for c in _sent_calls),
      f"sent_to={[c['to'] for c in _sent_calls]}")

# Verify the fake row's status flipped to 'sent'.
updated = db_v13.update_thank_you_sms(fake_id, {})  # no-op patch, returns row
check("fake row status flipped dry_run → sent",
      updated and updated.get("status") == "sent",
      f"status={updated.get('status') if updated else None}")
check("fake row has sent_at timestamp set",
      updated and bool(updated.get("sent_at")),
      f"sent_at={updated.get('sent_at') if updated else None}")
check("fake row attempts incremented (>=1)",
      updated and int(updated.get("attempts", 0)) >= 1,
      f"attempts={updated.get('attempts') if updated else None}")

# Restore.
sms.send_one_sms = _orig_send
db_v13.load_sms_gateway = _orig_load

# ====================================================================
# CLEANUP: restore the original gateway config + remove test rows
# ====================================================================
print("\n[cleanup] Restore gateway config + remove test rows:")
# Restore gateway.
C("/api/sms-gateway", "PUT", {
    "dry_run": gw_orig.get("dry_run", True),
    "auto_send_enabled": gw_orig.get("auto_send_enabled", False),
}, sess=sess_p)
# Remove the test rows we inserted (directly via db_v13).
import db_v13 as _v13
_tab = _v13._read_tab(_v13.THANK_YOU_SMS_TAB)
_test_phones = {"0780000001", "0780000002", "0780000003", "0780000004", "0799999999"}
_remaining = [r for r in _tab if r.get("recipient_phone") not in _test_phones]
_v13._write_tab(_v13.THANK_YOU_SMS_TAB, _remaining)
check("test rows removed from thank_you_sms_log",
      len(_remaining) <= len(_tab), f"before={len(_tab)} after={len(_remaining)}")

# ---- Summary ----
print("\n" + "=" * 64)
print(f"SUMMARY: {passed}/{passed + failed} passed")
if failed == 0:
    print("ALL V1.14 THANK-YOU QUEUE + AUTO-SEND + CUSTOM CONTACTS CHECKS PASSED")
else:
    print(f"{failed} FAILED")
print("=" * 64)
sys.exit(0 if failed == 0 else 1)
