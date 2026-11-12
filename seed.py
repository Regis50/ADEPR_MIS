"""
seed.py — Seed real ADEPR Paruwasi ya Ruhango data.

SCOPE: RUHANGO Parish only — 37 amatorero nyayo extracted from the
"WEEKLY REPORT - 2.xlsx" (Copy of Ruhango Parish sheet).

Run once before starting app.py:
    python3 seed.py

Creates:
  - 1 Parish Pastor account (parish / parish123)
  - 37 Ruhango churches (the parish seat + 36 others)
  - 37 Church Pastor accounts (umushumba w'itorero)
  - 37 Church Finance accounts (ushinzwe imali) — can enter amaturo
  - Default ministries (Abana, Urubyiruko, Abagabo, ...) + leaders
  - Sample members per church
  - 8 weeks of sample weekly offerings per church, including the
    7% / 2% / 2% / 89% distribution that mirrors the Excel sheet.
  - Default UI translations + sample announcements
"""

import db
import auth
import datetime
import random


# ---------------------------------------------------------------
# Default UI translations (Kinyarwanda)
# ---------------------------------------------------------------
DEFAULT_TRANSLATIONS = {
    "_comment": "UI strings — Kinyarwanda. Edit from Settings.",
    "app_title": "ADEPR MIS — Paruwasi ya Ruhango",
    "login_welcome": "Murakaza neza kuri sisitemu yo gucunga amakuru ya Paruwasi",
    "login_username": "Izina ryo kwinjira",
    "login_password": "Ijambobanga",
    "login_button": "Injira",
    "nav_dashboard": "Dashboard",
    "nav_churches": "Amatorero",
    "nav_pastors": "Abashumba",
    "nav_members": "Abakristo",
    "nav_ministries": "Ministeur",
    "nav_offerings": "Amaturo",
    "nav_rankings": "Uruhare",
    "nav_reports": "Raporo",
    "nav_sms": "Tangaza",
    "nav_settings": "Igenamiterere",
    "nav_my_church": "Itorero ryanjye",
    "nav_my_members": "Abakristo banjye",
    "nav_record_offering": "Andika amaturo",
    "nav_my_reports": "Raporo zanjye",
    "nav_my_ministry": "Ministeur yanjye",
    "nav_signature": "Umukono",
    "logout": "Soqa",
    "kpi_total_churches": "Amatorero yose",
    "kpi_total_members": "Abakristo bose",
    "kpi_total_ministries": "Ministeur",
    "kpi_total_offerings": "Amaturo yose",
    "kpi_this_week": "Ayi cyumweru",
    "kpi_active_pastors": "Abashumba b'itorero",
    "kpi_active_finance": "Abayobozi b'imali",
    "kpi_active_leaders": "Abayobozi ba ministeur",
    "btn_add": "Ongeraho",
    "btn_edit": "Hindura",
    "btn_delete": "Siba",
    "btn_save": "Bika",
    "btn_cancel": "Hagarika",
    "btn_sync": "Kura amakuru",
    "btn_export": "Kura Excel",
    "btn_send": "Ohereza",
    "msg_no_data": "Nta makuru ahari. Ongeraho.",
    "msg_confirm_delete": "Urabyizeye ko ushaka gusiba?",
    "msg_login_failed": "Izina cyangwa ijambobanga sibyo.",
    "msg_no_permission": "Nta burenganzira ufite.",
    "msg_saved": "Byabitswe neza.",
    "msg_sms_dry_run": "Dry run — nta SMS nyayo yoherejwe.",
    "msg_sms_sent": "SMS yoherejwe neza.",
}


# ---------------------------------------------------------------
# The 37 real amatorero of ADEPR Paruwasi ya Ruhango.
# Extracted from "Copy of Ruhango Parish" sheet (WEEKLY REPORT - 2.xlsx).
# RUHANGO itself is the parish seat (top church).
# ---------------------------------------------------------------
RUHANGO_CHURCHES = [
    "RUHANGO",           # parish seat (from "Ruhango Parish" sheet row 10)
    "MUNINI",
    "KABUTARE",
    "GITISI",
    "BUHORO",
    "BUNYOGOMBE",
    "KAREBA",
    "GIKOMA",
    "MUSAMO",
    "NYARURAMA",
    "NYABUGINGO",
    "TAMBWE",
    "KINAZI",
    "KIBANDA",
    "GISALI",
    "NYABUSUNZU",
    "NYAKABUNGO",
    "RUBONA-KN",
    "RUTABO CENTRE",
    "BUHANDA",
    "BYIMANA",
    "GISANGA",
    "GISEKE",
    "GITINDA",
    "GITWE",
    "KIRWA",
    "KIZIBERE",
    "MAYUNZWE",
    "MBUYE-MBUYE",
    "MPANDA",
    "MUNANIRA",
    "MUREMURE",
    "MUTARA",
    "MWENDO",
    "NTENYO",
    "NYAKABUYE",
    "RUGOGWE",
    "VUNGA",
]

