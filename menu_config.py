"""
menu_config.py — Modular per-role menu registry (V1.12).

The sidebar menu is NO LONGER hardcoded in the template. It is driven by
this single config so that:

  * each "component" (page) is declared ONCE with its icon, label and
    optional badge counter (single source of truth);
  * each role's menu is an explicit ordered list of page keys (easy to
    read, easy to reorder, easy to add/remove one item);
  * the server personalises the menu (church name, leader name, parish
    name) and ships it via /api/auth/session, so the template just
    renders `this.menu`.

== How to add a new component (modular development) ==
1. Add the page template section in templates/index.html
   (`x-if="page==='my_new_page'"`).
2. Add the routes in app.py (behind the right role decorator).
3. Register it here:
   - add an entry to COMPONENTS:  "my_new_page": {"icon":"bx-...", "label":"..."}
   - add "my_new_page" to the MENU_BY_ROLE lists of every role that
     should see it.
That is the whole change — the sidebar picks it up automatically.

== Label overrides ==
Most items use the COMPONENTS label. A role may override a label by
writing a tuple ("page", "Custom label") in its MENU_BY_ROLE list. The
override supports {church_name} / {leader_name} / {parish_name}
placeholders, filled by menu_for_role() from the user's context.
"""

# ------------------------------------------------------------------
# Component registry — single source of truth for icon + default label
# + optional badge (JS counter property on the Alpine component).
# badge=None means no badge. Otherwise it is the property name the
# template reads (e.g. "pendingServiceCount").
# ------------------------------------------------------------------
COMPONENTS = {
    # ---- shared ----
    "dashboard":         {"icon": "bx-grid-alt",            "label": "Dashboard",                       "badge": None},
    "profile":           {"icon": "bx-user",                "label": "Umwirondoro wanjye",              "badge": None},
    "signature":         {"icon": "bx-pen",                 "label": "Umukono wanjye",                  "badge": None},
    "schedules":         {"icon": "bx-calendar-event",      "label": "Gahunda",                         "badge": None},

    # ---- parish level ----
    "churches":          {"icon": "bx-church",              "label": "Amatorero",                       "badge": None},
    "pastors":           {"icon": "bx-user-pin",            "label": "Abashumba n'Abayobozi",           "badge": None},
    "members":           {"icon": "bx-group",               "label": "Abakristo bose",                  "badge": None},
    "ministries":        {"icon": "bx-network-chart",       "label": "Ministeur",                       "badge": None},
    "offerings":         {"icon": "bx-money",               "label": "Amaturo yose",                    "badge": None},
    "proof_audit":       {"icon": "bx-file-find",           "label": "Ibyemezo (Proof)",                "badge": None},
    "weekly_reset":      {"icon": "bx-reset",               "label": "Reset y'icyumweru",               "badge": None},
    "budgets":           {"icon": "bx-wallet-alt",          "label": "Budget z'amatorero",              "badge": None},
    "rankings":          {"icon": "bx-trophy",              "label": "Uruhare (Ranking)",               "badge": None},
    "reports":           {"icon": "bx-file",                "label": "Raporo (PDF/Excel)",              "badge": None},
    "service_requests":  {"icon": "bx-user-plus",           "label": "Gusaba kwakira",                  "badge": "pendingServiceCount"},
    "death_reports":     {"icon": "bx-cross",               "label": "Abitabye Imana",                  "badge": None},
    "sms":               {"icon": "bx-message-rounded-dots","label": "Tangaza (SMS)",                   "badge": None},
    "pending_users":     {"icon": "bx-user-check",          "label": "Konti z'emeza",                   "badge": "pendingUsersCount"},
    "settings":          {"icon": "bx-cog",                 "label": "Igenamiterere",                   "badge": None},
    "monitoring":        {"icon": "bx-pulse",               "label": "Isuzuma sisitemu",                "badge": "_systemHealthPending"},
    "message_queue":     {"icon": "bx-mail-send",           "label": "Ubutumwa bukuriye",               "badge": "_queuePending"},
    "automation":        {"icon": "bx-bolt-circle",         "label": "Auto mode",                       "badge": None},
    "assets":            {"icon": "bx-briefcase-alt-2",     "label": "Imitungo y'amatorero",            "badge": None},
    "zones":             {"icon": "bx-map-pin",             "label": "Ama zone",                        "badge": None},
    "activity_log":      {"icon": "bx-activity",            "label": "Ibyabaye (monitoring)",           "badge": None},
    "visitors":          {"icon": "bx-user-voice",          "label": "Abashyitsi",                      "badge": None},
    "discipline":        {"icon": "bx-shield-quarter",      "label": "Abafatiwe ibihano",               "badge": None},
    "delegations":       {"icon": "bx-transfer-alt",        "label": "Delegation",                      "badge": None},
    "parish_ministries": {"icon": "bx-network-chart",       "label": "Ama ministeur yose",              "badge": None},
    "documents":         {"icon": "bx-file-blank",          "label": "Inkete z'emeza",                  "badge": "pendingDocsCount"},

    # ---- church level ----
    "my_members":        {"icon": "bx-group",               "label": "Abakristo banjye",                "badge": None},
    "record_offering":   {"icon": "bx-money",               "label": "Andika amaturo",                  "badge": None},
    "my_rank":           {"icon": "bx-trophy",              "label": "Urwego rw'itorero",               "badge": None},
    "my_reports":        {"icon": "bx-file",                "label": "Raporo zanjye",                   "badge": None},

    # ---- ministry level ----
    "my_ministry":           {"icon": "bx-network-chart",   "label": "Ministeur yanjye",                "badge": None},
    "my_ministry_members":   {"icon": "bx-group",           "label": "Abakristo b'o kwita",             "badge": None},

    # ---- V1.13 — per-role new sections ----
    # Own settings (name/phone/email/photo) for every role; reflects
    # immediately on the page after a save.
    "my_settings":           {"icon": "bx-user-circle",     "label": "Umwirondoro n'amakuru yanjye",    "badge": None},
    # Member deletion requests — zone/ministry ask, church approves.
    "deletion_requests":     {"icon": "bx-user-x",          "label": "Gusaba gukuramo umukristo",       "badge": "pendingDeletionCount"},
    # Manager proposed writes awaiting parish approval.
    "manager_changes":       {"icon": "bx-task",            "label": "Ibyasabwe n'umuyobozi",           "badge": "pendingChangeCount"},
    # Parish-wide reception overview (requests/approved/baptized).
    "reception_overview":    {"icon": "bx-user-check",      "label": "Abakristo b'emejwe",              "badge": None},
    # Tracar SMS gateway config + test.
    "sms_gateway":           {"icon": "bx-message-alt",     "label": "SMS Gateway (Tracar)",            "badge": None},
    # Thank-you SMS log + send per church per week.
    "thank_you_sms":         {"icon": "bx-heart",           "label": "Ubutumwa bwo gushimira",          "badge": None},
    # V1.14: Bulk thank-you SMS to ALL submitters at once (auto/manual/
    # scheduled) + reminder SMS to non-submitters with a configurable
    # auto-fire schedule.
    "bulk_send":             {"icon": "bx-broadcast",       "label": "Ubutumwa bwa bundle",             "badge": None},
    # Schedule requests awaiting approve/decline (church view of
    # minister/zone proposals).
    "schedule_requests":     {"icon": "bx-calendar-exclamation", "label": "Gahunda zasabwe",           "badge": "pendingScheduleCount"},
}

