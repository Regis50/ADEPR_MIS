"""test_smoke.py — Quick smoke test of the ADEPR MIS.

Run with:  python3 test_smoke.py
Starts the server, runs through each role's login + key endpoints,
then shuts down. Prints a summary at the end.
"""

import os
import sys
import time
import json
import subprocess
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
        # decode safely — binary PDF/Excel content may not be valid UTF-8
        try:
            body_out = raw.decode()
        except UnicodeDecodeError:
            body_out = "<binary %d bytes>" % len(raw)
        out_cookie = resp.headers.get("Set-Cookie", "")
        return resp.status, body_out, out_cookie
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            body_out = raw.decode()
        except UnicodeDecodeError:
            body_out = "<binary %d bytes>" % len(raw)
        return e.code, body_out, ""
    except Exception as e:
        return 0, str(e), ""


def check(label, ok, extra=""):
    mark = "✅" if ok else "❌"
    results.append((label, ok))
    print(f"{mark} {label} {('— ' + extra) if extra else ''}")


def login(username, password):
    status, body, cookie = req("POST", "/api/auth/login",
                                {"username": username, "password": password})
    cookie_only = cookie.split(";")[0] if cookie else ""
    return status == 200, cookie_only, body


def main():
    print("=" * 60)
    print("ADEPR MIS — Smoke Test")
    print("=" * 60)

    # Start server
    print("\n🚀 Starting server...")
    proc = subprocess.Popen([sys.executable, "app.py"],
                            cwd=os.path.dirname(os.path.abspath(__file__)),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Wait for boot
    for _ in range(20):
        try:
            status, _, _ = req("GET", "/health")
            if status == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)

    ok, _, _ = req("GET", "/health")
    check("Server boots", ok)

    try:
        # ---------- PARISH PASTOR ----------
        print("\n--- Parish Pastor (parish / parish123) ---")
        ok, parish_cookie, body = login("parish", "parish123")
        check("Login", ok)
        if not ok:
            print(body)
            return

        status, body, _ = req("GET", "/api/dashboard", cookie=parish_cookie)
        d = json.loads(body) if status == 200 else {}
        check("Dashboard KPIs", status == 200 and "kpis" in d,
              f"churches={d.get('kpis', {}).get('total_churches')}")

        status, body, _ = req("GET", "/api/churches", cookie=parish_cookie)
        churches = json.loads(body) if status == 200 else []
        check("List churches", status == 200 and len(churches) > 0,
              f"{len(churches)} churches")

        status, body, _ = req("GET", "/api/members", cookie=parish_cookie)
        members = json.loads(body) if status == 200 else []
        check("List members", status == 200 and len(members) > 0,
              f"{len(members)} members")

        status, body, _ = req("GET", "/api/ministries", cookie=parish_cookie)
        mins = json.loads(body) if status == 200 else []
        check("List ministries", status == 200 and len(mins) > 0,
              f"{len(mins)} ministries")

        status, body, _ = req("GET", "/api/offerings", cookie=parish_cookie)
        offs = json.loads(body) if status == 200 else []
        check("List offerings", status == 200 and len(offs) > 0,
              f"{len(offs)} offerings")

        status, body, _ = req("GET", "/api/rankings", cookie=parish_cookie)
        ranks = json.loads(body) if status == 200 else []
        check("Rankings", status == 200 and len(ranks) > 0,
              f"top: {ranks[0].get('name') if ranks else '?'} #{ranks[0].get('rank') if ranks else '?'}")

        status, body, _ = req("GET", "/api/users", cookie=parish_cookie)
        users = json.loads(body) if status == 200 else []
        check("List users", status == 200 and len(users) > 0,
              f"{len(users)} accounts")

        status, body, _ = req("POST", "/api/sms/preview-recipients",
                              body={"target_role": "ALL"}, cookie=parish_cookie)
        pr = json.loads(body) if status == 200 else {}
        check("SMS preview recipients", status == 200 and "recipients" in pr,
              f"{pr.get('count')} recipients")

        status, body, _ = req("POST", "/api/sms/broadcast",
                              body={"title": "Test", "message": "Test SMS",
                                    "target_role": "CHURCH_PASTOR", "dry_run": True},
                              cookie=parish_cookie)
        br = json.loads(body) if status == 200 else {}
        check("SMS broadcast (dry run)", status == 200 and br.get("ok"),
              f"sent={br.get('broadcast', {}).get('sent')}")

        status, _, _ = req("GET", "/api/reports/weekly", cookie=parish_cookie)
        check("Generate weekly PDF", status == 200)

        status, _, _ = req("GET", "/api/export/weekly", cookie=parish_cookie)
        check("Generate weekly Excel", status == 200)

        # ---------- CHURCH PASTOR ----------
        print("\n--- Church Pastor (ruhango / church123) ---")
        ok, church_cookie, _ = login("ruhango", "church123")
        check("Login", ok)
        if ok:
            status, body, _ = req("GET", "/api/my-church", cookie=church_cookie)
            mc = json.loads(body) if status == 200 else {}
            check("Get own church", status == 200 and "name" in mc,
                  f"{mc.get('name')} ({mc.get('members_count')} members)")

            status, body, _ = req("GET", "/api/my-members", cookie=church_cookie)
            mm = json.loads(body) if status == 200 else []
            check("List own members", status == 200 and len(mm) >= 0,
                  f"{len(mm)} members")

            # Try to record an offering
            status, body, _ = req("POST", "/api/my-offerings",
                                  body={
                                      "week_date": "2026-11-08",
                                      "abihannye": 5, "abana": 30, "abagarutse": 2,
                                      "items": [
                                          {"category": "AMATURO", "amount": 50000},
                                          {"category": "ICYACUMI_MOMO", "amount": 15000},
                                      ],
                                  }, cookie=church_cookie)
            check("Record offering", status == 201, f"total={json.loads(body).get('total') if status==201 else '?'}")

            status, body, _ = req("GET", "/api/my-rank", cookie=church_cookie)
            check("Get own rank", status == 200)

            # Must NOT have parish endpoints
            status, _, _ = req("GET", "/api/churches", cookie=church_cookie)
            check("Cannot access parish endpoint", status == 403)

        # ---------- MINISTRY LEADER ----------
        print("\n--- Ministry Leader (leader_abana / leader123) ---")
        ok, min_cookie, _ = login("leader_abana", "leader123")
        check("Login", ok)
        if ok:
            status, body, _ = req("GET", "/api/my-ministry", cookie=min_cookie)
            mn = json.loads(body) if status == 200 else {}
            check("Get own ministry", status == 200 and "name" in mn,
                  f"{mn.get('name')}")

            status, body, _ = req("GET", "/api/my-ministry-members", cookie=min_cookie)
            mem = json.loads(body) if status == 200 else []
            check("List ministry members", status == 200, f"{len(mem)} members")

            status, _, _ = req("GET", "/api/my-church", cookie=min_cookie)
            check("Cannot access church endpoint", status == 403)

    finally:
        proc.terminate()
        proc.wait(timeout=5)

    # Summary
    print("\n" + "=" * 60)
    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"SUMMARY: {passed}/{total} passed")
    print("=" * 60)
    if passed != total:
        for label, ok in results:
            if not ok:
                print(f"  ❌ {label}")
        sys.exit(1)


if __name__ == "__main__":
    main()