# Sample leaders + phones for the parish seat (top church, real data from xlsx).
RUHANGO_TOP_LEADER = ("KIM SEZIBERA", "0786717390")

# Default ministries (per ADEPR structure: abana, urubyiruko, abagabo, ...)
DEFAULT_MINISTRIES = [
    ("ABANA",        "Ministeur y'abana bato",                  "Urwabo rw'Abana"),
    ("URUBYIRUKO",   "Ministeur y'urubyiruko",                  "Urubyiruko rw'ITORERO"),
    ("ABAGABO",      "Ministeur y'abagabo",                      "Abagabo b'ITORERO"),
    ("ABAGORE",      "Ministeur y'abagore",                      "Abagore b'ITORERO"),
    ("UMUSIKERI",    "Ministeur y'umusikeri (choir)",            "Abayobozi b'umusiki"),
    ("UTUMISHWA",    "Ministeur y'utumishwa (evangelism)",       "Gutanga ubutumwa"),
    ("UBUJURA",      "Ministeur y'ubujura (ushinzwe imali)",     "Ubufasha mu imali"),
    ("ISOMERO",      "Ministeur y'isomero (Sunday School)",      "Gutanga amasomo"),
]

# Sample first names + surnames for member generation (Rwandan names).
FIRST_NAMES = ["Pierre", "Marie", "Jean", "Grace", "Eric", "Aline", "David",
               "Claudine", "Emmanuel", "Rose", "Innocent", "Beatrice", "Patrick",
               "Solange", "Theogene", "Vestine", "Augustin", "Immaculee", "Felix",
               "Annonciata", "Gaspard", "Jeannette", "Damien", "Dancille"]
SURNAMES = ["Habimana", "Nshimiyimana", "Mukamana", "Twizeyimana", "Uwase",
            "Mugisha", "Iradukunda", "Bizimana", "Niyonzima", "Uwimana",
            "Mukamazimpaka", "Habarurema", "Ndayishimiye", "Rwema", "Gahondere",
            "Mugabowabo", "Nsengimana", "Karangwa", "Nyiraneza", "Mbarushimana"]


def _slug(name):
    """Make a username slug from a church name."""
    s = name.lower().replace(" ", "_").replace("'", "").replace("-", "_")
    return s[:24]


def _seed_users_parish():
    """Create the PARISH_PASTOR account (idempotent)."""
    existing = db.find_user_by_username("parish")
    if existing:
        db.update_user(existing["id"], {
            "password": "parish123", "role": "PARISH_PASTOR", "active": True,
        })
        return existing
    return db.insert_user({
        "username": "parish",
        "password": "parish123",
        "name": "Pasteur Muyobozi wa Paruwasi",
        "role": "PARISH_PASTOR",
        "phone": "0786717390",
        "email": "paruwasi@adepr.rw",
        "active": True,
    })


def _seed_churches_and_accounts():
    """Create all 37 Ruhango churches + matching shepherd & finance accounts."""
    created = []
    for idx, name in enumerate(RUHANGO_CHURCHES, start=1):
        existing = next((c for c in db.list_churches()
                         if c.get("name", "").upper() == name), None)
        if existing:
            created.append(existing)
            # still ensure it is scoped to RUHANGO
            if existing.get("parish", "").upper() != "RUHANGO":
                db.update_church(existing["id"], {"parish": "RUHANGO"})
            continue
        leader, phone = RUHANGO_TOP_LEADER if name == "RUHANGO" else (
            f"Muyobozi wa {name.title()}", f"0788{200000 + idx:06d}")
        c = db.insert_church({
            "name": name, "parish": "RUHANGO",
            "leader_name": leader, "leader_phone": phone,
            "leader_email": "", "location": "Ruhango, Southern Province, Rwanda",
        })
        created.append(c)

    # ---- Create/update a shepherd (CHURCH_PASTOR) + finance (CHURCH_FINANCE)
    # account for each church, so offerings can be entered by either.
    for c in created:
        # Shepherd (umushumba w'itorero)
        uname = _slug(c["name"])
        u = db.find_user_by_username(uname)
        if u:
            db.update_user(u["id"], {
                "church_id": c["id"], "role": "CHURCH_PASTOR", "active": True,
            })
        else:
            db.insert_user({
                "username": uname,
                "password": "church123",
                "name": c.get("leader_name") or f"Umushumba {c['name']}",
                "role": "CHURCH_PASTOR",
                "phone": c.get("leader_phone", ""),
                "email": "",
                "church_id": c["id"],
                "active": True,
            })
        # Finance leader (ushinzwe imali w'itorero)
        funame = _slug(c["name"]) + "_fin"
        fu = db.find_user_by_username(funame)
        if fu:
            db.update_user(fu["id"], {
                "church_id": c["id"], "role": "CHURCH_FINANCE", "active": True,
            })
        else:
            db.insert_user({
                "username": funame,
                "password": "finance123",
                "name": f"Ushinzwe imali — {c['name'].title()}",
                "role": "CHURCH_FINANCE",
                "phone": c.get("leader_phone", ""),
                "email": "",
                "church_id": c["id"],
                "active": True,
            })
    return created


