"""
scheduler.py — Background automation for ADEPR MIS (V1.6).

Runs two APScheduler jobs in a background thread:

  1. queue_processor — every 2 minutes. Drains the message queue: SMS via
     the gateway (sms.py) and email via SMTP (smtplib). If no connection
     is available, messages stay "pending" and are retried on the next
     tick (up to N attempts, then marked "failed"). So a user who queues
     a message while offline has it sent automatically the moment the
     connection comes back — no manual retry needed.

  2. weekly_church_report — once a week (default Monday 08:00). For every
     church with an email address, generates the weekly offering report
     (Excel via reports.py) and emails it as an attachment. Each send is
     logged in email_reports_log so the parish pastor can audit delivery.

If SMTP is not configured (host empty), email messages are skipped
(status "skipped") and the weekly report job is a no-op — the system
keeps running, it just does not send mail. This keeps the MIS usable
offline without errors.
"""

import os
import smtplib
import threading
import traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta

import db

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _HAS_APS = True
except Exception:
    _HAS_APS = False

_scheduler = None
_lock = threading.Lock()


# ------------------------------------------------------------------
# Connection probe — do we have a route to the gateway / SMTP server?
# ------------------------------------------------------------------
def _gateway_reachable():
    url = (db.load_system_settings().get("sms_gateway_url") or "").strip()
    if not url:
        return False
    try:
        import requests
        from urllib.parse import urlparse
        host = urlparse(url).hostname
        port = urlparse(url).port or (443 if url.startswith("https") else 80)
        import socket
        s = socket.create_connection((host, port), timeout=3)
        s.close()
        return True
    except Exception:
        return False


def _smtp_reachable():
    s = db.load_system_settings()
    host = (s.get("smtp_host") or "").strip()
    if not host:
        return False
    try:
        port = int(s.get("smtp_port") or 587)
        sock = smtplib.SMTP(host, port, timeout=5)
        sock.quit()
        return True
    except Exception:
        return False


# ------------------------------------------------------------------
# Send helpers
# ------------------------------------------------------------------
def _send_email(to, subject, body, attachment_path=None):
    """Send one email via configured SMTP. Returns (ok, error)."""
    s = db.load_system_settings()
    host = (s.get("smtp_host") or "").strip()
    if not host:
        return False, "SMTP ntabwo ikonfigiwe (host ntiri mu igenamiterere)."
    port = int(s.get("smtp_port") or 587)
    user = s.get("smtp_user", "")
    pwd = s.get("smtp_password", "")
    frm = (s.get("smtp_from") or user or "adepr-mis@local").strip()
    use_tls = bool(s.get("smtp_use_tls", True))

    msg = MIMEMultipart()
    msg["From"] = frm
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application",
                            "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition",
                        "attachment",
                        filename=os.path.basename(attachment_path))
        msg.attach(part)

    srv = smtplib.SMTP(host, port, timeout=15)
    try:
        if use_tls:
            srv.starttls()
        if user and pwd:
            srv.login(user, pwd)
        srv.sendmail(frm, [to], msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)[:200]
    finally:
        try:
            srv.quit()
        except Exception:
            pass


def _send_sms(to, body):
    """Send one SMS via the gateway. Returns (ok, response)."""
    import sms
    res = sms.send_one_sms(to, body, dry_run=db.load_system_settings()
                           .get("sms_dry_run", True))
    return res.get("ok", False), res.get("response", "")


