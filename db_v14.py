"""
db_v14.py — V1.14 extensions for bulk messaging + reminder automation.

Builds on db_v13 (which builds on db). Adds:

Entities (new JSON files):
  bulk_send_batches.json  — one row per bulk-send batch (parish pastor
        fires thank-you SMS to ALL submitters in one action). Tracks
        mode (auto/manual/scheduled), status, scheduled_at, sent_at,
        and aggregate counts. Each thank_you_sms_log row written by a
        bulk batch carries batch_id so the audit trail links back.
  reminder_log.json       — one row per reminder SMS sent to a church
        that had NOT submitted offerings for the week. Same shape as
        thank_you_sms_log (church_id, recipient_phone, message, status)
        plus batch_id + week_date + reminder_type.
  reminder_config.json    — single-object config: enabled, days_after
        _week_start (0-6, Monday=0), hour, minute, message_template,
        last_run, auto_send_enabled. The scheduler reads this every
        tick and fires when the current time crosses the configured
        slot AND last_run is for a different week.

Helpers:
  insert_bulk_send_batch / list_bulk_send_log / find_bulk_batch /
  mark_bulk_batch_status / list_due_scheduled_batches
  insert_reminder_log / list_reminder_log / list_pending_reminders
  load_reminder_config / save_reminder_config
  list_pending_thank_you_by_batch (extends v13 for batch filtering)

Design notes:
  - We reuse db._read_tab / _write_tab / _read_obj / _write_obj / _new_id
    / _now_iso / _to_bool / _to_float / log_activity (imported from db
    and db_v13).
  - The thank_you_sms_log table is NOT migrated; we just add an optional
    `batch_id` field on insert (the bulk-messaging module sets it). Old
    rows without batch_id are unaffected (single sends have batch_id="").
  - Reminder log rows are separate from thank_you_sms_log so the audit
    trail for "reminders to non-submitters" doesn't pollute the "thank-
    you to submitters" view.
"""

import os
import json
import db
from db import (
    _read_tab, _write_tab, _new_id, _now_iso, _to_bool, _to_float,
    log_activity,
)
from db_v13 import _read_obj, _write_obj


# ==================================================================
# 1. BULK SEND BATCHES (parish pastor → all submitters in one action)
# ==================================================================
BULK_SEND_TAB = "bulk_send_batches"


def insert_bulk_send_batch(payload):
    """Record a bulk-send batch. `payload` carries:
       week_date, mode (auto|manual|scheduled), status, scheduled_at,
       sent_by, sent_by_name, message_override (str or ""), total (int),
       sent_count, failed_count, parish, notes.
    Returns the created record."""
    rec = {
        "id": _new_id("BB"),
        "week_date": payload.get("week_date", ""),
        "parish": payload.get("parish", ""),
        "mode": payload.get("mode", "manual"),      # auto|manual|scheduled
        "status": payload.get("status", "pending"), # pending|scheduled|sending|sent|partial|failed|cancelled
        "scheduled_at": payload.get("scheduled_at", ""),  # ISO datetime for scheduled mode
        "sent_by": payload.get("sent_by", ""),
        "sent_by_name": payload.get("sent_by_name", ""),
        "message_override": payload.get("message_override", ""),
        "total": int(payload.get("total", 0) or 0),
        "sent_count": int(payload.get("sent_count", 0) or 0),
        "failed_count": int(payload.get("failed_count", 0) or 0),
        "skipped_count": int(payload.get("skipped_count", 0) or 0),
        "notes": payload.get("notes", ""),
        "created_at": _now_iso(),
        "sent_at": payload.get("sent_at", ""),
        "gateway_responses": payload.get("gateway_responses", []),
    }
    rows = _read_tab(BULK_SEND_TAB)
    rows.append(rec)
    _write_tab(BULK_SEND_TAB, rows)
    return rec


def list_bulk_send_log(limit=100):
    """Bulk-send batches, newest first."""
    rows = _read_tab(BULK_SEND_TAB)
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return rows[:limit]


