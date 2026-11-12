"""
sms.py — SMS broadcast logic (Tracar / HTTP gateway).

This module follows the reference pattern from the ADEPR Ruhango weekly-report
automation (send_sms.py): a single HTTP gateway endpoint, a bearer token, a
DRY_RUN flag, Rwanda phone normalization, send_one_sms() + broadcast().

Configuration source (in priority order, so the UI panel drives real sends):
  1. UI panel  →  db_v13.load_sms_gateway()  (sms_gateway.json)
                  fields: endpoint, token, sender_id, phone, dry_run
  2. env vars  →  SMS_GATEWAY_URL / SMS_GATEWAY_TOKEN / SMS_DRY_RUN
  3. defaults  →  http://192.168.1.169:8082, no token, dry_run=True

Send pattern (unchanged from the reference):
  POST {endpoint}/send-sms   form-encoded {phone, message}   Bearer {token}
  DRY_RUN → return a synthetic OK without touching the network.

The module-level SMS_GATEWAY_URL / SMS_GATEWAY_TOKEN / DRY_RUN_DEFAULT
constants are kept for backwards compatibility (other modules import them),
but the live values are read from the UI panel at send time so a config
change in the panel takes effect without a restart.
"""

import os
import requests

# --- Module-level defaults (env vars). Live config is read in _gateway(). ---
SMS_GATEWAY_URL = os.environ.get("SMS_GATEWAY_URL", "http://192.168.1.169:8082")
SMS_GATEWAY_TOKEN = os.environ.get("SMS_GATEWAY_TOKEN", "")
DRY_RUN_DEFAULT = os.environ.get("SMS_DRY_RUN", "true").lower() != "false"

# Lazy db_v13 import to avoid a circular import at module load time.
_db_v13 = None


def _gateway():
    """Return the live gateway config as a dict.

    UI panel (sms_gateway.json via db_v13.load_sms_gateway()) takes priority;
    env vars are the fallback so the module still works headless.
    """
    global _db_v13
    endpoint = SMS_GATEWAY_URL
    token = SMS_GATEWAY_TOKEN
    dry_run = DRY_RUN_DEFAULT
    auth_mode = "header_raw"
    basic_user = ""
    token_param = "password"
    http_method = "POST"
    phone_param = "to"
    message_param = "message"
    body_format = "json"
    phone_format = "intl"
    url_trailing_slash = True
    timeout = 15          # seconds — matches settings.json gateway_timeout
    delay_between = 1.0   # seconds between sends in a broadcast — matches settings.json delay_between
    try:
        if _db_v13 is None:
            import db_v13
            _db_v13 = db_v13
        gw = _db_v13.load_sms_gateway() or {}
        if gw.get("endpoint"):
            endpoint = gw["endpoint"]
        if gw.get("token"):
            token = gw["token"]
        # The panel dry_run flag is authoritative when the panel has been
        # saved at least once (default gateway ships with dry_run=True).
        dry_run = bool(gw.get("dry_run", dry_run))
        am = (gw.get("auth_mode") or "header_raw").lower()
        if am in ("bearer", "x-api-key", "query", "header_raw", "basic", "none"):
            auth_mode = am
        basic_user = gw.get("basic_user", "") or ""
        token_param = (gw.get("token_param") or "password").strip() or "password"
        hm = str(gw.get("http_method", "POST")).upper()
        http_method = hm if hm in ("POST", "GET") else "POST"
        phone_param = (gw.get("phone_param") or "to").strip() or "to"
        message_param = (gw.get("message_param") or "message").strip() or "message"
        bf = (gw.get("body_format") or "json").lower()
        body_format = bf if bf in ("json", "form") else "json"
        pf = (gw.get("phone_format") or "intl").lower()
        phone_format = pf if pf in ("local", "intl") else "intl"
        url_trailing_slash = bool(gw.get("url_trailing_slash", True))
        # timeout / delay_between come from the panel (settings.json values
        # are the default). Guard against bad types so a corrupt value can't
        # break a real send.
        try:
            t = float(gw.get("timeout", 15))
            timeout = t if t > 0 else 15
        except (TypeError, ValueError):
            timeout = 15
        try:
            d = float(gw.get("delay_between", 1.0))
            delay_between = d if d >= 0 else 1.0
        except (TypeError, ValueError):
            delay_between = 1.0
    except Exception:
        # If db_v13 is unreachable (e.g. running outside the app), keep
        # the env-var / default config so sending still works.
        pass
    return {
        "endpoint": endpoint, "token": token, "dry_run": dry_run,
        "auth_mode": auth_mode, "basic_user": basic_user,
        "token_param": token_param, "http_method": http_method,
        "phone_param": phone_param, "message_param": message_param,
        "body_format": body_format, "phone_format": phone_format,
        "url_trailing_slash": url_trailing_slash,
        "timeout": timeout, "delay_between": delay_between,
    }