# ------------------------------------------------------------------
# Queue processor job
# ------------------------------------------------------------------
def process_queue():
    """Drain all pending messages. Each one: probe the right channel,
    send if reachable, otherwise leave pending (next tick retries)."""
    settings = db.load_system_settings()
    if not settings.get("auto_process_queue", True):
        return {"processed": 0, "reason": "auto disabled"}

    pending = db.pending_queue_messages()
    if not pending:
        # Still record the run so the health panel shows "alive".
        db.save_system_settings({"last_queue_run": db._now_iso()})
        return {"processed": 0, "reason": "empty"}

    sms_up = _gateway_reachable()
    email_up = _smtp_reachable()
    max_retries = int(settings.get("queue_max_retries", 5))

    sent = failed = skipped = 0
    for m in pending:
        ch = m.get("channel", "sms")
        if ch == "sms":
            if not sms_up:
                db.mark_message_failed(m["id"], "gateway ntabwo ikora",
                                        max_retries=max_retries)
                skipped += 1
                continue
            ok, resp = _send_sms(m.get("to", ""), m.get("body", ""))
        else:  # email
            if not email_up:
                db.mark_message_failed(m["id"], "SMTP ntabwo ikora",
                                        max_retries=max_retries)
                skipped += 1
                continue
            ok, resp = _send_email(m.get("to", ""), m.get("subject", ""),
                                   m.get("body", ""))
        if ok:
            db.mark_message_sent(m["id"], resp)
            sent += 1
        else:
            db.mark_message_failed(m["id"], resp, max_retries=max_retries)
            failed += 1

    db.save_system_settings({"last_queue_run": db._now_iso()})
    return {"processed": len(pending), "sent": sent,
            "failed": failed, "skipped": skipped,
            "sms_up": sms_up, "email_up": email_up}


# ------------------------------------------------------------------
# Weekly church report job
# ------------------------------------------------------------------
def send_weekly_reports(trigger="auto"):
    """For each church with an email, attach the weekly Excel and mail it."""
    settings = db.load_system_settings()
    if not settings.get("auto_weekly_email", True) and trigger == "auto":
        return {"sent": 0, "reason": "auto disabled"}

    import reports as reports_mod
    results = {"sent": 0, "failed": 0, "skipped": 0, "churches": []}
    for c in db.list_churches():
        email = (c.get("email") or "").strip()
        church_name = c.get("name", "")
        if not email:
            results["skipped"] += 1
            continue
        try:
            path = reports_mod.export_excel(period="weekly",
                                           parish=c.get("id", ""))
            subject = (f"Incamake y'icyumweru — Itorero rya {church_name}")
            body = (f"Yezu Kristu azane umugisha.\n\n"
                    f"Iyi mirongo irimo incamake y'amaturo y'icyumweru "
                    f"cy'itorero rya {church_name}.\n"
                    f"Fungura file y'Excel yo kureba byose.\n\n"
                    f"— ADEPR Paruwasi ya Ruhango (MIS)")
            ok, err = _send_email(email, subject, body, attachment_path=path)
            db.log_email_report({
                "church_id": c.get("id", ""),
                "church_name": church_name,
                "recipient": email,
                "subject": subject,
                "period": "weekly",
                "status": "sent" if ok else "failed",
                "error": "" if ok else err,
                "trigger": trigger,
            })
            if ok:
                results["sent"] += 1
                results["churches"].append({"name": church_name,
                                            "email": email, "ok": True})
            else:
                results["failed"] += 1
                results["churches"].append({"name": church_name,
                                            "email": email, "ok": False,
                                            "error": err})
        except Exception as e:
            db.log_email_report({
                "church_id": c.get("id", ""),
                "church_name": church_name,
                "recipient": email,
                "subject": "weekly report",
                "period": "weekly",
                "status": "failed",
                "error": str(e)[:200],
                "trigger": trigger,
            })
            results["failed"] += 1

    db.save_system_settings({"last_email_run": db._now_iso()})
    return results


