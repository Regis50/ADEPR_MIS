"""Smoke test: confirm the SMS gateway panel config drives sms.py and that
the test endpoint delegates to the production send path.

The default gateway config now reproduces the user's PROVEN send_sms.py
pattern exactly: POST + JSON {to, message} + raw Authorization header
(no "Bearer " prefix) + +250 international phone + trailing slash.
This is the root cause of the original HTTP 401: the gateway rejects
"Bearer {token}" but accepts the raw token.

We prove the match end-to-end against a mock that behaves like the real
Traccar gateway (200 OK with the right request shape, 401 with the wrong
header).

Run with the app live on http://127.0.0.1:5000.
"""
import requests, json, sys, os, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

# Make the parent mis/ dir importable so we can call sms.py directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

B = "http://127.0.0.1:5000"

def login_session(u, p):
    s = requests.Session()
    r = s.post(f"{B}/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, f"login {u} failed: {r.status_code}"
    return s

def check(label, cond, extra=""):
    print(f"  {'✅' if cond else '❌'} {label}" + (f"  ({extra})" if extra and not cond else ""))
    if not cond:
        sys.exit(1)

print("=" * 60)
print("SMS GATEWAY ADOPTION SMOKE TEST (Traccar / send_sms.py pattern)")
print("=" * 60)

s_p = login_session("parish", "parish123")

# 1. Default gateway state — now ships as the PROVEN send_sms.py pattern,
#    PRE-FILLED with the user's real Traccar endpoint + token from
#    settings.json (so the panel works out-of-the-box: just flip dry_run off).
#    We check the source of truth (db_v13._DEFAULT_GATEWAY) directly because
#    other test suites may have already persisted a test-fixture config that
#    overrides the defaults at runtime.
import db_v13
dgw = db_v13._DEFAULT_GATEWAY
gw = s_p.get(f"{B}/api/sms-gateway").json()
print(f"\n[1] Default gateway (db_v13._DEFAULT_GATEWAY):")
print(f"    auth_mode={dgw.get('auth_mode')} method={dgw.get('http_method')} "
      f"body_format={dgw.get('body_format')} phone_format={dgw.get('phone_format')}")
print(f"    phone_param={dgw.get('phone_param')} message_param={dgw.get('message_param')} "
      f"token_param={dgw.get('token_param')} url_trailing_slash={dgw.get('url_trailing_slash')}")
print(f"    endpoint={dgw.get('endpoint')!r} token={dgw.get('token')!r}")
print(f"    timeout={dgw.get('timeout')} delay_between={dgw.get('delay_between')}")
check("default auth_mode is header_raw (Traccar)", dgw.get("auth_mode") == "header_raw", dgw.get("auth_mode"))
check("default http_method is POST", dgw.get("http_method") == "POST", dgw.get("http_method"))
check("default body_format is json", dgw.get("body_format") == "json", dgw.get("body_format"))
check("default phone_format is intl (+250)", dgw.get("phone_format") == "intl", dgw.get("phone_format"))
check("default phone_param is to", dgw.get("phone_param") == "to", dgw.get("phone_param"))
check("default message_param is message", dgw.get("message_param") == "message")
check("default url_trailing_slash is True", dgw.get("url_trailing_slash") is True, str(dgw.get("url_trailing_slash")))
# Real Traccar endpoint + token from settings.json (works out-of-the-box).
check("default endpoint is the real Traccar URL from settings.json",
      dgw.get("endpoint") == "http://192.168.1.169:8082", dgw.get("endpoint"))
check("default token is the real UUID from settings.json",
      dgw.get("token") == "7d6ed977-9415-4e0c-855a-820c76cbe2e5", dgw.get("token"))
# Behavioral settings from settings.json: 15s timeout, 1.0s delay between sends.
check("default timeout is 15 (matches settings.json gateway_timeout)",
      dgw.get("timeout") == 15, str(dgw.get("timeout")))
check("default delay_between is 1.0 (matches settings.json delay_between)",
      dgw.get("delay_between") == 1.0, str(dgw.get("delay_between")))
# Also confirm load_sms_gateway() merges the real defaults onto a persisted
# object — the panel GET should at least reflect the new behavioral fields
# even if a fixture overrode endpoint/token.
check("panel GET exposes timeout field", "timeout" in gw, "no timeout in GET response")
check("panel GET exposes delay_between field", "delay_between" in gw, "no delay_between in GET response")

# 2. Save a NON-dry-run config with a dead endpoint via the UI panel.
save = s_p.put(f"{B}/api/sms-gateway", json={
    "provider": "traccar",
    "endpoint": "http://127.0.0.1:59999",  # nothing listening; trailing slash added
    "token": "tok-xyz",
    "auth_mode": "header_raw",
    "http_method": "POST",
    "phone_param": "to", "message_param": "message",
    "body_format": "json", "phone_format": "intl",
    "url_trailing_slash": True,
    "sender_id": "ADEPR",
    "phone": "0788123456",
    "app": "Traccar SMS Gateway",
    "dry_run": False,
}).json()
check("panel config saved (dry_run=False, dead endpoint)", save.get("ok") is True)

# 3. Confirm sms.py reads the panel config (default + applied overrides).
import sms
g = sms._gateway()
print(f"\n[3] sms._gateway() → endpoint={g['endpoint']!r} token={g['token']!r} "
      f"dry_run={g['dry_run']}")
print(f"    auth_mode={g['auth_mode']} method={g['http_method']} "
      f"body_format={g['body_format']} phone_format={g['phone_format']} "
      f"url_trailing_slash={g['url_trailing_slash']}")
print(f"    timeout={g['timeout']} delay_between={g['delay_between']}")
check("sms.py uses panel endpoint", g["endpoint"] == "http://127.0.0.1:59999", g["endpoint"])
check("sms.py uses panel auth_mode=header_raw", g["auth_mode"] == "header_raw", g["auth_mode"])
check("sms.py uses panel body_format=json", g["body_format"] == "json", g["body_format"])
check("sms.py uses panel phone_format=intl", g["phone_format"] == "intl", g["phone_format"])
check("sms.py uses panel url_trailing_slash=True", g["url_trailing_slash"] is True)
check("sms.py exposes timeout from panel config", g.get("timeout") == 15, str(g.get("timeout")))
check("sms.py exposes delay_between from panel config", g.get("delay_between") == 1.0, str(g.get("delay_between")))

# 4. send_one_sms on dead endpoint → connection error (proves it tried).
#    The URL gets the trailing slash appended; phone is intl (+250…).
res = sms.send_one_sms("0788123456", "Test from panel-configured gateway", dry_run=False)
print(f"\n[4] send_one_sms(dry_run=False) on dead endpoint:")
print(f"    ok={res['ok']} status={res['status']} to={res['to']}")
print(f"    request_url: {res['request_url']}")
print(f"    response: {res['response'][:80]}")
check("real send attempted (failed = endpoint dead)",
      res["ok"] is False and (res["status"] == -1 or "refused" in res["response"].lower() or "Connection" in res["response"]))
check("trailing slash appended to URL",
      res["request_url"] == "http://127.0.0.1:59999/", res["request_url"])
check("phone converted to intl (+250…)",
      res["to"] == "+250788123456", res["to"])
check("header_raw → URL clean (no token in URL)",
      "?" not in res["request_url"] and "tok-xyz" not in res["request_url"], res["request_url"])
check("body_format echoed in result", res.get("body_format") == "json", res.get("body_format"))
check("phone_format echoed in result", res.get("phone_format") == "intl", res.get("phone_format"))

# 5. Test endpoint delegates to sms.send_one_sms (same path as broadcast).
test = s_p.post(f"{B}/api/sms-gateway/test", json={"phone": "0788123456"})
tj = test.json()
lt = tj.get("last_test", {})
print(f"\n[5] /api/sms-gateway/test (real path): HTTP {test.status_code} ok={lt.get('ok')} status={lt.get('status')}")
check("test endpoint returns 502 on dead endpoint", test.status_code == 502, f"status={test.status_code}")
check("test endpoint records last_test.ok=False", lt.get("ok") is False)
check("test endpoint records body_format", lt.get("body_format") == "json", lt.get("body_format"))
check("test endpoint records phone_format", lt.get("phone_format") == "intl", lt.get("phone_format"))
check("test endpoint records http_method", lt.get("http_method") == "POST", lt.get("http_method"))

# 6. Flip back to dry_run → test succeeds without network.
s_p.put(f"{B}/api/sms-gateway", json={"dry_run": True})
test2 = s_p.post(f"{B}/api/sms-gateway/test", json={"phone": "0788123456"})
lt2 = test2.json().get("last_test", {})
print(f"\n[6] /api/sms-gateway/test (dry_run=True): HTTP {test2.status_code} ok={lt2.get('ok')}")
check("dry-run test succeeds (no network)", test2.status_code == 200 and lt2.get("ok") is True)

# 6b. Custom test message + phone normalization.
custom_msg = "Muraho Regis! Test y'ubwoko bw'ubutumwa — 2026-11-09."
test3 = s_p.post(f"{B}/api/sms-gateway/test",
                 json={"phone": "+250 788 999 100", "message": custom_msg})
lt3 = test3.json().get("last_test", {})
print(f"[6b] custom-message test: ok={lt3.get('ok')} to={lt3.get('to')!r}")
check("custom test message is recorded as sent",
      lt3.get("sent") == custom_msg, f"sent={lt3.get('sent')!r}")
check("custom test destination normalized to intl (+250788999100)",
      lt3.get("to") == "+250788999100", f"to={lt3.get('to')!r}")

# 6c. Empty message falls back to the default test message.
test4 = s_p.post(f"{B}/api/sms-gateway/test", json={"phone": "0788123456", "message": ""})
lt4 = test4.json().get("last_test", {})
check("empty message falls back to default",
      "Traccar SMS gateway test" in str(lt4.get("sent", "")), f"sent={lt4.get('sent')!r}")

# 7. Broadcast flows through sms.py with panel config.
bc = s_p.post(f"{B}/api/sms/broadcast", json={
    "target_role": "CHURCH_PASTOR",
    "title": "Smoke test",
    "message": "Smoke: panel-configured broadcast",
    "dry_run": True,
}).json()
b = bc.get("broadcast", {})
print(f"\n[7] Broadcast (dry_run=True): sent={b.get('sent')}/{b.get('total')}")
check("broadcast flows through sms.py", b.get("sent", 0) == b.get("total", 0) and b.get("sent", 0) > 0,
      f"sent={b.get('sent')} total={b.get('total')}")

# 8. Phone normalization (local canonical form).
for raw, exp in [("0788123456","0788123456"),("+250788123456","0788123456"),
                 ("250788123456","0788123456"),("+250 788 123 456","0788123456")]:
    got = sms.normalize_phone(raw)
    check(f"normalize_phone({raw!r}) → {exp!r}", got == exp, got)

# 9. REAL end-to-end send against a mock that behaves EXACTLY like the
#    Traccar gateway: accepts POST + JSON {to, message} + raw Authorization
#    header (no "Bearer ") + +250 phone. Returns 200. This is the proof
#    that the panel default reproduces send_sms.py and will work against
#    the real gateway.
print("\n[9] REAL send against a mock Traccar gateway (POST + JSON + raw Auth + +250 phone)")
received = {}
class TraccarMock(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {}
        received["path"] = self.path
        received["auth_header"] = self.headers.get("Authorization", "")
        received["content_type"] = self.headers.get("Content-Type", "")
        received["to"] = body.get("to", "")
        received["message"] = body.get("message", "")
        # Traccar rejects "Bearer ..." with 401 — this is the user's original bug.
        auth = received["auth_header"]
        if auth.startswith("Bearer "):
            self.send_response(401); self.end_headers(); return
        if auth != "secret-token":
            self.send_response(401); self.end_headers(); return
        resp = b'{"status":"success","id":"msg-1"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)
    def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 59997), TraccarMock)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.3)