def _seed_ministries(churches=None):
    created = []
    for name, desc, _ in DEFAULT_MINISTRIES:
        existing = next((m for m in db.list_ministries()
                         if m.get("name", "").upper() == name), None)
        if existing:
            created.append(existing)
            continue
        m = db.insert_ministry({
            "name": name,
            "description": desc,
            "leader_name": f"Muyobozi {name.title()}",
            "leader_phone": "",
            "active": True,
        })
        created.append(m)
    # Create ministry leader accounts for the first 3 ministries.
    # Each leader is attached to a church (church_id) so they can add
    # members of that church to their ministry from their own panel.
    first_churches = churches[:3] if len(churches) >= 3 else [churches[0]] * 3
    sample_leaders = [
        ("leader_abana", "leader123", "Muyobozi w'Abana",
         created[0]["id"] if len(created) > 0 else "",
         first_churches[0]["id"] if first_churches else ""),
        ("leader_rubyiruko", "leader123", "Muyobozi w'Urubyiruko",
         created[1]["id"] if len(created) > 1 else "",
         first_churches[1]["id"] if len(first_churches) > 1 else ""),
        ("leader_abagabo", "leader123", "Muyobozi w'Abagabo",
         created[2]["id"] if len(created) > 2 else "",
         first_churches[2]["id"] if len(first_churches) > 2 else ""),
    ]
    for uname, pw, name, mid, cid in sample_leaders:
        if db.find_user_by_username(uname):
            db.update_user(db.find_user_by_username(uname)["id"], {
                "ministry_id": mid, "role": "MINISTRY_LEADER", "active": True,
                "church_id": cid,
            })
            continue
        db.insert_user({
            "username": uname, "password": pw, "name": name,
            "role": "MINISTRY_LEADER", "phone": "0788002000",
            "ministry_id": mid, "church_id": cid, "active": True,
        })
    return created


def _seed_members(churches, count_per_church=6):
    """Create sample members per church across categories."""
    random.seed(42)
    categories = db.MEMBER_CATEGORIES
    members_made = 0
    for c in churches:
        existing = db.list_members(church_id=c["id"])
        if len(existing) >= count_per_church:
            continue
        for _ in range(count_per_church - len(existing)):
            fn = random.choice(FIRST_NAMES)
            sn = random.choice(SURNAMES)
            db.insert_member({
                "church_id": c["id"],
                "name": f"{fn} {sn}",
                "gender": random.choice(["M", "F"]),
                "phone": f"0788{random.randint(100000, 999999)}",
                "category": random.choice(categories),
                "dob": f"{random.randint(1960, 2005)}-{random.randint(1,12):02d}-01",
                "baptism_date": f"{random.randint(2010, 2024)}-{random.randint(1,12):02d}-01",
                "active": True,
            })
            members_made += 1
    return members_made


def _seed_offerings(churches):
    """Create sample weekly offerings for the last 8 weeks for each church.

    Mirrors the ADEPR Ruhango Parish sheet: ICYACUMI (Ibiturisho, Momo,
    Banki, Agasanduka), Amaturo, Amashimwe, Buracyeye, Imisaruro, Igiteranyo,
    then 7% / 2% / 2% / 89% distribution + Abana amount + Budget (plan).
    """
    random.seed(7)
    today = datetime.date.today()
    start_of_week = today - datetime.timedelta(days=today.weekday())
    count = 0
    for c in churches:
        # vary the church size so the ranking is realistic
        base = random.choice([0.5, 0.8, 1.0, 1.2, 2.0])
        # planned weekly budget for this church (kept stable across weeks)
        budget = round(random.randint(300000, 1500000) * base, 2)
        for w in range(8):
            week_date = (start_of_week - datetime.timedelta(weeks=w)).isoformat()
            existing = [o for o in db.list_offerings(church_id=c["id"])
                        if o.get("week_date") == week_date]
            if existing:
                continue
            ic1 = round((random.randint(20000, 220000) * base), 2) if w < 5 else 0
            ic2 = round((random.randint(5000, 80000) * base), 2)
            ic3 = round((random.randint(0, 60000) * base), 2)
            ic4 = round((random.randint(0, 40000) * base), 2)
            amaturo = round((random.randint(20000, 900000) * base), 2)
            amashimwe = round((random.randint(2000, 60000) * base), 2)
            buracyeye = round((random.randint(500, 15000) * base), 2)
            misaruro = round((random.randint(1000, 30000) * base), 2)
            abana_amount = round(random.randint(1000, 20000) * base, 2)
            db.insert_offering({
                "church_id": c["id"],
                "week_date": week_date,
                "recorded_by": "",
                "recorder_name": c.get("leader_name", ""),
                "recorder_role": "CHURCH_FINANCE",
                "abihannye": random.randint(0, 12),
                "abana": random.randint(10, 80),
                "abagarutse": random.randint(0, 8),
                "abana_amount": abana_amount,
                "budget": budget,
                "items": [
                    {"category": "ICYACUMI_IBITURISHO", "amount": ic1},
                    {"category": "ICYACUMI_MOMO", "amount": ic2},
                    {"category": "ICYACUMI_BANK", "amount": ic3},
                    {"category": "ICYACUMI_AGASANDUKA", "amount": ic4},
                    {"category": "AMATURO", "amount": amaturo},
                    {"category": "AMASHIMWE", "amount": amashimwe},
                    {"category": "BURACYEYE", "amount": buracyeye},
                    {"category": "IMISARURO", "amount": misaruro},
                ],
                "notes": "",
            })
            count += 1
    return count