def _build_send_url(endpoint, trailing_slash=False):
    """Return the endpoint as configured, optionally appending a trailing
    slash. Traccar's gateway requires the trailing "/" (it routes on it),
    so the panel default is url_trailing_slash=True. Other gateways may not,
    so it is configurable.
    """
    base = (endpoint or "").strip()
    if not base:
        return ""
    if trailing_slash and not base.endswith("/"):
        base = base + "/"
    return base


def _apply_auth(url, headers, token, auth_mode, token_param="password",
                basic_user=""):
    """Apply credentials per the configured scheme. Returns (url, display_url).

    - header_raw → header Authorization: {token}  (NO "Bearer " prefix —
                   this is what Traccar SMS Gateway expects; sending
                   "Bearer {token}" is the #1 cause of an HTTP 401 here)
    - bearer     → header Authorization: Bearer {token}
    - x-api-key  → header X-API-Key: {token}
    - query      → ?{token_param}={token} appended to the URL
    - basic      → HTTP Basic auth with {basic_user}:{token}
    - none       → no auth at all

    display_url is the URL with the token masked (***), safe to show in the
    panel so a 401/403 can be diagnosed without leaking the secret.
    """
    display_url = url
    am = (auth_mode or "header_raw").lower()
    if am == "none":
        return url, display_url
    if am == "basic":
        # requests.auth.HTTPBasicAuth handles encoding; we set it on the
        # call site, but also stash the header here for the display.
        headers["Authorization"] = "Basic (user:password)"
        return url, display_url
    if not token:
        return url, display_url
    if am == "header_raw":
        # Raw token in the Authorization header, no scheme prefix.
        # Traccar SMS Gateway authenticates exactly this way.
        headers["Authorization"] = token
    elif am == "bearer":
        headers["Authorization"] = f"Bearer {token}"
    elif am == "x-api-key":
        headers["X-API-Key"] = token
    elif am == "query":
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{token_param}={token}"
        display_url = url.replace(token, "***")
    return url, display_url


def _format_phone_for_gateway(local_phone, phone_format):
    """Convert a normalized local number (0788123456) to the gateway's
    expected format. Traccar expects +250788123456 (intl); some apps want
    the bare local form. Returns the local form unchanged if conversion
    can't be done safely.
    """
    p = (local_phone or "").strip()
    if phone_format != "intl" or not p:
        return p
    if p.startswith("+250"):
        return p
    if p.startswith("0") and len(p) == 10:
        return "+250" + p[1:]
    if p.startswith("250") and len(p) == 12:
        return "+" + p
    return p


# Rwanda phone normalization: accept 07XXXXXXXX, +2507XXXXXXXX, 2507XXXXXXXX
def normalize_phone(phone):
    if not phone:
        return ""
    s = str(phone).strip().replace(" ", "").replace("-", "")
    if s.startswith("+250"):
        s = "0" + s[4:]
    elif s.startswith("250"):
        s = "0" + s[3:]
    if not s.startswith("0") or len(s) != 10:
        # Last resort: keep digits only
        digits = "".join(c for c in s if c.isdigit())
        if digits.startswith("250") and len(digits) == 12:
            s = "0" + digits[3:]
        elif len(digits) == 9:
            s = "0" + digits
    return s


