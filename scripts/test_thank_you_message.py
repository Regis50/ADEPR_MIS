"""
test_thank_you_message.py — verify the message2.py-style rich builder.

Checks the builder produces the EXACT message2.py template (greeting + name +
church + IMIBARE breakdown + URUHARE ranking + share + blessing), that the
numbers come from db.rankings() (not made up), and that it gracefully falls
back when there is no offering for the given week.

Run: python3 scripts/test_thank_you_message.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # mis/

import db
import thank_you_message as tym

# ---- Mini test framework (same shape as the other suites) ----
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


print("=" * 60)
print("THANK-YOU MESSAGE BUILDER TEST (message2.py-style)")
print("=" * 60)

# ---- 1. Pick a real church + week with offerings ----
offs = db.list_offerings() or []
assert offs, "seed data missing — run seed.py first"
# Find a week_date that has multiple churches (so ranking > 1).
from collections import Counter
wd_counts = Counter(o.get("week_date", "") for o in offs if o.get("week_date"))
wd_best = max(wd_counts, key=wd_counts.get)
print(f"\n[setup] richest week: {wd_best} ({wd_counts[wd_best]} churches)")

# Rank that week and grab the #1 church — that gives us a clear UMUNYAMWANYA
# WA MBERE label and a non-trivial share %.
rows = db.rankings(start_date=wd_best, end_date=wd_best) or []
assert rows, "rankings empty for the richest week"
target = rows[0]
church_id = target["church_id"]
print(f"[setup] target church: {target.get('name')} (id={church_id})")
print(f"        leader: {target.get('leader_name')} | rank={target.get('rank')} | igiteranyo={target.get('igiteranyo')}")
print(f"        momo={target.get('icyacumi_momo')} bank={target.get('icyacumi_bank')} church_7={target.get('church_7')} parish_2={target.get('parish_2')}")
total_amaturo = sum(r.get("igiteranyo", 0) for r in rows)
print(f"        total amaturo in parish: {total_amaturo} across {len(rows)} churches")

# ---- 2. Build the message ----
print(f"\n[2] build() for {target.get('name')} on {wd_best}:")
built = tym.build(church_id, wd_best, parish_name="RUHANGO")
print(f"    available={built['available']}")
print(f"    meta: izina={built['meta'].get('izina')!r} itorero={built['meta'].get('itorero')!r} "
      f"rank={built['meta'].get('rank')} share={built['meta'].get('share')}% n_total={built['meta'].get('n_total')}")
print(f"    --- message ---")
for line in built["message"].split("\n"):
    print(f"    | {line}")
print(f"    --- end message ---")

check("build returns available=True for a real week", built["available"] is True)
check("meta.izina matches db rank row",
      built["meta"].get("izina") == (target.get("leader_name") or ""))
check("meta.itorero matches db rank row",
      built["meta"].get("itorero") == (target.get("name") or ""))
check("meta.amaturo matches igiteranyo",
      built["meta"].get("amaturo") == int(float(target.get("igiteranyo", 0))),
      f"built={built['meta'].get('amaturo')} db={int(float(target.get('igiteranyo', 0)))}")
check("meta.momo matches icyacumi_momo",
      built["meta"].get("momo") == int(float(target.get("icyacumi_momo", 0))))
check("meta.bank matches icyacumi_bank",
      built["meta"].get("bank") == int(float(target.get("icyacumi_bank", 0))))
check("meta.retenu matches church_7",
      built["meta"].get("retenu") == int(float(target.get("church_7", 0))))
check("meta.kuri_par matches parish_2",
      built["meta"].get("kuri_par") == int(float(target.get("parish_2", 0))))
check("meta.rank matches db rank",
      built["meta"].get("rank") == int(target.get("rank", 0)))
check("meta.n_total matches number of ranked churches",
      built["meta"].get("n_total") == len(rows))
# Share %: amaturo / total_amaturo * 100, 1 decimal.
expected_share = round(int(float(target.get("igiteranyo", 0))) / total_amaturo * 100, 1) if total_amaturo else 0.0
check("meta.share is the correct percentage",
      built["meta"].get("share") == expected_share,
      f"built={built['meta'].get('share')} expected={expected_share}")

# ---- 3. Verify the message contains every message2.py section ----
m = built["message"]
check("message starts with 'Muraho {izina}'",
      m.startswith(f"Muraho {built['meta'].get('izina')}"),
      f"first 30 chars: {m[:30]!r}")
check("message greets by leader name",
      built["meta"].get("izina", "") in m)
check("message names the church (itorero)",
      built["meta"].get("itorero", "") in m)
check("message mentions parish name",
      "RUHANGO" in m or built["meta"].get("parish_name", "") in m)
check("message has IMIBARE Y'AMATURO section",
      "IMIBARE Y'AMATURO" in m)
check("message lists Amaturo yose line",
      "Amaturo yose" in m)
check("message lists Kuri MoMo line",
      "Kuri MoMo" in m)
check("message lists Kuri Banki line",
      "Kuri Banki" in m)
check("message lists 7% Asigara kwitorero line",
      "7% Asigara kwitorero" in m)
check("message lists Kuri Paruwasi line",
      "Kuri Paruwasi" in m)
check("message has URUHARE MU KARERE section",
      "URUHARE MU KARERE" in m)
check("message lists Ijanisha line",
      "Ijanisha" in m)
check("message lists Amatorero yose line",
      "Amatorero yose" in m)
check("message ends with blessing",
      m.rstrip().endswith("Murakoze cyane."),
      f"last 30 chars: {m[-30:]!r}")

# ---- 4. Ranking label logic (matches message2.py) ----
rank = built["meta"].get("rank", 0)
expected_label = (
    "UMUNYAMWANYA WA MBERE" if rank == 1 else
    "UMUNYAMWANYA WA KABIRI" if rank == 2 else
    "UMUNYAMWANYA WA GATATU" if rank == 3 else
    f"Urwego #{rank}"
)
check(f"ranking label correct for rank={rank}",
      built["meta"].get("ako_akamaro") == expected_label,
      f"built={built['meta'].get('ako_akamaro')!r} expected={expected_label!r}")
check("ranking label appears in message",
      expected_label in m)

# ---- 5. Numbers in message are formatted with thousands separators ----
amaturo = built["meta"].get("amaturo", 0)
if amaturo >= 1000:
    expected_str = f"{amaturo:,} RWF"
    check("amaturo value formatted with comma separator",
          expected_str in m,
          f"looking for {expected_str!r}")

# ---- 6. Fallback: week with no offerings ----
print(f"\n[6] build() for a week with NO offerings (fallback):")
fake_wd = "2099-12-31"  # far future — no offerings
built2 = tym.build(church_id, fake_wd, parish_name="RUHANGO")
print(f"    available={built2['available']}")
print(f"    message: {built2['message']!r}")
check("fallback returns available=False", built2["available"] is False)
check("fallback message is the flat one-liner",
      "Murakoze" in built2["message"] and "Imana ibahe umugisha" in built2["message"])
check("fallback message includes parish name",
      "RUHANGO" in built2["message"])
check("fallback message includes week_date",
      fake_wd in built2["message"])

# ---- 7. Fallback: bogus church_id ----
print(f"\n[7] build() for a bogus church_id (fallback):")
built3 = tym.build("NONEXISTENT_CHURCH", wd_best, parish_name="RUHANGO")
print(f"    available={built3['available']}")
print(f"    message: {built3['message']!r}")
check("bogus church returns available=False", built3["available"] is False)
check("bogus church fallback is the flat one-liner",
      "Murakoze" in built3["message"])

# ---- 8. build_flat() helper ----
flat = tym.build_flat("TEST CHURCH", "2026-01-01", 1234567, parish_name="RUHANGO")
print(f"\n[8] build_flat(): {flat!r}")
check("build_flat has church name", "TEST CHURCH" in flat)
check("build_flat has week_date", "2026-01-01" in flat)
check("build_flat has total with commas", "1,234,567" in flat)
check("build_flat has parish name", "RUHANGO" in flat)
check("build_flat has blessing", "Imana ibahe umugisha" in flat)

# ---- Summary ----
print("\n" + "=" * 60)
print(f"SUMMARY: {passed}/{passed + failed} passed")
if failed == 0:
    print("ALL THANK-YOU MESSAGE BUILDER CHECKS PASSED")
    print("(builder reproduces message2.py — proven against real MIS data)")
else:
    print(f"{failed} FAILED")
print("=" * 60)
sys.exit(0 if failed == 0 else 1)
