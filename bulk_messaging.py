"""
bulk_messaging.py — Bulk thank-you SMS + reminder automation (V1.14).

Three send modes for thank-you SMS to churches that SUBMITTED offerings:
  1. AUTO     — fire immediately through the gateway; if gateway is not
                live (dry_run or no endpoint), rows are queued with
                status=dry_run and the existing scheduler auto-drains
                them when the gateway comes up.
  2. MANUAL   — parish pastor previews every message, may override the
                text per-batch (one custom message for all churches, or
                the message2.py-style builder per church), then fires.
  3. SCHEDULED — parish pastor picks a future datetime; rows are queued
                with status=scheduled + scheduled_at. The scheduler
                fires them when the time arrives (process_scheduled_bulk
                _sends, runs every minute so scheduled sends fire within
                ~60s of their due time).

Reminder SMS for churches that DID NOT submit:
  - find_non_submitters(week_date) diffs list_churches() against the
    churches that appear in rankings(week_date). For each non-submitter,
    build a reminder message from the configured template.
  - Reminders can be fired manually (POST /api/bulk-send/reminder) or
    automatically by the scheduler (process_reminders, every 5 minutes,
    when reminder_config.enabled + the day/time slot is crossed).

The message2.py format is preserved exactly — thank_you_message.build()
is the single source of truth for the per-church thank-you text, so a
bulk send produces the same message a per-church send would.
"""

import os
from datetime import datetime, timedelta

import db
import db_v13 as v13
import db_v14 as v14
import thank_you_message as tym


# ==================================================================
# Week-date helper (Monday ISO date). db.py computes this inline in two
# places; we centralize it here so bulk + reminder share one source.
# ==================================================================
def week_start(date=None):
    """Return the Monday of the week containing `date` as an ISO string.
    `date` may be a date/datetime or an ISO string; default = today."""
    if date is None:
        d = datetime.now().date()
    elif isinstance(date, str):
        try:
            d = datetime.fromisoformat(date[:10]).date()
        except ValueError:
            d = datetime.now().date()
    else:
        d = date.date() if hasattr(date, "date") else date
    start = d - timedelta(days=d.weekday())  # Monday
    return start.isoformat()


def _parish_name(church):
    """Pull the parish name from a church record, with a default."""
    if not church:
        return "ADEPR Paruwasi"
    return (church.get("parish") or "").strip() or "ADEPR Paruwasi"


# ==================================================================
# Submitters / non-submitters for a given week
# ==================================================================
def find_submitters(week_date, parish=None):
    """Churches that submitted offerings for `week_date`. Returns a list
    of ranking-row dicts (church_id, name, leader_name, leader_phone,
    total, igiteranyo, rank, ...). Sorted by rank asc."""
    rows = db.rankings(parish=parish, start_date=week_date, end_date=week_date) or []
    rows.sort(key=lambda x: x.get("rank", 999))
    return rows


def find_non_submitters(week_date, parish=None):
    """Churches that have NOT submitted offerings for `week_date`.
    Diffs list_churches() against find_submitters(). Returns a list of
    church records (id, name, parish, leader_name, leader_phone,
    leader_email, ...). Sorted by name."""
    all_churches = db.list_churches(parish=parish) or []
    submitted_ids = {str(r.get("church_id", "")) for r in find_submitters(week_date, parish)}
    missing = [c for c in all_churches
               if c.get("active", True)
               and str(c.get("id", "")) not in submitted_ids]
    missing.sort(key=lambda x: x.get("name", ""))
    return missing