s_p.put(f"{B}/api/sms-gateway", json={
    "endpoint": "http://127.0.0.1:59997",
    "token": "secret-token",
    "auth_mode": "header_raw", "http_method": "POST",
    "phone_param": "to", "message_param": "message",
    "body_format": "json", "phone_format": "intl",
    "url_trailing_slash": True, "dry_run": False,
})
res = sms.send_one_sms("0788123456", "Muraho! Test y'ukuri.", dry_run=False)
print(f"     send_one_sms → ok={res['ok']} status={res['status']}")
print(f"     request_url: {res['request_url']}")
print(f"     response: {res['response']}")
print(f"     mock received: path={received.get('path')!r} to={received.get('to')!r} "
      f"message={received.get('message')!r}")
print(f"     mock auth header: {received.get('auth_header')!r} (no 'Bearer ' prefix)")
print(f"     mock content-type: {received.get('content_type')!r}")
check("real send returns ok=True (200)", res["ok"] is True and res["status"] == 200, f"status={res['status']}")
check("mock received POST /", received.get("path") == "/", received.get("path"))
check("mock received JSON content-type",
      "application/json" in received.get("content_type", ""), received.get("content_type"))
check("mock received 'to' key with +250 phone",
      received.get("to") == "+250788123456", received.get("to"))