def _seed_announcements():
    db.insert_announcement({
        "title": "Iteraniro ry'abashumba",
        "message": ("Muraho abashumba b'amatorero. Hari inama ku wa gatatu "
                    "saa 10:00 kuri Paruwasi. Mweze."),
        "target_role": "CHURCH_PASTOR",
        "sent_by": "",
        "sender_name": "Umushumba wa Paruwasi",
        "dry_run": True,
        "recipients_count": 0,
        "sent_count": 0,
        "failed_count": 0,
        "status": "DRAFT",
    })


def _seed_budgets(churches):
    """Set a weekly budget per church for the current week (and the previous
    7 weeks), so achievement % is meaningful out of the box."""
    import datetime as _dt
    import random as _r
    _r.seed(13)
    today = _dt.date.today()
    monday = today - _dt.timedelta(days=today.weekday())
    pp = db.find_user_by_username("parish") or {"id": ""}
    n = 0
    for w in range(8):
        week = (monday - _dt.timedelta(weeks=w)).isoformat()
        items = []
        for c in churches:
            # budget varies with church size; same week-to-week for stability
            base = _r.choice([0.5, 0.8, 1.0, 1.2, 2.0])
            amt = round(_r.randint(300000, 1500000) * base, 2)
            items.append({"church_id": c["id"], "amount": amt})
        db.set_budgets_for_week(week, items, set_by=pp["id"])
        n += len(items)
    return n


def _seed_sample_notifications():
    """Seed a couple of sample notifications so the inbox is not empty."""
    db.send_notification({
        "sender_id": "", "sender_name": "ADEPR Paruwasi ya Ruhango",
        "sender_role": "PARISH_PASTOR",
        "recipient_role": "ALL_CHURCH",
        "title": "Murakaza neza kuri sisitemu",
        "body": ("Sisitemu yacu yo gucunga amakuru yatangiye. "
                 "Andikamo amaturo y'icyumweru buri cyumweru."),
        "category": "announcement",
    })
    db.send_notification({
        "sender_id": "", "sender_name": "Ministeur y'Abana",
        "sender_role": "MINISTRY_LEADER",
        "recipient_role": "PARISH_PASTOR",
        "title": "Gahunda y'abana",
        "body": ("Ministeur y'Abana ifite gahunda yo gukarima abana "
                 "ku cyumweru kizaza. Turakeneye iyemezwa."),
        "category": "request",
    })


def _seed_service_requests(churches):
    """Seed a few service/certificate requests so the approval flow has data."""
    import random as _r
    _r.seed(44)
    # find the ministry leader of the Abana (has a church_id)
    leader = db.find_user_by_username("leader_abana")
    if not leader:
        return 0
    cid = leader.get("church_id", "")
    church = db.find_church(cid)
    samples = [
        ("Jean Pierre Habimana", "0788111222", "M",
         "Avuye mu rundi torero, dufite icyemezo cy'ubatizo.", "cert_jp.pdf"),
        ("Marie Claire Uwase", "0788333444", "F",
         "Umukobwa nshya mu karere, asaba kwakirwa.", "cert_mc.pdf"),
        ("Eric Niyonzima", "0788555666", "M",
         "Yabaye impamvu yo kwakirwa nyuma yo kwigishwa.", "cert_en.pdf"),
    ]
    n = 0
    for name, phone, gender, msg, cert in samples:
        db.submit_service_request({
            "requester_id": leader["id"],
            "requester_name": leader.get("name", ""),
            "requester_role": "MINISTRY_LEADER",
            "church_id": cid,
            "church_name": church.get("name", "") if church else "",
            "christian_name": name,
            "christian_phone": phone,
            "christian_gender": gender,
            "request_type": "NEW_MEMBER",
            "message": msg,
            "certificate_filename": cert,
        })
        n += 1
    return n