# ==================================================================
# Build messages (thank-you for submitters, reminder for non-submitters)
# ==================================================================
def build_bulk_messages(week_date, parish=None, message_override=None):
    """Build a per-church thank-you message for every submitter.

    If `message_override` is a non-empty string, it replaces the builder
    output for ALL churches (the parish pastor's custom text). Otherwise
    each message is built by thank_you_message.build() — the message2.py
    format with imibare, ranking, ijanisha, umugisha.

    Returns: list of {
        church_id, church_name, recipient_phone, recipient_name,
        message, available (bool), meta
    }
    """
    submitters = find_submitters(week_date, parish)
    out = []
    for row in submitters:
        church_id = str(row.get("church_id", ""))
        church = db.find_church(church_id) or {}
        parish_name = _parish_name(church)
        recipient_name = (row.get("leader_name") or church.get("leader_name") or "").strip()
        recipient_phone = (row.get("leader_phone") or church.get("leader_phone") or "").strip()
        if message_override:
            # Apply the same {church_name}/{week_date}/{parish_name}
            # placeholders the reminder template uses, so a custom
            # thank-you message can still be per-church.
            message = _apply_template(message_override, {
                "church_name": row.get("name") or church.get("name", ""),
                "week_date": week_date,
                "parish_name": parish_name,
                "leader_name": recipient_name,
            })
            available = True
            meta = {"custom": True, "parish_name": parish_name}
        else:
            built = tym.build(church_id, week_date, parish_name=parish_name)
            message = built["message"]
            available = built["available"]
            meta = built.get("meta", {})
        out.append({
            "church_id": church_id,
            "church_name": row.get("name") or church.get("name", ""),
            "recipient_phone": recipient_phone,
            "recipient_name": recipient_name,
            "message": message,
            "available": available,
            "meta": meta,
        })
    return out


def _apply_template(template, ctx):
    """Replace {church_name} / {week_date} / {parish_name} / {leader_name}
    placeholders. Missing keys are left as-is (defensive)."""
    if not template:
        return ""
    out = template
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def build_reminder_messages(week_date, parish=None, custom_message=None):
    """Build a reminder message for every non-submitter.

    If `custom_message` is given, it's used as the template (with
    placeholders). Otherwise the configured reminder_config template is
    used. Returns: list of {
        church_id, church_name, recipient_phone, recipient_name, message
    }
    """
    config = v14.load_reminder_config()
    template = custom_message or config.get("message_template", "")
    non_submitters = find_non_submitters(week_date, parish)
    out = []
    for c in non_submitters:
        parish_name = _parish_name(c)
        recipient_name = (c.get("leader_name") or "").strip()
        recipient_phone = (c.get("leader_phone") or "").strip()
        message = _apply_template(template, {
            "church_name": c.get("name", ""),
            "week_date": week_date,
            "parish_name": parish_name,
            "leader_name": recipient_name,
        })
        out.append({
            "church_id": c.get("id", ""),
            "church_name": c.get("name", ""),
            "recipient_phone": recipient_phone,
            "recipient_name": recipient_name,
            "message": message,
        })
    return out


# ==================================================================
# Preview endpoints (no send — for the UI)
# ==================================================================
def preview_bulk(week_date, parish=None, message_override=None):
    """UI preview: which churches submitted, with their messages."""
    submitters = find_submitters(week_date, parish)
    messages = build_bulk_messages(week_date, parish, message_override)
    non_submitters = find_non_submitters(week_date, parish)
    return {
        "week_date": week_date,
        "submitters_count": len(submitters),
        "non_submitters_count": len(non_submitters),
        "messages": messages,
        "non_submitters": [{"id": c.get("id"), "name": c.get("name"),
                            "leader_name": c.get("leader_name"),
                            "leader_phone": c.get("leader_phone")}
                           for c in non_submitters],
    }


def preview_reminder(week_date, parish=None, custom_message=None):
    """UI preview: which churches didn't submit, with the reminder text."""
    messages = build_reminder_messages(week_date, parish, custom_message)
    return {
        "week_date": week_date,
        "non_submitters_count": len(messages),
        "messages": messages,
    }


# ==================================================================
# Send execution
# ==================================================================
def _gateway_live():
    """True if the gateway is configured for real sends."""
    gw = v13.load_sms_gateway()
    return bool(gw.get("endpoint") and not gw.get("dry_run"))


