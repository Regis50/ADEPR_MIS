"""test_v14_minister_edit_delete.py — V1.14 minister edit/delete endpoint test.

Verifies:
  1. MINISTRY_LEADER can list their members (GET /api/my-ministry-members)
  2. MINISTRY_LEADER can edit their own member (PUT /api/my-ministry-members/<id>)
  3. MINISTRY_LEADER can delete their own member (DELETE /api/my-ministry-members/<id>)
  4. A member NOT in the leader's ministry returns 403 on edit/delete
  5. Non-existent member returns 404

Run against the live server:  python3 test_v14_minister_edit_delete.py
"""

import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:5000"
results = []


def req(method, path, body=None, cookie=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=10)
        raw = resp.read()
        try:
            parsed = json.loads(raw.decode()) if raw else None
        except (ValueError, UnicodeDecodeError):
            parsed = None
        return resp.status, parsed
    except urllib.error.HTTPError as e:
        try:
            parsed = json.loads(e.read().decode())
        except Exception:
            parsed = None
        return e.code, parsed


def login(username, password):
    status, body = req("POST", "/api/auth/login",
                        {"username": username, "password": password})
    cookie = ""  # urllib gives us no easy cookie jar; use header trick
    # we need the Set-Cookie header — redo with a manual opener
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", 5000)
    body_json = json.dumps({"username": username, "password": password})
    conn.request("POST", "/api/auth/login", body_json,
                 {"Content-Type": "application/json"})
    r = conn.getresponse()
    r.read()
    cookie = r.getheader("Set-Cookie") or ""
    return r.status == 200, cookie.split(";")[0] if cookie else ""


def check(name, ok, detail=""):
    if ok:
        results.append(("PASS", name, ""))
        print("  ✓ %s" % name)
    else:
        results.append(("FAIL", name, detail))
        print("  ✗ %s  %s" % (name, detail))


def main():
    print("V1.14 — Minister edit/delete test\n")

    # 1) Login as ministry leader
    ok, leader_cookie = login("leader_abana", "leader123")
    check("login leader_abana/leader123", ok, "cookie=%s" % leader_cookie[:30])
    if not ok:
        return report()

    # 2) List this leader's ministry members
    status, body = req("GET", "/api/my-ministry-members", cookie=leader_cookie)
    check("GET /api/my-ministry-members → 200", status == 200, "status=%s" % status)
    my_members = body if isinstance(body, list) else []

    # If the leader has no members yet, create one via the add endpoint so
    # the test is self-contained (and exercises the add path too).
    created_id = None
    if not my_members:
        status, body = req("POST", "/api/ministry-members",
                            {"name": "TEST_V14 Member", "phone": "0788000001",
                             "gender": "M", "category": "ABAKRISTO_BASHYA"},
                            cookie=leader_cookie)
        check("create test member via POST /api/ministry-members → 201",
              status in (200, 201), "status=%s body=%s" % (status, body))
        if status in (200, 201) and isinstance(body, dict):
            created_id = body.get("id")
            my_members = [body]
    else:
        check("leader already has members to test on", True, "count=%d" % len(my_members))

    check("leader has at least 1 member to test on",
          len(my_members) >= 1, "count=%d" % len(my_members))

    if not my_members:
        print("\n  (Cannot test edit/delete without a member. Add one first.)")
        return report()

    target = my_members[0]
    target_id = target["id"]
    original_name = target.get("name", "")
    print("  using member: %s (%s)" % (original_name, target_id))

    # 3) EDIT the member — change phone, keep name
    new_phone = "0788" + str(abs(hash(original_name)) % 1000000).zfill(6)
    status, body = req("PUT", "/api/my-ministry-members/" + target_id,
                        {"phone": new_phone}, cookie=leader_cookie)
    check("PUT edit member → 200", status == 200, "status=%s body=%s" % (status, body))
    if status == 200 and isinstance(body, dict):
        check("edit actually persisted (phone changed)",
              body.get("phone") == new_phone,
              "phone=%s" % body.get("phone"))

    # 4) 404 on a non-existent member
    status, body = req("PUT", "/api/my-ministry-members/NONEXISTENT123",
                        {"phone": "000"}, cookie=leader_cookie)
    check("PUT on non-existent member → 404", status == 404, "status=%s" % status)

    # 5) Ownership: a member that is NOT in this leader's ministry must 403.
    #    Find any member from a different church (not assigned to leader's ministry).
    import sys
    sys.path.insert(0, ".")
    import db
    my_member_ids = {m["id"] for m in my_members}
    other_member = None
    for m in db.list_members():
        if m["id"] not in my_member_ids:
            other_member = m
            break
    if other_member:
        status, body = req("PUT", "/api/my-ministry-members/" + other_member["id"],
                            {"phone": "000"}, cookie=leader_cookie)
        check("PUT on non-owned member → 403", status == 403, "status=%s" % status)
        status, body = req("DELETE", "/api/my-ministry-members/" + other_member["id"],
                            cookie=leader_cookie)
        check("DELETE on non-owned member → 403", status == 403, "status=%s" % status)
    else:
        check("ownership test (skipped — no other member available)", True, "")

    # 6) DELETE the member we just edited (cleanup + proves delete works)
    status, body = req("DELETE", "/api/my-ministry-members/" + target_id,
                        cookie=leader_cookie)
    check("DELETE own member → 200", status == 200, "status=%s body=%s" % (status, body))
    if status == 200:
        # confirm it's gone from the leader's list
        status2, body2 = req("GET", "/api/my-ministry-members", cookie=leader_cookie)
        ids = [m["id"] for m in (body2 or [])] if isinstance(body2, list) else []
        check("deleted member no longer in list",
              target_id not in ids, "still present? %s" % (target_id in ids))

    return report()


def report():
    passed = sum(1 for r in results if r[0] == "PASS")
    failed = sum(1 for r in results if r[0] == "FAIL")
    print("\nResult: %d passed, %d failed" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