def _seed_death_reports(churches):
    """Seed one or two death reports so the deceased-member flow is visible."""
    members = db.list_members()
    if len(members) < 5:
        return 0
    pp = db.find_user_by_username("parish") or {"id": ""}
    chosen = members[2:4]
    n = 0
    for m in chosen:
        church = db.find_church(m.get("church_id", ""))
        db.report_death({
            "member_id": m["id"],
            "church_id": m.get("church_id", ""),
            "church_name": church.get("name", "") if church else "",
            "reported_by": pp["id"],
            "reported_by_name": pp.get("name", ""),
            "death_date": "2026-10-25",
            "notes": "Yitabye Imana akurikije indwara.",
        })
        n += 1
    return n


def _seed_schedules(churches):
    """Seed a couple of scheduled events with feedback."""
    import datetime as _dt
    today = _dt.date.today()
    samples = [
        ("Inama y'abashumba", "Inama y'ukwezi y'abashumba b'amatorero.",
         (today + _dt.timedelta(days=3)).isoformat() + "T10:00",
         "Kuri Paruwasi"),
        ("Igikoresho cy'abana", "Gukarima abana b'amatorero.",
         (today + _dt.timedelta(days=7)).isoformat() + "T14:00",
         "Ku matorero"),
        ("Inama y'Urubyiruko", "Inama y'urubyiruko rwa Paruwasi.",
         (today - _dt.timedelta(days=2)).isoformat() + "T16:00",
         "Paruwasi"),
    ]
    leader = db.find_user_by_username("leader_abana") or {"id": "", "name": "",
                                                          "role": "MINISTRY_LEADER",
                                                          "church_id": churches[0]["id"]}
    pp = db.find_user_by_username("parish") or {"id": "", "name": "",
                                                "role": "PARISH_PASTOR"}
    n = 0
    for title, desc, dt, loc in samples:
        sc = db.create_schedule({
            "title": title,
            "description": desc,
            "scheduled_by": pp["id"],
            "scheduled_by_name": pp.get("name", ""),
            "scheduled_by_role": "PARISH_PASTOR",
            "church_id": leader.get("church_id", ""),
            "ministry_id": leader.get("ministry_id", ""),
            "datetime": dt,
            "location": loc,
        })
        if sc:
            n += 1
            # add feedback to the past one
            if "Urubyiruko" in title:
                db.add_schedule_feedback(sc["id"], leader, "Byagenze neza, abagabo benshi bahisemo.")
                db.update_schedule_status(sc["id"], "done")
    return n


def _seed_pending_users(churches):
    """Seed one or two pending (unapproved) account requests so the
    church-pastor approval flow has data to show."""
    ch = churches[0] if churches else None
    if not ch:
        return 0
    rec1, _ = db.register_user({
        "username": "newfinance",
        "password": "test1234",
        "name": "Mukasa Jean Finance",
        "role": "CHURCH_FINANCE",
        "church_id": ch["id"],
        "phone": "0788999000",
        "email": "mukasa@example.com",
        "security_question": db.SECURITY_QUESTIONS[0],
        "security_answer": "Mbabazi",
    })
    ch2 = churches[1] if len(churches) > 1 else ch
    rec2, _ = db.register_user({
        "username": "newleader",
        "password": "test1234",
        "name": "Uwase Grace Leader",
        "role": "MINISTRY_LEADER",
        "church_id": ch2["id"],
        "phone": "0788999111",
        "security_question": db.SECURITY_QUESTIONS[1],
        "security_answer": "Mukamana",
    })
    return sum(1 for r in (rec1, rec2) if r)


def _seed_automation(churches):
    """Seed system settings (SMTP placeholder), a couple of queued
    messages, and an email-report log entry so the new panels have data."""
    db.save_system_settings({
        "smtp_host": "",            # left blank = offline-friendly (dry-run)
        "smtp_port": "587",
        "smtp_user": "",
        "smtp_password": "",
        "smtp_from": "",
        "smtp_use_tls": True,
        "auto_process_queue": True,
        "auto_weekly_email": True,
        "weekly_email_day": "mon",
        "weekly_email_hour": 8,
        "sms_gateway_url": "http://192.168.1.169:8082",
        "sms_dry_run": True,
    })
    n = 0
    ch = churches[0] if churches else None
    if ch:
        db.enqueue_message({
            "channel": "sms", "to": "0786717390",
            "body": "Test message yo kwemeza ko queue ikora — ADEPR MIS.",
            "church_id": ch["id"], "created_by": "U1", "created_by_name": "Seed",
        })
        n += 1
        db.enqueue_message({
            "channel": "email", "to": "paruwasi@adepr.rw",
            "subject": "Test — ADEPR MIS queue",
            "body": "Iyi email iri mu murongo — izoherejwe iyo SMTP ikonfigiwe.",
            "church_id": ch["id"], "created_by": "U1", "created_by_name": "Seed",
        })
        n += 1
    db.log_email_report({
        "church_id": ch["id"] if ch else "",
        "church_name": ch["name"] if ch else "TEST",
        "recipient": "paruwasi@adepr.rw",
        "subject": "Incamake y'icyumweru — Itorero rya RUHANGO",
        "period": "weekly", "status": "sent", "trigger": "manual",
    })
    return n