def send_bulk_now(messages, sent_by, sent_by_name, batch_id="",
                  week_date="", parish=""):
    """Execute a bulk send immediately. For each church:
       - build recipients = [leader] (extra_contacts not supported in
         bulk mode — keep it simple; the per-church send route handles
         extra_contacts)
       - call sms.broadcast() if gateway is live, else queue as dry_run
       - log one thank_you_sms_log row with batch_id
    Returns: {sent, failed, skipped, total, results, batch_status}
    """
    import sms as sms_mod

    gw = v13.load_sms_gateway()
    live = _gateway_live()
    sent = failed = skipped = 0
    results = []

    for m in messages:
        phone = (m.get("recipient_phone") or "").strip()
        church_id = m.get("church_id", "")
        church_name = m.get("church_name", "")
        message = m.get("message", "")
        recipient_name = m.get("recipient_name", "") or church_name
        if not phone:
            # No phone — log a skipped row so the audit trail shows why.
            v13.insert_thank_you_sms({
                "church_id": church_id, "church_name": church_name,
                "week_date": week_date, "total_offering": 0,
                "recipient_phone": "", "recipient_name": recipient_name,
                "extra_contacts": [], "message": message,
                "sent_by": sent_by, "sent_by_name": sent_by_name,
                "status": "failed",
                "gateway_response": "no recipient phone",
            })
            skipped += 1
            results.append({"church_id": church_id, "church_name": church_name,
                            "ok": False, "reason": "no phone"})
            continue
        if live:
            bres = sms_mod.broadcast(
                [{"name": recipient_name, "phone": phone}], message, dry_run=False)
            if bres.get("sent", 0) > 0:
                status = "sent"
                gw_resp = (f"sent: {bres.get('sent',0)}/{bres.get('total',0)}")[:500]
                sent += 1
            else:
                status = "failed"
                gw_resp = (f"failed: {bres.get('results', '')}")[:500]
                failed += 1
        else:
            # Gateway not live — queue as dry_run; the existing auto-send
            # scheduler (process_thank_you_queue) will drain it when the
            # gateway comes up, IF auto_send_enabled is on.
            status = "dry_run"
            gw_resp = "dry_run (gateway not live)"
            sent += 1  # counted as queued-successfully
        v13.insert_thank_you_sms({
            "church_id": church_id, "church_name": church_name,
            "week_date": week_date, "total_offering": 0,
            "recipient_phone": phone, "recipient_name": recipient_name,
            "extra_contacts": [], "message": message,
            "sent_by": sent_by, "sent_by_name": sent_by_name,
            "status": status, "gateway_response": gw_resp,
        })
        results.append({"church_id": church_id, "church_name": church_name,
                        "ok": status in ("sent", "dry_run"),
                        "status": status, "phone": phone})

    # Determine batch status.
    if not live and sent > 0 and failed == 0:
        batch_status = "queued"  # all dry_run, waiting for gateway
    elif failed == 0 and skipped == 0:
        batch_status = "sent"
    elif sent > 0 and (failed > 0 or skipped > 0):
        batch_status = "partial"
    elif sent == 0:
        batch_status = "failed"
    else:
        batch_status = "partial"

    if batch_id:
        v14.mark_bulk_batch_status(batch_id, {
            "status": batch_status,
            "sent_count": sent,
            "failed_count": failed,
            "skipped_count": skipped,
            "sent_at": db._now_iso(),
        })
    db.log_activity({
        "actor_id": sent_by, "actor_name": sent_by_name,
        "actor_role": "PARISH_PASTOR", "church_id": "",
        "action": "BULK_THANK_YOU_SENT",
        "target": f"{sent}/{len(messages)} churches (week {week_date})",
        "detail": f"batch={batch_id} mode=now status={batch_status}",
        "scope": "parish",
    })
    return {"sent": sent, "failed": failed, "skipped": skipped,
            "total": len(messages), "results": results,
            "batch_status": batch_status, "gateway_live": live}


def schedule_bulk(messages, scheduled_at, sent_by, sent_by_name,
                  week_date="", parish=""):
    """Queue a bulk send for later. Creates a batch with status=scheduled
    + scheduled_at, and logs one thank_you_sms_log row per church with
    status=queued + batch_id. The scheduler's process_scheduled_bulk
    _sends() fires the actual send when scheduled_at arrives."""
    batch = v14.insert_bulk_send_batch({
        "week_date": week_date, "parish": parish,
        "mode": "scheduled", "status": "scheduled",
        "scheduled_at": scheduled_at,
        "sent_by": sent_by, "sent_by_name": sent_by_name,
        "total": len(messages),
    })
    batch_id = batch["id"]
    for m in messages:
        v13.insert_thank_you_sms({
            "church_id": m.get("church_id", ""),
            "church_name": m.get("church_name", ""),
            "week_date": week_date, "total_offering": 0,
            "recipient_phone": m.get("recipient_phone", ""),
            "recipient_name": m.get("recipient_name", ""),
            "extra_contacts": [], "message": m.get("message", ""),
            "sent_by": sent_by, "sent_by_name": sent_by_name,
            "status": "queued",
            "gateway_response": f"scheduled for {scheduled_at}",
        })
    db.log_activity({
        "actor_id": sent_by, "actor_name": sent_by_name,
        "actor_role": "PARISH_PASTOR", "church_id": "",
        "action": "BULK_THANK_YOU_SCHEDULED",
        "target": f"{len(messages)} churches (week {week_date})",
        "detail": f"batch={batch_id} at={scheduled_at}",
        "scope": "parish",
    })
    return {"batch_id": batch_id, "scheduled_at": scheduled_at,
            "total": len(messages)}


