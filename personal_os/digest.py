"""Tages-/Wochen-Digest: der ADHS-freundliche Ueberblick, damit nichts untergeht."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

_WEEKDAY_DE = [
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
]
_MONTH_DE = [
    "Januar",
    "Februar",
    "Maerz",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]


def _fmt_day(iso: Optional[str]) -> str:
    if not iso:
        return "-"
    try:
        d = datetime.fromisoformat(iso[:10])
        return f"{_WEEKDAY_DE[d.weekday()][:3]}, {d.day}. {_MONTH_DE[d.month - 1]}"
    except ValueError:
        return iso


def build_digest(core, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Sammelt alle relevanten offenen Dinge fuer den heutigen Tag."""
    now = now or datetime.now()
    cfg = core.config.adhd
    today = now.date().isoformat()
    horizon = (now + timedelta(days=3)).date().isoformat()
    cap = cfg.max_items_per_section
    recent_since = (now - timedelta(hours=24)).isoformat(timespec="seconds")

    open_loops = core.loops.list("open", include_snoozed_until=today)
    overdue = [lp for lp in open_loops if lp.get("due") and lp["due"] < today]
    due_today = [lp for lp in open_loops if lp.get("due") == today]
    due_soon = [
        lp for lp in open_loops if lp.get("due") and today < lp["due"] <= horizon
    ]
    stale = core.loops.stale(now)
    pending_delegations = core.store.list_delegations(status=None)
    pending_delegations = [
        d for d in pending_delegations if d["status"] in ("pending", "running")
    ]
    recent = core.store.list_items(since=recent_since, limit=50)

    top = core.loops.top_thing(now) if cfg.top_thing else None

    return {
        "date": today,
        "top_thing": top,
        "overdue": sorted(overdue, key=lambda lp: lp["due"])[:cap],
        "due_today": sorted(due_today, key=lambda lp: -lp.get("priority", 1))[:cap],
        "due_soon": sorted(due_soon, key=lambda lp: lp["due"])[:cap],
        "stale": sorted(stale, key=lambda lp: lp.get("updated_at", ""))[:cap],
        "pending_delegations": pending_delegations[:cap],
        "recent_items": recent[:cap],
        "counts": {
            "open_loops": len(open_loops),
            "overdue": len(overdue),
            "stale": len(stale),
            "pending_delegations": len(pending_delegations),
            "recent_items_24h": core.store.count_items(since=recent_since),
        },
    }


def build_weekly(core, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Woechentliche Review: was lief, was ist haengen geblieben."""
    now = now or datetime.now()
    week_ago = (now - timedelta(days=7)).isoformat(timespec="seconds")
    done = core.store.list_loops(status="done")
    done_week = [lp for lp in done if (lp.get("done_at") or "") >= week_ago]
    delegations = core.store.list_delegations(status="done")
    delegations_week = [
        d for d in delegations if (d.get("updated_at") or "") >= week_ago
    ]
    return {
        "week_start": (now - timedelta(days=now.weekday())).date().isoformat(),
        "done_loops_week": done_week,
        "done_delegations_week": delegations_week,
        "open_loops": core.loops.list("open"),
        "stale": core.loops.stale(now),
        "memory_stats": core.memory.stats(),
        "items_week": core.store.count_items(since=week_ago),
    }


def _render_loop(lp: Dict[str, Any]) -> str:
    tags = " ".join(f"#{t}" for t in lp.get("tags", []))
    due = f" (fällig {_fmt_day(lp.get('due'))})" if lp.get("due") else ""
    nxt = f" → nächstes: {lp['next_action']}" if lp.get("next_action") else ""
    prio = {3: "‼️", 2: "⚠️", 1: ""}[lp.get("priority", 1)]
    return f"- {prio} **{lp['title']}**{due} {tags}{nxt}".rstrip()


def render_digest(digest: Dict[str, Any], profile_name: str = "Ich") -> str:
    """Digest als lesbaren Markdown-Text (deutsch)."""
    date_str = _fmt_day(digest["date"])
    lines = [f"# 🌅 Tages-Digest für {profile_name} – {date_str}", ""]

    top = digest.get("top_thing")
    if top:
        lines += ["## 🎯 Das wichtigste Ding heute", _render_loop(top), ""]

    if digest["overdue"]:
        lines += (
            ["## 🚨 Überfällig"] + [_render_loop(lp) for lp in digest["overdue"]] + [""]
        )
    if digest["due_today"]:
        lines += (
            ["## ⏰ Heute fällig"]
            + [_render_loop(lp) for lp in digest["due_today"]]
            + [""]
        )
    if digest["due_soon"]:
        lines += (
            ["## 📥 Demnächst (3 Tage)"]
            + [_render_loop(lp) for lp in digest["due_soon"]]
            + [""]
        )
    if digest["stale"]:
        lines += (
            ["## 👀 Lange nicht angefasst – kurz checken oder schließen?"]
            + [_render_loop(lp) for lp in digest["stale"]]
            + [""]
        )

    pend = digest.get("pending_delegations", [])
    if pend:
        lines += ["## 🤖 Delegationen in Arbeit"]
        for d in pend:
            lines.append(f"- [{d['status']}] {d['agent']}: {d['instruction'][:80]}")
        lines.append("")

    recent = digest.get("recent_items", [])
    if recent:
        n24 = digest["counts"]["recent_items_24h"]
        lines += [f"## 📚 Neu im Wissensspeicher ({n24} in 24h)"]
        for item in recent:
            snippet = item["content"].replace("\n", " ")[:90]
            src = f" ({item['source']})" if item.get("source") else ""
            lines.append(f"- `{item['kind']}`{src}: {snippet}…")
        lines.append("")

    c = digest["counts"]
    lines += [
        "---",
        f"Offen: {c['open_loops']} Loops · {c['overdue']} überfällig · "
        f"{c['stale']} stale · {c['pending_delegations']} Delegationen",
    ]
    return "\n".join(lines)


def render_weekly(weekly: Dict[str, Any], profile_name: str = "Ich") -> str:
    """Wochen-Review als Markdown-Text (deutsch)."""
    lines = [
        f"# 📊 Wochen-Review für {profile_name} (ab {_fmt_day(weekly['week_start'])})",
        "",
    ]
    lines.append(
        f"## ✅ Erledigt diese Woche: {len(weekly['done_loops_week'])} Loops, "
        f"{len(weekly['done_delegations_week'])} Delegationen"
    )
    for lp in weekly["done_loops_week"][:10]:
        lines.append(f"- ~~{lp['title']}~~")
    lines.append("")
    lines.append(
        f"## 📥 Weiterhin offen: {len(weekly['open_loops'])} Loops, "
        f"davon {len(weekly['stale'])} stale"
    )
    for lp in weekly["stale"][:10]:
        lines.append(f"- {lp['title']} (seit {_fmt_day(lp.get('updated_at'))})")
    lines.append("")
    ms = weekly["memory_stats"]
    lines.append(
        f"## 🧠 Wissensspeicher: {ms['items']} Einträge · {ms['entities']} Entitäten · "
        f"{ms['relationships']} Relationen · {weekly['items_week']} neu diese Woche"
    )
    return "\n".join(lines)