# ------------------------------------------------------------------
# Thank-you SMS auto-send queue (V1.14)
# ------------------------------------------------------------------
def process_thank_you_queue():
    """Drain thank-you SMS rows still in 'queued'/'dry_run' status, sending
    them through the gateway. Only fires when ALL of:
      - gateway config has auto_send_enabled=True
      - gateway is live (endpoint set AND dry_run=False)
    Otherwise it leaves the queue untouched (next tick retries).

    Returns a small summary dict for logging/health."""
    try:
        import db_v13 as v13
        import sms as sms_mod
    except Exception as e:
        return {"processed": 0, "reason": f"import error: {e}"}

    try:
        gw = v13.load_sms_gateway()
    except Exception as e:
        return {"processed": 0, "reason": f"gateway load error: {e}"}

    # Gate 1: auto-send must be enabled by the parish pastor.
    if not gw.get("auto_send_enabled"):
        return {"processed": 0, "reason": "auto_send disabled"}
    # Gate 2: gateway must be live (endpoint + not dry_run).
    if not gw.get("endpoint") or gw.get("dry_run"):
        return {"processed": 0, "reason": "gateway not live (dry_run or no endpoint)"}

    pending = v13.list_pending_thank_you_sms(limit=200)
    if not pending:
        return {"processed": 0, "reason": "empty"}

    sent = failed = 0
    for row in pending:
        rid = row.get("id")
        phone = (row.get("recipient_phone") or "").strip()
        msg = row.get("message") or ""
        # Skip rows with no phone — mark failed so we don't loop forever.
        if not phone:
            v13.update_thank_you_sms(rid, {
                "status": "failed",
                "gateway_response": "no recipient phone",
                "sent_at": db._now_iso(),
                "attempts": int(row.get("attempts", 0)) + 1,
            })
            failed += 1
            continue
        try:
            res = sms_mod.send_one_sms(phone, msg, dry_run=False)
            attempts = int(row.get("attempts", 0)) + 1
            if res.get("ok"):
                v13.update_thank_you_sms(rid, {
                    "status": "sent",
                    "gateway_response": res.get("response", ""),
                    "sent_at": db._now_iso(),
                    "attempts": attempts,
                })
                sent += 1
            else:
                # Don't flip to 'failed' on the first hiccup — leave as
                # 'queued' so the next tick retries, up to a sane cap.
                if attempts >= 5:
                    v13.update_thank_you_sms(rid, {
                        "status": "failed",
                        "gateway_response": (f"HTTP {res.get('status')} — "
                                             f"{res.get('response', '')}")[:500],
                        "sent_at": db._now_iso(),
                        "attempts": attempts,
                    })
                    failed += 1
                else:
                    v13.update_thank_you_sms(rid, {
                        "gateway_response": (f"retry {attempts}/5: HTTP "
                                             f"{res.get('status')} — "
                                             f"{res.get('response', '')}")[:500],
                        "attempts": attempts,
                    })
        except Exception as e:
            attempts = int(row.get("attempts", 0)) + 1
            v13.update_thank_you_sms(rid, {
                "gateway_response": f"exception: {str(e)[:200]}",
                "attempts": attempts,
            })
            failed += 1
    return {"processed": sent + failed, "sent": sent, "failed": failed}


# ------------------------------------------------------------------
# Scheduled bulk send (V1.14) — fire batches whose scheduled_at arrived
# ------------------------------------------------------------------
def process_scheduled_bulk_sends():
    """Drain bulk-send batches with status='scheduled' whose scheduled_at
    has arrived. Runs every minute so a scheduled send fires within ~60s
    of its due time. Rebuilds messages from the batch's week_date at fire
    time so fresh offering data is used."""
    try:
        import db_v14 as v14
        import bulk_messaging as bm
    except Exception as e:
        return {"processed": 0, "reason": f"import error: {e}"}

    due = v14.list_due_scheduled_batches(limit=50)
    if not due:
        return {"processed": 0, "reason": "empty"}

    fired = 0
    failed = 0
    for batch in due:
        try:
            res = bm.fire_scheduled_batch(batch)
            if res.get("batch_status") in ("sent", "partial", "queued"):
                fired += 1
            elif res.get("status") == "cancelled":
                pass  # no submitters — not a failure
            else:
                failed += 1
        except Exception as e:
            v14.mark_bulk_batch_status(batch.get("id", ""), {
                "status": "failed",
                "notes": f"fire error: {str(e)[:200]}",
                "sent_at": db._now_iso(),
            })
            failed += 1
    return {"processed": fired + failed, "fired": fired, "failed": failed}