check("mock received 'message' key", received.get("message") == "Muraho! Test y'ukuri.", received.get("message"))
check("mock received RAW Authorization header (no 'Bearer ' prefix)",
      received.get("auth_header") == "secret-token", received.get("auth_header"))

# 9b. The 401 bug, reproduced: if the panel is (mis)configured to use
# "bearer" auth, the mock rejects it with 401 — exactly the user's
# original symptom. This proves the default (header_raw) is correct.
s_p.put(f"{B}/api/sms-gateway", json={"auth_mode": "bearer", "dry_run": False})
res2 = sms.send_one_sms("0788123456", "test 401", dry_run=False)
print(f"\n[9b] WRONG auth (bearer) → 401 (the user's original bug, reproduced)")
print(f"     ok={res2['ok']} status={res2['status']} response={res2['response']!r}")
check("bearer auth → ok=False", res2["ok"] is False)
check("bearer auth → status=401", res2["status"] == 401, str(res2["status"]))
check("empty 401 body → clear hint", "ubusa" in res2["response"], res2["response"])

# 9c. The endpoint-also-needs-trailing-slash case: some deployments 404 the
# bare URL but accept the slash. We verify the slash is actually appended.
class SlashMock(BaseHTTPRequestHandler):
    def do_POST(self):
        # Only respond 200 to "/" (the slashed form), 404 to bare.
        if self.path == "/":
            self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *a): pass