def find_bulk_batch(batch_id):
    if not batch_id:
        return None
    for r in _read_tab(BULK_SEND_TAB):
        if r.get("id") == batch_id:
            return r
    return None


def mark_bulk_batch_status(batch_id, updates):
    """Patch a bulk batch row (status, sent_count, sent_at, ...)."""
    if not batch_id:
        return None
    rows = _read_tab(BULK_SEND_TAB)
    for r in rows:
        if r.get("id") == batch_id:
            r.update(updates)
            _write_tab(BULK_SEND_TAB, rows)
            return r
    return None


def list_due_scheduled_batches(limit=50):
    """Scheduled batches whose scheduled_at <= now and status='scheduled'.
    The scheduler drains this list every tick."""
    rows = _read_tab(BULK_SEND_TAB)
    now = _now_iso()
    due = [r for r in rows
           if r.get("status") == "scheduled"
           and r.get("scheduled_at")
           and r.get("scheduled_at") <= now]
    due.sort(key=lambda x: x.get("scheduled_at", ""))
    return due[:limit]


# ==================================================================
# 2. REMINDER LOG (per non-submitter recipient)
# ==================================================================
REMINDER_LOG_TAB = "reminder_log"


def insert_reminder_log(payload):
    """One row per reminder SMS recipient. `payload` carries:
       batch_id, week_date, church_id, church_name, recipient_phone,
       recipient_name, message, reminder_type (week_missing|custom),
       sent_by, sent_by_name, status, gateway_response."""
    status = payload.get("status", "queued")
    rec = {
        "id": _new_id("RM"),
        "batch_id": payload.get("batch_id", ""),
        "week_date": payload.get("week_date", ""),
        "church_id": payload.get("church_id", ""),
        "church_name": payload.get("church_name", ""),
        "recipient_phone": payload.get("recipient_phone", ""),
        "recipient_name": payload.get("recipient_name", ""),
        "message": payload.get("message", ""),
        "reminder_type": payload.get("reminder_type", "week_missing"),
        "sent_by": payload.get("sent_by", ""),
        "sent_by_name": payload.get("sent_by_name", ""),
        "status": status,  # queued/sent/failed/dry_run
        "gateway_response": payload.get("gateway_response", ""),
        "created_at": _now_iso(),
        "queued_at": _now_iso() if status in ("queued", "dry_run") else None,
        "sent_at": _now_iso() if status == "sent" else None,
        "attempts": 0,
    }
    rows = _read_tab(REMINDER_LOG_TAB)
    rows.append(rec)
    _write_tab(REMINDER_LOG_TAB, rows)
    return rec


def list_reminder_log(church_id=None, limit=200):
    rows = _read_tab(REMINDER_LOG_TAB)
    if church_id:
        rows = [r for r in rows if r.get("church_id") == church_id]
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return rows[:limit]


def list_pending_reminders(limit=200):
    """Reminder rows still awaiting delivery (queued/dry_run)."""
    rows = _read_tab(REMINDER_LOG_TAB)
    pending = [r for r in rows if r.get("status") in ("queued", "dry_run")]
    pending.sort(key=lambda x: x.get("queued_at") or x.get("created_at", ""))
    return pending[:limit]


def update_reminder_log(rec_id, updates):
    if not rec_id:
        return None
    rows = _read_tab(REMINDER_LOG_TAB)
    for r in rows:
        if r.get("id") == rec_id:
            r.update(updates)
            _write_tab(REMINDER_LOG_TAB, rows)
            return r
    return None


# ==================================================================
# 3. REMINDER CONFIG (single-object — parish pastor sets day/time)
# ==================================================================
REMINDER_CONFIG_OBJ = "reminder_config"

