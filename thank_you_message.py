"""
thank_you_message.py — builder y'ubutumwa bwo gushimira bwa paruwasi.

Ihuye n'amategeko ya message2.py (template yuzuye: izina + itorero + imibare
yose + ranking + ijanisha + umugisha), ariko ikomoka kuri data ya MIS
(db.rankings()) — nta pandas, nta sheets_reader. Ibi bituma ubutumwa bwo
gushimira bwuzuye mu nzira imwe: POST /api/thank-you-sms + auto thank-you
ku offering insert + preview ya panel, byose bikora builder imwe.

Amategeko ya message2.py yarokotse mu rwego rwa Kinyarwanda (nta cyo
byahinduye), gusa amazina y'aba columns yahinduwe agoresheje data ya MIS:

    message2.py          →  db.rankings() row
    -------------------------------------------------
    AMAZINA              →  leader_name
    ITORERO              →  name
    AMATURO YOSE         →  igiteranyo   (gross total)
    MOMO AMOUNT          →  icyacumi_momo
    BANK AMOUNT          →  icyacumi_bank
    ASIGARA (7%)         →  church_7     (RATE_CHURCH_7 = 0.07)
    AKOMEZA (kuri par.)  →  parish_2     (RATE_PARISH_2 = 0.02)
    RANKING              →  rank
    TELEPHONE            →  leader_phone
"""

# Parish default — ikoreshwa niba data ya paruwasi itabonetse.
_DEFAULT_PARISH_NAME = "ADEPR Paruwasi"


# Role-code → Kinyarwanda label (icyo ashinzwe). Used so the message shows
# a human-readable role next to the recorder's name instead of the raw
# internal code (CHURCH_FINANCE → "Inzego y'Imari y'Itorero", etc.).
_ROLE_LABELS = {
    "CHURCH_PASTOR":     "Umubyeyi w'Itorero",
    "CHURCH_FINANCE":    "Inzego y'Imari y'Itorero",
    "ZONE_READER":       "Musoma w'Akarere",
    "MINISTRY_LEADER":   "Umunyamabanga w'Umuryango",
    "PARISH_PASTOR":     "Umubyeyi wa Paruwasi",
    "PARISH_MANAGER":    "Munyamabanga wa Paruwasi",
    "PARISH_FINANCE":    "Inzego y'Imari ya Paruwasi",
    "ADMIN":             "Umuyobozi wa Sisiteme",
}


def _role_label(code):
    """Translate an internal role code to a Kinyarwanda label. Falls back
    to the raw code if unknown (so nothing is lost)."""
    if not code:
        return ""
    return _ROLE_LABELS.get(str(code).upper().strip(), str(code).strip())


def _recorder_info(church_id, week_date):
    """Look up who submitted the offering report for `church_id` /
    `week_date`, and what role they hold. Returns (name, role_label).

    An offering record carries recorder_name + recorder_role (set by
    insert_offering). We read the offerings tab directly via db.list_
    offerings() — filtered by church_id + week_date — and pick the most
    recent record (in case a church submitted twice and one was edited).

    Returns ("", "") if no offering exists for that church/week.
    """
    import db  # deferred — matches build()'s pattern (avoids circular import)
    try:
        offs = db.list_offerings(church_id=church_id,
                                 start_date=week_date, end_date=week_date)
    except Exception:
        return "", ""
    if not offs:
        return "", ""
    # Most recent first (list_offerings may not sort; be safe).
    offs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    o = offs[0]
    name = str(o.get("recorder_name", "") or "").strip()
    role = _role_label(o.get("recorder_role", ""))
    return name, role


def _week_over_week(church_id, week_date, current_total):
    """Compare this week's offering total vs the previous week's for the
    same church. Returns (prev_total, diff_amount, diff_pct, diff_label).

    `week_date` is a Monday ISO date; the previous week = week_date - 7d.
    diff_label is a Kinyarwanda phrase stating whether the church went
    forward (imbere) or backward (inyuma), with the amount and percent:
      - "byagiye imbere (+X RWF, +Y%)"  when current > previous
      - "byagiye inyuma (-X RWF, -Y%)"  when current < previous
      - "byabaye kimwe"                  when equal
      - ""                               when no previous-week data

    If there is no offering for the previous week, prev_total=0 and we
    return an empty label (the message omits the comparison section).
    """
    import db  # deferred — matches build()'s pattern
    from datetime import datetime, timedelta
    try:
        d = datetime.fromisoformat(str(week_date)[:10]).date()
    except (ValueError, TypeError):
        return 0, 0, 0.0, ""
    prev_date = (d - timedelta(days=7)).isoformat()
    try:
        prev_rows = db.rankings(start_date=prev_date, end_date=prev_date) or []
    except Exception:
        prev_rows = []
    prev_total = 0
    for r in prev_rows:
        if str(r.get("church_id", "")) == str(church_id):
            try:
                prev_total = int(float(str(r.get("igiteranyo", 0)).replace(",", "") or 0))
            except (ValueError, TypeError):
                prev_total = 0
            break
    if prev_total == 0:
        return 0, 0, 0.0, ""
    diff = current_total - prev_total
    pct = (diff / prev_total * 100.0) if prev_total else 0.0
    if diff > 0:
        label = (f"byagiye imbere (+{abs(diff):,} RWF, +{abs(pct):.1f}%)")
    elif diff < 0:
        label = (f"byagiye inyuma (-{abs(diff):,} RWF, -{abs(pct):.1f}%)")
    else:
        label = "byabaye kimwe"
    return prev_total, diff, pct, label