def _seed_zones_assets_activity(churches, members):
    """V1.7: seed zones per church, sample assets with value, a zone reader
    + parish manager user, and a handful of activity-log entries so the
    new monitoring feed has data from the first run."""
    import auth as auth_mod
    n_zones = n_assets = 0
    for c in churches[:8]:
        z = db.create_zone({
            "church_id": c["id"], "name": "Zone ya " + c["name"].split()[-1],
            "reader_name": "Umuyobozi wa zone",
            "description": "Zone yo gusanzwe mu itorero rya " + c["name"],
        })
        n_zones += 1
        # Tag a few members with this zone
        tagged = 0
        for m in members:
            if m.get("church_id") == c["id"] and not m.get("zone_id"):
                m["zone_id"] = z["id"]
                tagged += 1
                if tagged >= 3:
                    break
        db._write_tab(db.MEMBERS_TAB, members)
        # Sample assets
        sample = [
            ("Inzira ya ministeur", "AMATWARA", 4500000),
            ("Amacumi y'amajwi", "INZUBA_N_AMASHANYARAZI", 1200000),
            ("Imbeba zo gusamba", "IBINTU_BYO_GUSAMBA", 800000),
        ]
        for name, cat, val in sample:
            db.insert_asset({
                "church_id": c["id"], "name": name, "category": cat,
                "value": val, "quantity": 1, "acquired_date": "2024-06-15",
                "description": "Imitungo yanditswe n'umushumba w'itorero.",
                "status": "ACTIVE",
                "created_by": "seed", "created_by_name": "Seed",
            })
            n_assets += 1
        # Activity log entries
        db.log_activity({
            "actor_id": "seed", "actor_name": c.get("leader_name") or "Umushumba",
            "actor_role": "CHURCH_PASTOR", "church_id": c["id"],
            "action": "ASSET_ADDED", "target": sample[0][0],
            "detail": f"{sample[0][1]} • {sample[0][2]} RWF", "scope": "church",
        })
        db.log_activity({
            "actor_id": "seed", "actor_name": "Zone Reader",
            "actor_role": "ZONE_READER", "church_id": c["id"],
            "action": "MEMBER_ADDED", "target": "Abakristo bashya",
            "detail": "ABAKRISTO_BASHYA • 3 abakristo", "scope": "zone",
        })
    # Parish manager + zone reader users (created top-down by the parish)
    pm = db.insert_user({
        "username": "manager", "password": "manager123",
        "name": "Muyobozi wa Paruwasi", "role": "PARISH_MANAGER",
        "phone": "0788000999", "email": "manager@adepr.rw",
        "church_id": "", "active": True, "status": "active",
    })
    zr_church = churches[0] if churches else None
    zr = None
    if zr_church:
        zr, err = db.register_user({
            "username": "zoneru", "password": "zone123",
            "name": "Umuyobozi wa Zone Ruhango", "role": "ZONE_READER",
            "phone": "0788000888", "church_id": zr_church["id"],
            "security_question": "Izina rya sekuru?", "security_answer": "seed",
        })
        if zr:
            db.approve_user(zr["id"], {"id": "seed", "name": "Parish Pastor"})
            # V1.12.1: link the zone reader to the first zone of its church
            # so the Zone Reader menu (Abakristo b'iyi zone) has data, and
            # stamp the zone's reader_id. Previously zoneru had church_id
            # but no zone_id, so its dashboard looked empty.
            zr_zones = db.list_zones(church_id=zr_church["id"])
            if zr_zones:
                target_zone = zr_zones[0]
            else:
                target_zone = db.create_zone({
                    "church_id": zr_church["id"],
                    "name": "Zone ya " + zr_church["name"].split()[-1],
                    "reader_name": zr.get("name", ""),
                    "description": "Zone yo gusanzwe mu itorero rya "
                                   + zr_church["name"],
                })
            # Stamp both sides: reader.zone_id and zone.reader_id.
            urows = db._read_tab(db.USERS_TAB)
            for u in urows:
                if u.get("id") == zr["id"]:
                    u["zone_id"] = target_zone["id"]
                    break
            db._write_tab(db.USERS_TAB, urows)
            zrows = db._read_tab(db.ZONES_TAB)
            for z in zrows:
                if z.get("id") == target_zone["id"]:
                    z["reader_id"] = zr["id"]
                    z["reader_name"] = zr.get("name", "")
                    break
            db._write_tab(db.ZONES_TAB, zrows)
            zr["zone_id"] = target_zone["id"]
    return {"zones": n_zones, "assets": n_assets, "manager": bool(pm), "zone_reader": bool(zr)}