_DEFAULT_REMINDER_CONFIG = {
    # Master switch. When False, the scheduler never auto-fires reminders.
    "enabled": False,
    # days_after_week_start: 0=Monday (week start), 1=Tuesday, ... 6=Sunday.
    # Default: 2 (Wednesday) — gives churches 2 days after the week starts
    # to submit before a reminder fires.
    "days_after_week_start": 2,
    "hour": 18,        # 0-23, local time
    "minute": 0,       # 0-59
    # Message template. Placeholders (replaced per-church at send time):
    #   {church_name}  — izina ry'itorero
    #   {week_date}    — tariki y'icyumweru (YYYY-MM-DD)
    #   {parish_name}  — izina rya paruwasi
    # If empty, a sensible default is used.
    "message_template": (
        "Muraho {church_name},\n\n"
        "Tugirango tubibutse ko amaturo y'icyumweru cya {week_date} "
        "atannzwe kuri paruwasi. Tugirango ayohereze vuba kugiraango "
        "raporo y'icyumweru ikore neza.\n\n"
        "Murakoze — {parish_name}"
    ),
    # Whether to auto-send reminders through the gateway (needs live
    # gateway) or just queue them for manual review/drain.
    "auto_send_enabled": False,
    "last_run": "",          # ISO datetime of the last auto-fire
    "last_run_week": "",     # week_date of the last auto-fire (prevents double-fire)
}


def load_reminder_config():
    obj = _read_obj(REMINDER_CONFIG_OBJ)
    if not obj:
        return dict(_DEFAULT_REMINDER_CONFIG)
    merged = dict(_DEFAULT_REMINDER_CONFIG)
    merged.update(obj)
    return merged


def save_reminder_config(updates):
    cur = load_reminder_config()
    for k in ("enabled", "days_after_week_start", "hour", "minute",
              "message_template", "auto_send_enabled", "last_run",
              "last_run_week"):
        if k in updates:
            cur[k] = updates[k]
    # Normalize.
    cur["enabled"] = bool(cur.get("enabled", False))
    cur["auto_send_enabled"] = bool(cur.get("auto_send_enabled", False))
    try:
        d = int(cur.get("days_after_week_start", 2))
        cur["days_after_week_start"] = max(0, min(6, d))
    except (TypeError, ValueError):
        cur["days_after_week_start"] = 2
    try:
        cur["hour"] = max(0, min(23, int(cur.get("hour", 18))))
    except (TypeError, ValueError):
        cur["hour"] = 18
    try:
        cur["minute"] = max(0, min(59, int(cur.get("minute", 0))))
    except (TypeError, ValueError):
        cur["minute"] = 0
    if not str(cur.get("message_template", "")).strip():
        cur["message_template"] = _DEFAULT_REMINDER_CONFIG["message_template"]
    cur["updated_at"] = _now_iso()
    _write_obj(REMINDER_CONFIG_OBJ, cur)
    return cur


# ==================================================================
# 4. THANK-YOU SMS — batch-id filter (extends v13 without modifying it)
# ==================================================================
def list_thank_you_sms_by_batch(batch_id, limit=500):
    """Thank-you SMS rows belonging to a specific bulk batch."""
    if not batch_id:
        return []
    rows = _read_tab("thank_you_sms_log")
    rows = [r for r in rows if r.get("batch_id") == batch_id]
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return rows[:limit]