def build(church_id, week_date, parish_name=None):
    """Kora ubutumwa bwo gushimira bwa message2.py-style kuva kuri data ya MIS.

    Imiterere:
        church_id   — id y'itorero ryoherejwe (string)
        week_date   — tariki y'icyumweru (string "YYYY-MM-DD")
        parish_name — izina rya paruwasi (optional; bisabwa na message2.py)

    Isubiza:
        {
          "available": bool,        — True niba data ya rankings yabonetse
          "message":   str,         — ubutumwa bwa message2.py-style (cyangwa
                                       flat fallback niba available=False)
          "meta": {                 — imibare yose yo mu message (kuri UI)
            "izina", "itorero", "amaturo", "momo", "bank",
            "retenu", "kuri_par", "rank", "share", "n_total",
            "total_amaturo", "impuzandengo", "ako_akamaro", "uko_byagenze",
            "parish_name"
          }
        }

    Iyo data itabonetse (nta offering ku cyumweru cyo, cyangwa itorero
    ritabonetse), available=False + message = flat fallback — bituma
    endpoint ntigera yereke.
    """
    import db

    # ---- 1. Shakisha data y'icyumweru cyose (byose bitore) ----
    # db.rankings() ifata amatorero yose muri paruwasi ku cyumweru cyo.
    rows = []
    target = None
    try:
        rows = db.rankings(start_date=week_date, end_date=week_date) or []
    except Exception:
        rows = []
    for r in rows:
        if str(r.get("church_id", "")) == str(church_id):
            target = r
            break

    # ---- 2. Parish name ----
    parish = parish_name or ""
    if not parish:
        # Shake kuva kuri church record, cyangwa kuva kuri ranking row.
        try:
            ch = db.find_church(church_id) or {}
            parish = ch.get("parish", "") or ""
        except Exception:
            parish = ""
    if not parish and target:
        parish = target.get("parish", "") or ""
    if not parish:
        parish = _DEFAULT_PARISH_NAME

    # ---- 3. Fallback: nta data ——> message y'umurongo umwe ----
    if not target:
        # Nta offering ku cyumweru cyo, cyangwa itorero ntiribonetse muri
        # rankings. Tuguruka ku message y'umurongo umwe (nk'uko byari
        # bimeze mbere), ariko dukomeze izina rya paruwasi.
        try:
            ch = db.find_church(church_id) or {}
            church_name = ch.get("name", "") or ""
        except Exception:
            church_name = ""
        fallback = (
            f"Murakoze {church_name} kw'amaturo y'icyumweru cya {week_date}. "
            f"Imana ibahe umugisha. — {parish}"
        )
        return {
            "available": False,
            "message": fallback,
            "meta": {
                "parish_name": parish,
                "church_name": church_name,
                "week_date": week_date,
            },
        }

    # ---- 4. Imibare yose (nk'uko message2.py ubikoze) ----
    def _num(v):
        try:
            return int(float(str(v).replace(",", "").strip() or 0))
        except (ValueError, TypeError):
            return 0

    izina    = str(target.get("leader_name", "") or "").strip()
    itorero  = str(target.get("name", "") or "").strip()
    amaturo  = _num(target.get("igiteranyo", 0))
    momo     = _num(target.get("icyacumi_momo", 0))
    bank     = _num(target.get("icyacumi_bank", 0))
    retenu   = _num(target.get("church_7", 0))
    kuri_par = _num(target.get("parish_2", 0))
    rank     = _num(target.get("rank", 0))
    budget   = _num(target.get("budget_icyumweru", 0))
    budget_percent = float(target.get("percent", 0) or 0)

    # Total y'amatorero yose muri paruwasi ku cyumweru cyo (nk'uko
    # message2.py abibara mu nzira ya `for _, row in df.iterrows()`).
    total_amaturo = sum(_num(r.get("igiteranyo", 0)) for r in rows)
    n_total = len(rows)

    share = (amaturo / total_amaturo * 100) if total_amaturo else 0.0
    impuzandengo = (total_amaturo / n_total) if n_total else 0

    # ---- 4b. Uwitanye raporo (recorder) + icyo ashinzwe (role) ----
    recorder_name, recorder_role_label = _recorder_info(church_id, week_date)

    # ---- 4c. Ugereranyije n'icyumweru gishize (week-over-week) ----
    prev_total, diff_amount, diff_pct, diff_label = _week_over_week(
        church_id, week_date, amaturo)

    # ---- 5. Iganisha ry'umurongo (nk'uko message2.py abikoze) ----
    if amaturo >= impuzandengo:
        uko = "yagenze neza cyane, iri hejuru y'impuzandengo y'akarere"
    else:
        uko = "yageze kuri paruwasi kandi iri mu nzira nziza"

    # ---- 6. Ranking label (nk'uko message2.py abikoze) ----
    if rank == 1:
        akamaro = "UMUNYAMWANYA WA MBERE"
    elif rank == 2:
        akamaro = "UMUNYAMWANYA WA KABIRI"
    elif rank == 3:
        akamaro = "UMUNYAMWANYA WA GATATU"
    else:
        akamaro = f"Urwego #{rank}"

    # ---- 6b. Budget label (uko bageze kuri budget y'icyumweru) ----
    if budget > 0:
        if budget_percent >= 100:
            budget_uko = "byageze cyangwa byarenze budget"
        elif budget_percent >= 75:
            budget_uko = "byageze hafi ya budget"
        elif budget_percent >= 50:
            budget_uko = "byageze mu gice cya budget"
        else:
            budget_uko = "ntibikibye ku rugero rwa budget"
    else:
        budget_uko = "budget ntabwo yagenwe"

    # ---- 7. Template ya message2.py — YATORAGURWE NTA CYO BYAHINDUWE ----
    # V1.14: Byongereyemo: budget %, umwitanye raporo + icyo ashinzwe,
    # ugereranyije n'icyumweru gishize (imbere/inyuma).
    message = (
        f"Muraho {izina},\n\n"
        f"Tubashimira cyane ku murimo mwakoze mu itorero {itorero}.\n"
        f"Raporo yanyu yageze kuri {parish} kandi yafashwe neza.\n"
        + (f"Yayitanze: {recorder_name} ({recorder_role_label}).\n" if recorder_name else "")
        + f"\nIMIBARE Y'AMATURO:\n"
        f"   - Amaturo yose        : {amaturo:,} RWF\n"
        f"   - Kuri MoMo           : {momo:,} RWF\n"
        f"   - Kuri Banki          : {bank:,} RWF\n"
        f"   - 7% Asigara kwitorero: {retenu:,} RWF\n"
        f"   - Kuri Paruwasi       : {kuri_par:,} RWF\n"
        + (f"   - Budget y'icyumweru  : {budget:,} RWF\n"
           f"   - Uko byageze kuri %  : {budget_percent:.1f}% ({budget_uko})\n" if budget > 0 else "")
        + f"\nURUHARE MU KARERE:\n"
        f"   - {akamaro}\n"
        f"   - Ijanisha            : {share:.1f}% by'amaturo yose\n"
        f"   - Amatorero yose      : {n_total}\n"
        + (f"\nUGERERANYIJE N'ICYUMWERU GISHIZE:\n"
           f"   - Icyumweru gishize  : {prev_total:,} RWF\n"
           f"   - Uko byahindutse    : {diff_label}\n" if prev_total > 0 else "")
        + f"\nMuri rusange, raporo {uko}.\n\n"
        f"Mukomeze muri uru rugendo rwiza, kandi Imana ibahe umugisha.\n\n"
        f"Murakoze cyane."
    )

    return {
        "available": True,
        "message": message,
        "meta": {
            "izina": izina,
            "itorero": itorero,
            "amaturo": amaturo,
            "momo": momo,
            "bank": bank,
            "retenu": retenu,
            "kuri_par": kuri_par,
            "rank": rank,
            "share": round(share, 1),
            "n_total": n_total,
            "total_amaturo": total_amaturo,
            "impuzandengo": int(impuzandengo),
            "ako_akamaro": akamaro,
            "uko_byagenze": uko,
            "parish_name": parish,
            "week_date": week_date,
            "budget": budget,
            "budget_percent": round(budget_percent, 1),
            "budget_uko": budget_uko,
            "recorder_name": recorder_name,
            "recorder_role": recorder_role_label,
            "prev_total": prev_total,
            "diff_amount": diff_amount,
            "diff_pct": round(diff_pct, 1),
            "diff_label": diff_label,
        },
    }


def build_flat(church_name, week_date, total, parish_name=None):
    """Ubutumwa bwa fallback (y'umurongo umwe) — ikoreshwa niba data ya
    rankings itabonetse. Ihuza n'amategeko ya message2.py gusa mu gushimira,
    ariko nta breakdown. Ibi ni byo byari bisanzweho mbere y'uko builder
    ikorwa, byo kugirango endpoint ntigereke."""
    parish = parish_name or _DEFAULT_PARISH_NAME
    return (
        f"Murakoze {church_name} kw'amaturo y'icyumweru cya {week_date} "
        f"y'agaciro ka RWF {total:,.0f}. Imana ibahe umugisha. — {parish}"
    )