def _seed_v18_visitors_discipline_delegations(churches, members):
    """V1.8: sample visitors, a couple of discipline cases, a delegation,
    and extend some members with full profile fields."""
    import datetime as _dt
    today = _dt.date.today().isoformat()
    n_vis = n_disc = 0
    for c in churches[:6]:
        # 1-2 visitors per church
        db.insert_visitor({
            "church_id": c["id"], "name": "Umushyitsi " + c["name"].split()[-1],
            "phone": "078" + str(8000000 + n_vis), "gender": "M",
            "week_date": today, "goal_taught": "Gukunda Imana n'umutima wose",
            "address": c.get("location", "") or c["name"],
            "status": "VISITED",
            "entered_by": "seed", "entered_by_name": "Seed", "actor_role": "CHURCH_PASTOR",
        })
        db.insert_visitor({
            "church_id": c["id"], "name": "Umugeni " + c["name"].split()[-1],
            "phone": "078" + str(8001000 + n_vis), "gender": "F",
            "week_date": today, "goal_taught": "Kwemera Yesu nk'Umukiza",
            "address": c.get("location", "") or c["name"],
            "status": "FOLLOWUP",
            "entered_by": "seed", "entered_by_name": "Seed", "actor_role": "CHURCH_PASTOR",
        })
        n_vis += 2
    # Discipline: one confirmed + one pending
    if members:
        m = members[0]
        d = db.insert_discipline({
            "member_id": m.get("id", ""), "member_name": m.get("name", ""),
            "church_id": m.get("church_id", ""),
            "discipline_type": "WARNING", "reason": "Kudahwitamo amaturo",
            "action_taken": "Yavuzweho",
            "raised_by": "seed", "raised_by_name": "Church Pastor",
            "raised_by_role": "CHURCH_PASTOR",
        })
        if d:
            db.confirm_discipline(d["id"], {"id": "PP", "name": "Parish Pastor"}, "Byemejwe")
            n_disc += 1
        if len(members) > 5:
            m2 = members[5]
            db.insert_discipline({
                "member_id": m2.get("id", ""), "member_name": m2.get("name", ""),
                "church_id": m2.get("church_id", ""),
                "discipline_type": "SUSPENSION", "reason": "Ibyo yakorewe badahwituye",
                "action_taken": "Yahagaritswe ku minsi 30",
                "raised_by": "seed", "raised_by_name": "Church Pastor",
                "raised_by_role": "CHURCH_PASTOR",
            })
            n_disc += 1
    # Delegation: one active
    db.insert_delegation({
        "delegate_name": "Muyobozi wa Paruwasi (Manager)",
        "delegate_role": "PARISH_MANAGER", "church_id": "",
        "feature": "offering", "reason": "Umushumba wa paruwasi ari ku rugendo",
        "start_date": today, "end_date": (_dt.date.today() + _dt.timedelta(days=30)).isoformat(),
        "delegated_by": "PP", "delegated_by_name": "Parish Pastor",
    })
    # Extend a few members with full profile fields
    members = db.list_members()
    extended = 0
    for m in members[:15]:
        m["national_id"] = "1199" + str(1000000 + extended).zfill(7)
        m["marital_status"] = ["SINGLE", "MARRIED", "WIDOWED"][extended % 3]
        m["education_level"] = ["PRIMARY", "SECONDARY", "UNIVERSITY"][extended % 3]
        m["field_of_study"] = ["Theology", "Education", "Agriculture"][extended % 3]
        m["occupation"] = ["Mwarimu", "Umuhinzi", "Umucuruzi"][extended % 3]
        extended += 1
    db._write_tab(db.MEMBERS_TAB, members)
    return {"visitors": n_vis, "discipline": n_disc, "delegations": 1, "extended_members": extended}


def _seed_profile_and_translations():
    profile = db.load_parish_profile()
    profile["parish_name"] = "ADEPR PARUWASI YA RUHANGO"
    profile["region"] = "SOUTHERN REGION (URUREMBO RW'AMAJYEPOFO)"
    profile["pastor_name"] = "Pasteur Muyobozi wa Paruwasi"
    profile["pastor_phone"] = "0786717390"
    profile["pastor_email"] = "paruwasi@adepr.rw"
    profile["address"] = "Ruhango, Southern Province, Rwanda"
    profile["tin"] = "—"
    db.save_parish_profile(profile)
    current = db.load_translations()
    for k, v in DEFAULT_TRANSLATIONS.items():
        if k not in current:
            current[k] = v
    db.save_translations(current)