# ------------------------------------------------------------------
# Reminder auto-send (V1.14) — fire reminders to non-submitters at the
# configured day/time. Runs every 5 minutes; only fires when:
#   - reminder_config.enabled is True
#   - the current weekday/hour/minute crosses the configured slot
#   - last_run_week != current week (prevents double-fire in the same week)
# ------------------------------------------------------------------
def process_reminders():
    """Auto-fire reminder SMS to churches that haven't submitted for the
    current week, when the configured time slot is crossed."""
    try:
        import db_v14 as v14
        import bulk_messaging as bm
    except Exception as e:
        return {"processed": 0, "reason": f"import error: {e}"}

    cfg = v14.load_reminder_config()
    if not cfg.get("enabled"):
        return {"processed": 0, "reason": "reminder disabled"}

    now = datetime.now()
    today = now.date()
    monday = today - timedelta(days=today.weekday())
    week_str = monday.isoformat()

    # Already fired this week? Skip.
    if cfg.get("last_run_week") == week_str:
        return {"processed": 0, "reason": "already fired this week"}

    # Has the configured slot been crossed this week?
    target_day = monday + timedelta(days=int(cfg.get("days_after_week_start", 2)))
    target_dt = datetime.combine(target_day, datetime.min.time()).replace(
        hour=int(cfg.get("hour", 18)), minute=int(cfg.get("minute", 0)))
    if now < target_dt:
        return {"processed": 0, "reason": "not yet due"}

    # Fire. Build messages for non-submitters of THIS week.
    messages = bm.build_reminder_messages(week_str, parish=None)
    if not messages:
        v14.save_reminder_config({
            "last_run": db._now_iso(),
            "last_run_week": week_str,
        })
        return {"processed": 0, "reason": "no non-submitters"}

    res = bm.send_reminders_now(
        messages,
        sent_by="system",
        sent_by_name="Reminder Scheduler",
        week_date=week_str, parish="",
    )
    v14.save_reminder_config({
        "last_run": db._now_iso(),
        "last_run_week": week_str,
    })
    return {"processed": res.get("total", 0),
            "sent": res.get("sent", 0),
            "failed": res.get("failed", 0)}


def process_weekly_reset():
    """V1.16 — Auto-finalize the week that just ended, so the new week
    starts at zero (each church submits fresh offerings for the new
    week_date). Runs every 5 minutes; only fires when the configured
    finalize day/time has been crossed AND we haven't already finalized
    that week.

    Finalizing flips `finalized=True` on every offering row for the
    ended week (read-only lock — history is never deleted). The new
    week's Monday is the boundary: offerings with the new week_date
    start at zero automatically (no carry-over).
    """
    try:
        import db_v14 as v14
    except Exception as e:
        return {"processed": 0, "reason": f"import error: {e}"}

    cfg = v14.load_weekly_reset_config()
    if not cfg.get("enabled"):
        return {"processed": 0, "reason": "weekly reset disabled"}

    now = datetime.now()
    today = now.date()
    # The week that should be finalized = the most recent Monday that is
    # at least `grace_days` old. grace_days=6 → finalize the week whose
    # Monday was 6+ days ago (i.e. last week, on Sunday).
    grace = int(cfg.get("grace_days", 6))
    finalize_day = int(cfg.get("finalize_day_of_week", 6))
    # Target datetime = today's week-Monday shifted back one week, plus
    # the configured hour/minute. (We finalize the PREVIOUS week, not
    # the current one.)
    this_monday = today - timedelta(days=today.weekday())
    target_week_monday = this_monday - timedelta(days=7)
    target_dt = datetime.combine(target_week_monday, datetime.min.time()).replace(
        hour=int(cfg.get("hour", 23)), minute=int(cfg.get("minute", 0)))
    # Shift the target by grace_days so the week fully elapses first.
    target_dt = target_dt + timedelta(days=grace)
    week_str = target_week_monday.isoformat()

    if now < target_dt:
        return {"processed": 0, "reason": "not yet due"}

    # Already finalized this week? Skip.
    if cfg.get("last_run_week") == week_str:
        return {"processed": 0, "reason": "already finalized this week"}

    # Also bail if v14.is_week_finalized already reports True (safety).
    if v14.is_week_finalized(week_str):
        v14.save_weekly_reset_config({
            "last_run": db._now_iso(),
            "last_run_week": week_str,
        })
        return {"processed": 0, "reason": "week already finalized"}

    res = v14.finalize_week(
        week_str,
        finalized_by="system",
        finalized_by_name="Weekly Reset Scheduler",
        trigger="auto",
    )
    v14.save_weekly_reset_config({
        "last_run": db._now_iso(),
        "last_run_week": week_str,
    })
    return {"processed": res.get("offering_count", 0),
            "week_date": week_str,
            "church_count": res.get("church_count", 0)}