# ------------------------------------------------------------------
# Per-role ordered menus — V1.15 grouped format.
#
# Each role's menu is a list of SECTION dicts:
#   {"title": "Section label", "items": [ "page", ("page","Label"), ... ]}
# The section title renders as a non-clickable divider in the sidebar
# (small caps, muted), and its items render below it. This declutters
# the previously flat 20-30 item list into ~5-8 named groups per role
# so each role sees its functions grouped by what they actually do.
#
# An item entry is either:
#   "page_key"                       -> uses COMPONENTS label
#   ("page_key", "Override label")   -> custom label (with {placeholders})
#
# Backward compat: a bare string/tuple at the top level (not inside a
# section dict) is treated as an item with no group — menu_for_role
# handles both shapes.
# ------------------------------------------------------------------
MENU_BY_ROLE = {
    # ================= PARISH PASTOR (head of all) =================
    "PARISH_PASTOR": [
        {"title": "Imiterere", "items": ["dashboard"]},
        {"title": "Amatorero n'Abayobozi", "items": [
            "churches", "pastors", "members", "ministries", "parish_ministries",
        ]},
        {"title": "Amaturo n'Imali", "items": [
            "offerings", "proof_audit", "budgets", "rankings", "weekly_reset",
        ]},
        {"title": "Abakristo n'Ubufatanye", "items": [
            "service_requests", "reception_overview", "death_reports",
            "visitors", "discipline",
        ]},
        {"title": "Ubutumwa (SMS)", "items": [
            "sms", "sms_gateway", "thank_you_sms", "bulk_send", "message_queue",
        ]},
        {"title": "Gahunda n'Imitungo", "items": [
            "schedules", "documents", "assets", "zones",
            "delegations", "activity_log",
        ]},
        {"title": "Raporo", "items": ["reports"]},
        {"title": "Sisitemu", "items": [
            "monitoring", "pending_users", "manager_changes",
            "settings", "my_settings",
        ]},
    ],

    # ================= PARISH MANAGER (subset, co-runs parish) ======
    "PARISH_MANAGER": [
        {"title": "Imiterere", "items": ["dashboard"]},
        {"title": "Amatorero", "items": [
            "churches", "pastors", "ministries", "parish_ministries",
        ]},
        {"title": "Amaturo n'Imali", "items": [
            "offerings", "proof_audit", "budgets", "rankings",
        ]},
        {"title": "Abakristo", "items": ["reception_overview", "visitors"]},
        {"title": "Ubutumwa n'Auto", "items": ["bulk_send", "message_queue", "automation"]},
        {"title": "Gahunda n'Imitungo", "items": [
            "schedules", "assets", "activity_log",
        ]},
        {"title": "Raporo", "items": ["reports"]},
        {"title": "Sisitemu", "items": [
            "manager_changes", "monitoring", "my_settings",
        ]},
    ],

    # ================= CHURCH PASTOR (local church leader) =========
    "CHURCH_PASTOR": [
        {"title": "Imiterere", "items": [
            ("dashboard", "Dashboard yanjye y'itorero rya {church_name}"),
        ]},
        {"title": "Itorero ryanjye", "items": [
            "my_members", "record_offering", "my_rank",
        ]},
        {"title": "Abakristo n'Ubufatanye", "items": [
            "service_requests", "deletion_requests", "death_reports",
            "visitors", "discipline",
        ]},
        {"title": "Gahunda", "items": [
            "schedules", "schedule_requests",
        ]},
        {"title": "Imitungo", "items": [
            "assets", "zones", "ministries", ("documents", "Inkete (emezwa)"),
        ]},
        {"title": "Raporo", "items": [
            ("my_reports", "Raporo zanjye"), ("activity_log", "Ibyabaye"),
        ]},
        {"title": "Konti n'Umwirondoro", "items": [
            "pending_users", "profile", "signature", "my_settings",
        ]},
    ],

    # ================= CHURCH FINANCE (ushinzwe imali w'itorero) ====
    "CHURCH_FINANCE": [
        {"title": "Imiterere", "items": [("dashboard", "Dashboard yanjye")]},
        {"title": "Amaturo", "items": ["record_offering", "my_rank"]},
        {"title": "Raporo", "items": ["my_reports"]},
        {"title": "Ibindi", "items": [
            ("assets", "Imitungo y'itorero"),
            ("visitors", "Abashyitsi b'icyumweru"),
        ]},
        {"title": "Konti n'Umwirondoro", "items": [
            "profile", "signature", "my_settings",
        ]},
    ],

    # ================= MINISTRY LEADER ==============================
    "MINISTRY_LEADER": [
        {"title": "Imiterere", "items": [("dashboard", "Dashboard yanjye")]},
        {"title": "Ministeur yanjye", "items": [
            "my_ministry", "my_ministry_members",
        ]},
        {"title": "Abakristo", "items": [
            ("service_requests", "Saba kwakira"), "deletion_requests",
        ]},
        {"title": "Gahunda", "items": ["schedules", "schedule_requests"]},
        {"title": "Raporo", "items": [("my_reports", "Raporo za ministeur")]},
        {"title": "Konti n'Umwirondoro", "items": ["signature", "my_settings"]},
    ],

    # ================= ZONE READER =================================
    "ZONE_READER": [
        {"title": "Imiterere", "items": [
            ("dashboard", "Dashboard yanjye — {church_name} / zone"),
        ]},
        {"title": "Zone yanjye", "items": [("my_members", "Abakristo b'iyi zone")]},
        {"title": "Abakristo", "items": [
            ("service_requests", "Saba kwakira"), "deletion_requests",
        ]},
        {"title": "Gahunda", "items": ["schedules", "schedule_requests"]},
        {"title": "Konti n'Umwirondoro", "items": ["signature", "my_settings"]},
    ],
}