def send_one_sms(to, message, dry_run=None):
    """Send a single SMS. Returns dict {ok, status, to, response,
    request_url, auth_mode, http_method, body_format, phone_format}.

    dry_run=None means: use the live gateway config (UI panel first, then
    the module default). Pass True/False to force a behaviour for this call.

    All transport details come from the panel config: HTTP method, body
    format (JSON vs form-encoded), the JSON keys / param names for phone
    and message, the phone number format (local vs intl), trailing-slash,
    and the auth scheme (header_raw / bearer / x-api-key / query / basic /
    none). This lets the same code path reproduce any working send script
    exactly — the panel's default matches the proven Traccar pattern
    (POST + JSON {to, message} + raw Authorization header + +250 phone).
    request_url is the URL we hit with the token masked (***), so a
    401/403 can be diagnosed in the panel.
    """
    gw = _gateway()
    endpoint = gw["endpoint"]
    token = gw["token"]
    auth_mode = gw["auth_mode"]
    basic_user = gw["basic_user"]
    token_param = gw["token_param"]
    http_method = gw["http_method"]
    phone_param = gw["phone_param"]
    message_param = gw["message_param"]
    body_format = gw["body_format"]
    phone_format = gw["phone_format"]
    url_trailing_slash = gw["url_trailing_slash"]
    timeout = gw["timeout"]          # seconds — matches settings.json gateway_timeout
    if dry_run is None:
        dry_run = gw["dry_run"]
    # Normalize to local first (canonical), then convert to the gateway's
    # expected format. The returned `to` is what we actually send.
    to_local = normalize_phone(to)
    if not to_local:
        return {"ok": False, "status": -1, "to": to, "response": "invalid number",
                "request_url": "", "auth_mode": auth_mode,
                "http_method": http_method, "body_format": body_format,
                "phone_format": phone_format}
    to = _format_phone_for_gateway(to_local, phone_format)
    if dry_run:
        return {"ok": True, "status": 0, "to": to, "response": "(DRY RUN)",
                "request_url": "", "auth_mode": auth_mode,
                "http_method": http_method, "body_format": body_format,
                "phone_format": phone_format}
    url = _build_send_url(endpoint, url_trailing_slash)
    if not url:
        return {"ok": False, "status": -1, "to": to,
                "response": "no endpoint configured",
                "request_url": "", "auth_mode": auth_mode,
                "http_method": http_method, "body_format": body_format,
                "phone_format": phone_format}
    # Build the payload with the configured key/param names. The same dict
    # is sent as a JSON body (body_format=json) or as form-encoded data
    # (body_format=form); for GET it goes in the query string instead.
    payload = {phone_param: to, message_param: message}
    headers = {}
    if body_format == "json" and http_method != "GET":
        headers["Content-Type"] = "application/json"
    auth = None
    url, display_url = _apply_auth(url, headers, token, auth_mode, token_param,
                                   basic_user)
    if auth_mode == "basic" and basic_user:
        # requests encodes Basic auth itself; remove the placeholder header.
        headers.pop("Authorization", None)
        auth = (basic_user, token or "")
    try:
        if http_method == "GET":
            r = requests.get(url, params=payload, headers=headers, auth=auth,
                             timeout=timeout)
        elif body_format == "json":
            # JSON body — matches the proven Traccar pattern:
            #   POST {to, message}  with  Authorization: <raw token>
            r = requests.post(url, json=payload, headers=headers, auth=auth,
                              timeout=timeout)
        else:
            # Form-encoded body.
            r = requests.post(url, data=payload, headers=headers, auth=auth,
                              timeout=timeout)
        ok = r.status_code == 200
        body = (r.text or "").strip()[:200]
        if not body:
            # An empty body on a non-200 is the classic "gateway refused and
            # said nothing" case — make it explicit so the panel doesn't
            # show a blank "Igisubizo cya gateway".
            body = (f"(gateway yatumiye igisubizo kirimo ubusa — "
                    f"HTTP {r.status_code})")
        return {
            "ok": ok,
            "status": r.status_code,
            "to": to,
            "response": body,
            "request_url": display_url,
            "auth_mode": auth_mode,
            "http_method": http_method,
            "body_format": body_format,
            "phone_format": phone_format,
        }
    except Exception as e:
        return {"ok": False, "status": -1, "to": to, "response": str(e)[:200],
                "request_url": display_url, "auth_mode": auth_mode,
                "http_method": http_method, "body_format": body_format,
                "phone_format": phone_format}


def broadcast(recipients, message, dry_run=None):
    """Send to a list of {name, phone} dicts. Returns summary + per-recipient results.

    Paces sends with `delay_between` seconds (default 1.0s, from settings.json)
    between each message — matches send_sms.py and prevents hammering the
    Traccar gateway, which would otherwise queue or reject bursts. The pause
    is skipped on dry_run and after the last send.
    """
    import time as _time
    gw = _gateway()
    delay = gw.get("delay_between", 1.0)
    results = []
    sent = 0
    failed = 0
    n = len(recipients)
    for i, r in enumerate(recipients):
        phone = r.get("phone") or r.get("telephone") or ""
        if not phone:
            results.append({
                "name": r.get("name", ""),
                "to": phone,
                "ok": False,
                "response": "no phone",
            })
            failed += 1
            continue
        res = send_one_sms(phone, message, dry_run=dry_run)
        results.append({
            "name": r.get("name", ""),
            "to": res["to"],
            "ok": res["ok"],
            "status": res["status"],
            "response": res["response"],
        })
        if res["ok"]:
            sent += 1
        else:
            failed += 1
        # Pace: sleep delay_between seconds between real sends (not on the
        # last one, not on dry_run — those don't touch the gateway).
        if delay > 0 and dry_run is not True and i < n - 1:
            _time.sleep(delay)
    return {
        "sent": sent,
        "failed": failed,
        "total": len(recipients),
        "results": results,
    }
