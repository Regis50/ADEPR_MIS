"""
reset_demo_accounts.py — Idempotent demo-account repair (V1.12.1).

IMPAMVU: iyi script yaremwe kugira ngo igosore ikibazo cyo "manager na
zone ntibashobora kwinjira" mu gihe ufite data ya kera (V1.9/V1.10/V1.11)
ahubwo y'uko gusegurira data yose hanyuma ukongera ukore seed.

IYI SCRIPT IKORA:
  1. Ku konti 6 z'ibyiciro (parish, manager, ruhango, ruhango_fin,
     leader_abana, zoneru) — hashing password nyayo + status='active'
     + active=True. Niba konti itabaho, irayikora.
  2. Ku zoneru — ikumorera zone_id mu itorero rye (zone ya mbere
     cyangwa iyanditswe nshya), ikandi zone igafata reader_id.
  3. Nta kindi cyandikwa (amaturo, abakristo, budget... byibanda
     byose ntibyahinduka).

IKORESHO:
  cd mis
  python3 reset_demo_accounts.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# (username, password, role, name, phone, email, church_lookup)
# church_lookup: None = parish-level (no church); "by_name:RUHANGO" =
# find church by name; falls back to first church.
DEMO_ACCOUNTS = [
    ("parish", "parish123", "PARISH_PASTOR", "Pasteur Muyobozi wa Paruwasi",
     "0788000000", "paruwasi@adepr.rw", None),
    ("manager", "manager123", "PARISH_MANAGER", "Muyobozi wa Paruwasi",
     "0788000999", "manager@adepr.rw", None),
    ("ruhango", "church123", "CHURCH_PASTOR", "Umushumba w'itorero rya RUHANGO",
     "0788000111", "ruhango@adepr.rw", "by_name:RUHANGO"),
    ("ruhango_fin", "finance123", "CHURCH_FINANCE",
     "Ushinzwe imali w'itorero rya RUHANGO",
     "0788000222", "ruhango_fin@adepr.rw", "by_name:RUHANGO"),
    ("leader_abana", "leader123", "MINISTRY_LEADER",
     "Umuyobozi wa ministeur y'Abana",
     "0788000333", "abana@adepr.rw", "by_name:RUHANGO"),
    ("zoneru", "zone123", "ZONE_READER", "Umuyobozi wa Zone Ruhango",
     "0788000888", "zone@adepr.rw", "by_name:RUHANGO"),
]


def _resolve_church(lookup):
    """Return a church dict (or None) based on the lookup hint."""
    if not lookup:
        return None
    churches = db.list_churches()
    if not churches:
        return None
    if lookup == "first":
        return churches[0]
    if lookup.startswith("by_name:"):
        target = lookup.split(":", 1)[1].strip().upper()
        for c in churches:
            if (c.get("name", "") or "").strip().upper() == target:
                return c
        return churches[0]  # fallback
    return None


def _ensure_zone_for_reader(church_id, church_name):
    """Make sure the zone reader's church has a zone, link the reader to
    it, and return the zone id. Creates a zone if the church has none."""
    if not church_id:
        return ""
    zones = db.list_zones(church_id=church_id)
    if zones:
        return zones[0]["id"]
    zone = db.create_zone({
        "church_id": church_id,
        "name": "Zone ya " + (church_name or "itorero").split()[-1],
        "reader_name": "Umuyobozi wa zone",
        "description": "Zone yo gusanzwe mu itorero rya " + (church_name or ""),
    })
    return zone["id"]


def main():
    print("=" * 64)
    print("Reset ya konti 6 z'ibyiciro (V1.12.1)")
    print("=" * 64)
    rows = db._read_tab(db.USERS_TAB)
    by_user = {r.get("username", "").lower(): r for r in rows}

    results = []
    for uname, pw, role, name, phone, email, church_lookup in DEMO_ACCOUNTS:
        church = _resolve_church(church_lookup)
        church_id = church["id"] if church else ""
        key = uname.lower()
        if key in by_user:
            r = by_user[key]
            r["password_hash"] = db.hash_password(pw)
            r["password_algo"] = db.HASH_ALGO
            r["password_changed_at"] = db._now_iso()
            r["role"] = role
            r["name"] = name
            r["phone"] = phone
            r["email"] = email
            r["active"] = True
            r["status"] = "active"
            if church_id:
                r["church_id"] = church_id
            results.append((uname, "updated", r.get("id", "")))
        else:
            new = db.insert_user({
                "username": uname,
                "password": pw,
                "name": name,
                "role": role,
                "phone": phone,
                "email": email,
                "church_id": church_id,
                "active": True,
                "status": "active",
            })
            if new:
                by_user[key] = new
                results.append((uname, "created", new["id"]))
            else:
                results.append((uname, "FAILED", ""))
                continue

    # Link zoneru to a zone + stamp the zone's reader_id.
    zr = by_user.get("zoneru")
    if zr and zr.get("church_id"):
        church = db.find_church(zr["church_id"]) or {}
        zid = _ensure_zone_for_reader(zr["church_id"], church.get("name", ""))
        if zid:
            zr["zone_id"] = zid
            zrows = db._read_tab(db.ZONES_TAB)
            for z in zrows:
                if z.get("id") == zid:
                    z["reader_id"] = zr["id"]
                    z["reader_name"] = zr.get("name", "")
                    break
            db._write_tab(db.ZONES_TAB, zrows)

    # Link leader_abana to the ABANA ministry (ministries are parish-wide
    # in this app, so we just take the one named ABANA).
    lr = by_user.get("leader_abana")
    if lr:
        ministries = db.list_ministries()
        abana = next((m for m in ministries
                      if "ABANA" in (m.get("name", "") or "").upper()), None)
        if abana:
            lr["ministry_id"] = abana["id"]
            mrows = db._read_tab(db.MINISTRIES_TAB)
            for m in mrows:
                if m.get("id") == abana["id"]:
                    m["leader_id"] = lr["id"]
                    m["leader_name"] = lr.get("name", "")
            db._write_tab(db.MINISTRIES_TAB, mrows)

    db._write_tab(db.USERS_TAB, list(by_user.values()))

    print()
    print(f"{'Username':16s} {'Action':10s} {'Role':18s} {'Church':12s} {'Zone':12s}")
    print("-" * 72)
    for uname, action, _ in results:
        r = by_user.get(uname.lower(), {})
        print(f"{uname:16s} {action:10s} {r.get('role',''):18s} "
              f"{(r.get('church_id','') or '')[:12]:12s} "
              f"{(r.get('zone_id','') or '')[:12]:12s}")
    print()
    print("Konti zose 6 zonguwe/zaremwe. Nta kindi cyanditswe")
    print("(amaturo, abakristo, budget... byose ntibyahinduka).")
    print()
    print("Injira noneho na:")
    print("  parish / parish123       — Umushumba wa Paruwasi")
    print("  manager / manager123     — Muyobozi wa Paruwasi")
    print("  ruhango / church123      — Umushumba w'itorero rya RUHANGO")
    print("  ruhango_fin / finance123 — Ushinzwe imali w'itorero rya RUHANGO")
    print("  leader_abana / leader123 — Umuyobozi wa ministeur y'Abana")
    print("  zoneru / zone123         — Umuyobozi wa zone mu itorero rya RUHANGO")
    print()
    print("Kugenzura login (verify_password):")
    all_ok = True
    for uname, pw, *_ in DEMO_ACCOUNTS:
        u = db.find_user_by_credentials(uname, pw)
        status = "OK" if u else "FAILED"
        if not u:
            all_ok = False
        print(f"  {uname:14s} -> {status}")
    print()
    print("=" * 64)
    print("BYARANGIJE — konti zose zikora." if all_ok
          else "Hari ikibazo — reba 'FAILED' haruguru.")
    print("=" * 64)


if __name__ == "__main__":
    main()