def menu_for_role(role, ctx=None):
    """Return the personalised menu for a role.

    Args:
        role: user role string (e.g. "PARISH_PASTOR"). Unknown roles
              return an empty list (the template shows nothing).
        ctx:  dict with optional {church_name, leader_name, parish_name}
              used to fill label placeholders.

    Returns:
        list of {page, label, icon, badge, group} dicts, in order. `group`
        is the section title the item belongs to (or None for ungrouped
        items). `badge` is None or a string. Two special badge markers
        start with "_":
          "_queuePending"        -> template reads queueStats.pending
          "_systemHealthPending" -> template reads systemHealth.queue.pending
        The template knows how to render these.

    Handles both V1.15 grouped format (list of {"title","items"} dicts)
    and the legacy flat format (list of strings/tuples) for backward
    compatibility.
    """
    role = (role or "").upper()
    ctx = ctx or {}
    raw = MENU_BY_ROLE.get(role, [])
    out = []
    for entry in raw:
        # V1.15 grouped section: {"title": ..., "items": [...]}
        if isinstance(entry, dict) and "items" in entry:
            group_title = entry.get("title") or ""
            for sub in entry["items"]:
                item = _build_menu_item(sub, group_title, ctx)
                if item:
                    out.append(item)
        else:
            # Legacy flat entry (string or tuple) — no group.
            item = _build_menu_item(entry, None, ctx)
            if item:
                out.append(item)
    return out