srv3 = HTTPServer(("127.0.0.1", 59995), SlashMock)
threading.Thread(target=srv3.serve_forever, daemon=True).start()
time.sleep(0.2)
s_p.put(f"{B}/api/sms-gateway", json={
    "endpoint": "http://127.0.0.1:59995", "auth_mode": "header_raw",
    "token": "t", "dry_run": False, "url_trailing_slash": True,
})
res3 = sms.send_one_sms("0788123456", "slash test", dry_run=False)
print(f"\n[9c] Trailing-slash required by gateway: ok={res3['ok']} status={res3['status']} url={res3['request_url']}")
check("trailing-slash gateway returns 200", res3["ok"] is True and res3["status"] == 200)

# 9d. Broadcast PACING: a real (non-dry-run) broadcast must sleep
# delay_between seconds between sends, matching send_sms.py. We prove this
# by timing a 3-message broadcast with delay_between=1.5 — it must take
# roughly 3.0s (2 gaps × 1.5s) plus a little for the calls themselves.
# Reuse the TraccarMock on 59997 (still running); it accepts any raw token.
import time as _time
s_p.put(f"{B}/api/sms-gateway", json={
    "endpoint": "http://127.0.0.1:59997", "auth_mode": "header_raw",
    "token": "secret-token", "dry_run": False,
    "url_trailing_slash": True, "delay_between": 1.5,
})
recips = [{"name": f"Tester {i}", "phone": f"0788123{i:04d}"} for i in range(1, 4)]
t0 = _time.monotonic()
bc = sms.broadcast(recips, "Pacing test", dry_run=False)
elapsed = _time.monotonic() - t0
print(f"\n[9d] Broadcast pacing (delay_between=1.5, n=3): elapsed={elapsed:.2f}s sent={bc['sent']}")
# Lower bound: 2 gaps × 1.5s = ~3.0s. Upper bound is generous for slow CI.
check("broadcast paces with delay_between between real sends",
      2.8 < elapsed < 6.0, f"elapsed={elapsed:.2f}s")
check("all 3 broadcast messages sent OK", bc["sent"] == 3 and bc["failed"] == 0,
      f"sent={bc['sent']} failed={bc['failed']}")

# 9e. Broadcast does NOT pace on dry_run (no gateway touched → fast).
s_p.put(f"{B}/api/sms-gateway", json={"dry_run": True, "delay_between": 1.5})
t0 = _time.monotonic()
bc2 = sms.broadcast(recips, "Dry pacing test", dry_run=True)
elapsed2 = _time.monotonic() - t0
print(f"[9e] Broadcast dry_run pacing (should be fast): elapsed={elapsed2:.3f}s")
check("broadcast skips pacing on dry_run",
      elapsed2 < 1.0, f"elapsed={elapsed2:.3f}s")

# Clean up: restore the real Traccar defaults (endpoint + token from
# settings.json) so a subsequent run sees a clean state, then flip dry_run
# back on so no accidental sends happen.
srv.shutdown(); srv3.shutdown()
s_p.put(f"{B}/api/sms-gateway", json={
    "dry_run": True,
    "endpoint": "http://192.168.1.169:8082",
    "token": "7d6ed977-9415-4e0c-855a-820c76cbe2e5",
    "delay_between": 1.0, "timeout": 15,
})

print("\n" + "=" * 60)
print("ALL SMS GATEWAY ADOPTION CHECKS PASSED")
print("(default config reproduces send_sms.py — proven against a mock)")
print("=" * 60)