def _prune_non_ruhango():
    """Remove any churches not in the Ruhango scope (e.g. legacy Muhanga)."""
    valid = set(RUHANGO_CHURCHES)
    for c in db.list_churches():
        if c.get("name", "").upper() not in valid:
            db.delete_church(c["id"])


def main():
    print("=" * 60)
    print("🌱 ADEPR Paruwasi ya Ruhango MIS — Seeding (RUHANGO scope)")
    print("=" * 60)
    print("\n[1/16] Prune non-Ruhango churches...")
    _prune_non_ruhango()
    print("   ✔ Only RUHANGO churches kept")

    print("\n[2/16] Parish pastor account...")
    pp = _seed_users_parish()
    print(f"   ✔ {pp['username']} / parish123 (PARISH_PASTOR)")

    print("\n[3/16] 37 Ruhango churches + shepherd & finance accounts...")
    churches = _seed_churches_and_accounts()
    print(f"   ✔ {len(churches)} churches (RUHANGO seat + 36 others)")
    print("   ✔ 37 shepherd accounts (<church> / church123)")
    print("   ✔ 37 finance accounts (<church>_fin / finance123)")

    print("\n[4/16] Ministries...")
    mins = _seed_ministries(churches)
    print(f"   ✔ {len(mins)} ministries + 3 leader accounts (with church_id)")

    print("\n[5/16] Members (sample)...")
    n = _seed_members(churches)
    print(f"   ✔ {n} members created across Ruhango churches")

    print("\n[6/16] Offerings (last 8 weeks, with 7/2/2/89 distribution)...")
    o = _seed_offerings(churches)
    print(f"   ✔ {o} offering records created")

    print("\n[7/16] Weekly budgets (set by Parish Pastor, last 8 weeks)...")
    b = _seed_budgets(churches)
    print(f"   ✔ {b} budget records (parish-set, drives achievement %)")

    print("\n[8/16] Profile + translations + sample announcement...")
    _seed_profile_and_translations()
    _seed_announcements()
    print("   ✔ Done")

    print("\n[9/16] Sample notifications (inbox)...")
    _seed_sample_notifications()
    print("   ✔ Done")

    print("\n[10/16] Service requests (certificate + message)...")
    sr = _seed_service_requests(churches)
    print(f"   ✔ {sr} service requests seeded (ministry leader → church pastor)")

    print("\n[11/16] Death reports (members marked deceased)...")
    dr = _seed_death_reports(churches)
    print(f"   ✔ {dr} death reports seeded (notify parish, removed from roster)")

    print("\n[12/16] Schedules (events + feedback)...")
    sc = _seed_schedules(churches)
    print(f"   ✔ {sc} schedules seeded (with feedback on the past one)")

    print("\n[13/16] Pending account requests (demo approval flow)...")
    pu = _seed_pending_users(churches)
    print(f"   ✔ {pu} pending accounts seeded (church pastor approves)")

    print("\n[14/16] Automation (SMTP placeholder, queue, email log)...")
    au = _seed_automation(churches)
    print(f"   ✔ {au} queued messages + 1 email log entry seeded")

    print("\n[15/16] Zones, assets, activity log + zone_reader/manager users...")
    va = _seed_zones_assets_activity(churches, db.list_members())
    print(f"   ✔ {va['zones']} zones, {va['assets']} assets, "
          f"manager={'yes' if va['manager'] else 'no'}, "
          f"zone_reader={'yes' if va['zone_reader'] else 'no'}")

    print("\n[16/16] V1.8: visitors, discipline, delegation, extended profiles...")
    v18 = _seed_v18_visitors_discipline_delegations(churches, db.list_members())
    print(f"   ✔ {v18['visitors']} visitors, {v18['discipline']} discipline, "
          f"{v18['delegations']} delegation, {v18['extended_members']} extended profiles")

    db._prewarm_cache()
    print("\n" + "=" * 60)
    print("✅ Seed complete. You can now run: python3 app.py")
    print("=" * 60)
    print("\nLogin accounts:")
    print("  Parish Pastor : parish / parish123")
    print("  Church Pastor : <church_lowercase> / church123")
    print("                   e.g. ruhango / church123, kabutare / church123")
    print("  Church Finance: <church_lowercase>_fin / finance123")
    print("                   e.g. ruhango_fin / finance123")
    print("  Ministry Lead : leader_abana / leader123")
    print("=" * 60)


if __name__ == "__main__":
    main()