# ==================================================================
# 5. V1.16 — WEEKLY OFFERINGS RESET + MANUAL CATEGORY RESET
# ==================================================================
# Two complementary reset mechanisms:
#
#   (A) Weekly auto-reset (finalize week). When a week ends (configurable
#       day/time), every offering row for that week is marked `finalized=`
#       True (read-only — protects history). The next week starts fresh
#       at zero: churches submit new offerings for the new week_date with
#       no carry-over. History is NEVER deleted — only the current week's
#       editable window rolls forward.
#
#   (B) Manual category reset. A parish pastor (or church finance) can
#       clear ONE offering category (e.g. just ICYACUMI_MOMO, or just
#       AMATURO) for a chosen church + week, so they can re-enter that
#       category from a clean starting point — without touching the
#       other categories. The matching ITEMS rows are deleted, and the
#       parent offering's total + distribution are recomputed. A reset
#       log row records who/when/what for the audit trail.
#
# Entities:
#   weekly_reset_config.json — single-object config: enabled,
#       finalize_day_of_week (0=Mon .. 6=Sun), hour, minute,
#       grace_days (extra days to wait before finalizing), last_run,
#       last_run_week.
#   weekly_reset_log.json    — one row per finalized week (week_date,
#       finalized_at, finalized_by, church_count, offering_count).
#   offering_reset_log.json  — one row per manual category reset
#       (church_id, week_date, category, removed_count, removed_total,
#        reset_by, reset_by_name, reset_at).
RESET_CONFIG_OBJ = "weekly_reset_config"
WEEKLY_RESET_LOG_TAB = "weekly_reset_log"
OFFERING_RESET_LOG_TAB = "offering_reset_log"

_DEFAULT_RESET_CONFIG = {
    "enabled": False,
    # 6 = Sunday evening is the natural week boundary (a new week's
    # Monday follows). 0-6 = Mon-Sun (Python weekday() convention).
    "finalize_day_of_week": 6,
    "hour": 23,
    "minute": 0,
    # How many days after the week's Monday to wait before finalizing.
    # 6 = finalize on Sunday (the last day of the week that started Mon).
    "grace_days": 6,
    "last_run": "",
    "last_run_week": "",
}


def load_weekly_reset_config():
    """Return the weekly-reset config, merged with defaults so callers
    always see a complete object."""
    cur = dict(_DEFAULT_RESET_CONFIG)
    saved = _read_obj(RESET_CONFIG_OBJ)
    if isinstance(saved, dict):
        cur.update(saved)
    return cur


def save_weekly_reset_config(updates):
    """Merge `updates` into the weekly-reset config and persist."""
    cur = load_weekly_reset_config()
    cur.update(updates or {})
    # Clamp numeric fields.
    try:
        cur["finalize_day_of_week"] = max(0, min(6, int(cur.get("finalize_day_of_week", 6))))
    except (TypeError, ValueError):
        cur["finalize_day_of_week"] = 6
    try:
        cur["hour"] = max(0, min(23, int(cur.get("hour", 23))))
    except (TypeError, ValueError):
        cur["hour"] = 23
    try:
        cur["minute"] = max(0, min(59, int(cur.get("minute", 0))))
    except (TypeError, ValueError):
        cur["minute"] = 0
    try:
        cur["grace_days"] = max(0, min(13, int(cur.get("grace_days", 6))))
    except (TypeError, ValueError):
        cur["grace_days"] = 6
    cur["updated_at"] = _now_iso()
    _write_obj(RESET_CONFIG_OBJ, cur)
    return cur


def list_weekly_reset_log(limit=100):
    """Finalized-week audit log, newest first."""
    rows = _read_tab(WEEKLY_RESET_LOG_TAB)
    rows.sort(key=lambda x: x.get("finalized_at", ""), reverse=True)
    return rows[:limit]


def insert_weekly_reset_log(payload):
    rec = {
        "id": _new_id("WR"),
        "week_date": payload.get("week_date", ""),
        "finalized_at": payload.get("finalized_at") or _now_iso(),
        "finalized_by": payload.get("finalized_by", ""),
        "finalized_by_name": payload.get("finalized_by_name", ""),
        "church_count": int(payload.get("church_count", 0) or 0),
        "offering_count": int(payload.get("offering_count", 0) or 0),
        "trigger": payload.get("trigger", "auto"),  # auto|manual
        "notes": payload.get("notes", ""),
    }
    rows = _read_tab(WEEKLY_RESET_LOG_TAB)
    rows.append(rec)
    _write_tab(WEEKLY_RESET_LOG_TAB, rows)
    return rec