def _build_menu_item(entry, group_title, ctx):
    """Build a single menu item dict from a string/tuple entry."""
    if isinstance(entry, tuple):
        page, label = entry[0], entry[1]
    else:
        page, label = entry, None
    comp = COMPONENTS.get(page)
    if not comp:
        return None
    final_label = label if label is not None else comp["label"]
    # Fill placeholders from context.
    try:
        final_label = final_label.format(
            church_name=ctx.get("church_name", "") or "",
            leader_name=ctx.get("leader_name", "") or "",
            parish_name=ctx.get("parish_name", "") or "",
        )
    except (KeyError, IndexError):
        pass
    return {
        "page": page,
        "label": final_label,
        "icon": comp["icon"],
        "badge": comp.get("badge"),
        "group": group_title,
    }


if __name__ == "__main__":
    # Quick self-check: print each role's menu.
    for r in ["PARISH_PASTOR", "PARISH_MANAGER", "CHURCH_PASTOR",
              "CHURCH_FINANCE", "MINISTRY_LEADER", "ZONE_READER"]:
        print(f"\n=== {r} ({len(MENU_BY_ROLE[r])} items) ===")
        for item in menu_for_role(r, {"church_name": "RUHANGO",
                                      "leader_name": "Pasteur Test"}):
            b = f"  [badge:{item['badge']}]" if item["badge"] else ""
            print(f"  {item['icon']:24s} {item['page']:20s} {item['label']}{b}")