def fire_scheduled_batch(batch):
    """Fire a scheduled batch that is now due. Rebuilds messages from
    the batch's week_date (so fresh offering data is used — a church
    that submitted AFTER the batch was scheduled gets a real thank-you
    instead of a stale dry_run), then calls send_bulk_now."""
    week_date = batch.get("week_date", "")
    parish = batch.get("parish", "")
    message_override = batch.get("message_override", "") or None
    messages = build_bulk_messages(week_date, parish, message_override)
    if not messages:
        v14.mark_bulk_batch_status(batch["id"], {
            "status": "cancelled",
            "notes": "no submitters when fired",
            "sent_at": db._now_iso(),
        })
        return {"batch_id": batch["id"], "status": "cancelled",
                "reason": "no submitters"}
    v14.mark_bulk_batch_status(batch["id"], {"status": "sending"})
    return send_bulk_now(
        messages,
        sent_by=batch.get("sent_by", ""),
        sent_by_name=batch.get("sent_by_name", ""),
        batch_id=batch["id"],
        week_date=week_date, parish=parish,
    )


def send_reminders_now(messages, sent_by, sent_by_name, week_date="",
                       parish="", custom_message=None):
    """Execute a reminder send immediately. Logs one reminder_log row
    per non-submitter. Same live/dry_run logic as send_bulk_now."""
    import sms as sms_mod
    gw = v13.load_sms_gateway()
    live = _gateway_live() and v14.load_reminder_config().get("auto_send_enabled", False)
    sent = failed = skipped = 0
    results = []
    batch_id = ""  # reminders don't need a batch row, but we group by run

    for m in messages:
        phone = (m.get("recipient_phone") or "").strip()
        church_id = m.get("church_id", "")
        church_name = m.get("church_name", "")
        message = m.get("message", "")
        recipient_name = m.get("recipient_name", "") or church_name
        if not phone:
            v14.insert_reminder_log({
                "batch_id": batch_id, "week_date": week_date,
                "church_id": church_id, "church_name": church_name,
                "recipient_phone": "", "recipient_name": recipient_name,
                "message": message, "reminder_type": "week_missing",
                "sent_by": sent_by, "sent_by_name": sent_by_name,
                "status": "failed", "gateway_response": "no phone",
            })
            skipped += 1
            results.append({"church_id": church_id, "ok": False,
                            "reason": "no phone"})
            continue
        if live:
            bres = sms_mod.broadcast(
                [{"name": recipient_name, "phone": phone}], message, dry_run=False)
            if bres.get("sent", 0) > 0:
                status = "sent"
                gw_resp = (f"sent: {bres.get('sent',0)}/{bres.get('total',0)}")[:500]
                sent += 1
            else:
                status = "failed"
                gw_resp = (f"failed: {bres.get('results', '')}")[:500]
                failed += 1
        else:
            status = "dry_run"
            gw_resp = "dry_run (gateway not live or auto_send off)"
            sent += 1
        v14.insert_reminder_log({
            "batch_id": batch_id, "week_date": week_date,
            "church_id": church_id, "church_name": church_name,
            "recipient_phone": phone, "recipient_name": recipient_name,
            "message": message, "reminder_type": "week_missing",
            "sent_by": sent_by, "sent_by_name": sent_by_name,
            "status": status, "gateway_response": gw_resp,
        })
        results.append({"church_id": church_id, "church_name": church_name,
                        "ok": status in ("sent", "dry_run"),
                        "status": status, "phone": phone})

    db.log_activity({
        "actor_id": sent_by, "actor_name": sent_by_name,
        "actor_role": "PARISH_PASTOR", "church_id": "",
        "action": "REMINDER_SENT",
        "target": f"{sent}/{len(messages)} non-submitters (week {week_date})",
        "detail": f"live={live}",
        "scope": "parish",
    })
    return {"sent": sent, "failed": failed, "skipped": skipped,
            "total": len(messages), "results": results,
            "gateway_live": live}