def list_offering_reset_log(church_id=None, week_date=None, limit=200):
    """Manual category-reset audit log, newest first."""
    rows = _read_tab(OFFERING_RESET_LOG_TAB)
    if church_id:
        rows = [r for r in rows if r.get("church_id") == church_id]
    if week_date:
        rows = [r for r in rows if r.get("week_date") == week_date]
    rows.sort(key=lambda x: x.get("reset_at", ""), reverse=True)
    return rows[:limit]


def insert_offering_reset_log(payload):
    rec = {
        "id": _new_id("OR"),
        "church_id": payload.get("church_id", ""),
        "church_name": payload.get("church_name", ""),
        "week_date": payload.get("week_date", ""),
        "category": payload.get("category", ""),
        "removed_count": int(payload.get("removed_count", 0) or 0),
        "removed_total": float(payload.get("removed_total", 0.0) or 0.0),
        "reset_by": payload.get("reset_by", ""),
        "reset_by_name": payload.get("reset_by_name", ""),
        "reset_at": _now_iso(),
        "reason": payload.get("reason", "manual_category_reset"),
    }
    rows = _read_tab(OFFERING_RESET_LOG_TAB)
    rows.append(rec)
    _write_tab(OFFERING_RESET_LOG_TAB, rows)
    return rec


def finalize_week(week_date, finalized_by="", finalized_by_name="",
                  trigger="manual"):
    """Mark every offering for `week_date` as finalized (read-only).

    Finalizing does NOT delete anything — it flips `finalized=True` on
    each offering row so the parish/church UI can lock edits to past
    weeks. Returns a summary {week_date, church_count, offering_count}.

    Idempotent: re-finalizing an already-finalized week is a no-op that
    still returns the count.
    """
    if not week_date:
        return {"week_date": "", "church_count": 0, "offering_count": 0}
    offs = _read_tab(db.OFFERINGS_TAB)
    touched = 0
    church_ids = set()
    for o in offs:
        if o.get("week_date") == week_date:
            if not o.get("finalized"):
                o["finalized"] = True
                o["finalized_at"] = _now_iso()
            touched += 1
            church_ids.add(o.get("church_id", ""))
    if touched:
        _write_tab(db.OFFERINGS_TAB, offs)
        db._invalidate(db.OFFERINGS_TAB)
    insert_weekly_reset_log({
        "week_date": week_date,
        "finalized_by": finalized_by,
        "finalized_by_name": finalized_by_name,
        "church_count": len(church_ids),
        "offering_count": touched,
        "trigger": trigger,
    })
    return {
        "week_date": week_date,
        "church_count": len(church_ids),
        "offering_count": touched,
    }