# ------------------------------------------------------------------
# Scheduler lifecycle
# ------------------------------------------------------------------
def start():
    """Start the background jobs. Safe to call once per process."""
    global _scheduler
    if not _HAS_APS:
        # No APScheduler — fall back to a simple timer thread so the
        # queue still drains in environments without the dependency.
        db._scheduler_state["running"] = True
        db._scheduler_state["started_at"] = db._now_iso()
        _start_fallback_loop()
        return False
    with _lock:
        if _scheduler is not None:
            return True
        s = BackgroundScheduler(daemon=True)
        s.add_job(process_queue, "interval", minutes=2, id="queue",
                  max_instances=1, coalesce=True)
        # Weekly report: every Monday 08:00 by default.
        settings = db.load_system_settings()
        day = (settings.get("weekly_email_day") or "mon").lower()[:3]
        hour = int(settings.get("weekly_email_hour", 8))
        try:
            s.add_job(send_weekly_reports, "cron", day_of_week=day,
                      hour=hour, minute=0, id="weekly",
                      max_instances=1, coalesce=True)
        except Exception:
            s.add_job(send_weekly_reports, "cron", day_of_week="mon",
                      hour=8, minute=0, id="weekly", max_instances=1,
                      coalesce=True)
        # V1.14: Thank-you SMS auto-send queue — every 2 minutes, drain
        # dry_run/queued thank-you rows when auto_send_enabled + live gateway.
        s.add_job(process_thank_you_queue, "interval", minutes=2,
                  id="thank_you_auto", max_instances=1, coalesce=True)
        # V1.14: Scheduled bulk sends — every 1 minute, fire batches whose
        # scheduled_at has arrived. 1-minute cadence = scheduled sends fire
        # within ~60s of their due time (the "kwihutisha gahunda bitewe na
        # scheduled time" requirement).
        s.add_job(process_scheduled_bulk_sends, "interval", minutes=1,
                  id="scheduled_bulk", max_instances=1, coalesce=True)
        # V1.14: Reminder auto-send — every 5 minutes, check if the
        # configured day/time slot has been crossed this week and fire.
        s.add_job(process_reminders, "interval", minutes=5,
                  id="reminders", max_instances=1, coalesce=True)
        # V1.16: Weekly offerings reset — every 5 minutes, check if the
        # configured finalize day/time has been crossed and finalize the
        # ended week (locks it read-only; new week starts at zero).
        s.add_job(process_weekly_reset, "interval", minutes=5,
                  id="weekly_reset", max_instances=1, coalesce=True)
        s.start()
        _scheduler = s
        db._scheduler_state["running"] = True
        db._scheduler_state["started_at"] = db._now_iso()
        return True


def _start_fallback_loop():
    """Tiny timer thread when APScheduler is unavailable."""
    def _loop():
        import time
        last_bulk = 0
        last_reminder = 0
        last_weekly_reset = 0
        while db._scheduler_state.get("running"):
            try:
                process_queue()
            except Exception:
                pass
            try:
                process_thank_you_queue()
            except Exception:
                pass
            now = time.time()
            # 60s cadence for scheduled bulk sends.
            if now - last_bulk >= 60:
                try:
                    process_scheduled_bulk_sends()
                except Exception:
                    pass
                last_bulk = now
            # 300s cadence for reminders + weekly reset.
            if now - last_reminder >= 300:
                try:
                    process_reminders()
                except Exception:
                    pass
                last_reminder = now
            if now - last_weekly_reset >= 300:
                try:
                    process_weekly_reset()
                except Exception:
                    pass
                last_weekly_reset = now
            time.sleep(30)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()


def shutdown():
    global _scheduler
    db._scheduler_state["running"] = False
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None


if __name__ == "__main__":
    # Manual one-shot: drain the queue now.
    print(process_queue())