def reset_offering_category(church_id, week_date, category,
                            reset_by="", reset_by_name="", reason=""):
    """Delete every ITEMS row matching (church_id, week_date, category)
    and recompute the parent offering's total + distribution. Used when a
    finance officer entered the wrong amounts for one category and wants
    to start that category over from zero — without touching the others.

    Returns {church_id, week_date, category, removed_count, removed_total,
    offering_updated (bool)}.

    If no offering exists for that church/week, returns zeros (nothing
    to reset). If the offering is finalized, refuses (returns
    error='finalized').
    """
    cat = (category or "").upper().strip()
    if not cat or not church_id or not week_date:
        return {"error": "church_id, week_date na category bikenewe."}
    offs = _read_tab(db.OFFERINGS_TAB)
    off = next((o for o in offs
                if o.get("church_id") == church_id
                and o.get("week_date") == week_date), None)
    if not off:
        return {
            "church_id": church_id, "week_date": week_date,
            "category": cat, "removed_count": 0, "removed_total": 0.0,
            "offering_updated": False, "note": "Nta maturo yabonetse.",
        }
    if off.get("finalized"):
        return {"error": "Icyumweru cyarangiye (finalized) — nticyongera kwandikwamo."}

    items = _read_tab(db.ITEMS_TAB)
    keep = []
    removed = []
    for it in items:
        if (it.get("offering_id") == off.get("id")
                and (it.get("category") or "").upper() == cat):
            removed.append(it)
        else:
            keep.append(it)
    removed_total = sum(_to_float(it.get("amount", 0.0)) for it in removed)

    if removed:
        _write_tab(db.ITEMS_TAB, keep)
        db._invalidate(db.ITEMS_TAB)
        # Recompute the parent offering's total + distribution.
        new_items = [it for it in keep if it.get("offering_id") == off.get("id")]
        off["total"] = sum(_to_float(it.get("amount", 0.0)) for it in new_items)
        budget = db.get_church_budget(church_id, week_date) \
            or _to_float(off.get("budget", 0.0))
        off["budget"] = budget
        off["distribution"] = db.compute_distribution(
            new_items, _to_float(off.get("abana_amount", 0.0)), budget)
        off["updated_at"] = _now_iso()
        _write_tab(db.OFFERINGS_TAB, offs)
        db._invalidate(db.OFFERINGS_TAB)

    # Find the church name for the audit log.
    church = db.find_church(church_id) if hasattr(db, "find_church") else None
    insert_offering_reset_log({
        "church_id": church_id,
        "church_name": (church or {}).get("name", "") if church else "",
        "week_date": week_date,
        "category": cat,
        "removed_count": len(removed),
        "removed_total": removed_total,
        "reset_by": reset_by,
        "reset_by_name": reset_by_name,
        "reason": reason or "manual_category_reset",
    })
    return {
        "church_id": church_id,
        "week_date": week_date,
        "category": cat,
        "removed_count": len(removed),
        "removed_total": removed_total,
        "offering_updated": bool(removed),
    }


def list_finalized_weeks(limit=52):
    """Distinct finalized week_dates, newest first — so the UI can show
    which past weeks are locked."""
    offs = _read_tab(db.OFFERINGS_TAB)
    weeks = sorted({o.get("week_date", "") for o in offs if o.get("finalized")},
                   reverse=True)
    return weeks[:limit]


def is_week_finalized(week_date):
    """True if ANY offering for `week_date` is marked finalized."""
    if not week_date:
        return False
    offs = _read_tab(db.OFFERINGS_TAB)
    return any(o.get("finalized") for o in offs
               if o.get("week_date") == week_date)


# ==================================================================
# 6. V1.16 — PROOF-FILE AUDIT (parish pastor browses all uploads)
# ==================================================================
# The proof files themselves are stored in uploads/ and the per-item
# metadata lives in ITEMS_TAB (each item has an `attachments` list).
# db.list_offering_attachments() already flattens them. Here we add a
# helper that enriches each attachment with a signed-ish view URL and
# groups them so the audit UI can render by church / by week / by kind.

PROOF_KIND_LABELS = {
    "momo_sms":   "MoMo SMS",
    "bank_slip":  "Icyemezo cya Banki",
    "other":      "Ikindi",
}


def proof_kind_label(kind):
    return PROOF_KIND_LABELS.get((kind or "").lower(), kind or "")


def list_proof_attachments_enriched(church_id=None, start_date=None,
                                    end_date=None, kind=None):
    """Same flat list as db.list_offering_attachments but with the
    church_name + week_date + a view_url attached, ready for the audit
    UI. Filters by kind ('momo_sms' | 'bank_slip' | 'other')."""
    rows = db.list_offering_attachments(
        church_id=church_id, start_date=start_date, end_date=end_date)
    out = []
    for r in rows:
        if kind and (r.get("kind") or "").lower() != kind:
            continue
        r = dict(r)
        r["kind_label"] = proof_kind_label(r.get("kind"))
        r["view_url"] = "/uploads/" + str(r.get("path", ""))
        # Determine file type for icon/preview choice.
        p = str(r.get("path", "")).lower()
        if p.endswith(".pdf"):
            r["file_type"] = "pdf"
        elif p.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            r["file_type"] = "image"
        else:
            r["file_type"] = "other"
        out.append(r)
    return out
