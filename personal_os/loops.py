"""Open Loops: Aufgaben, Projekte und Versprechen, die am Laufen bleiben.

ADHS-freundlich: klare naechste Aktion, Faelligkeit, Snooze, Wiederholung
und Stale-Erkennung (Loops, die laenger nicht angefasst wurden).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .extract import next_due, parse_loop
from .models import Loop, new_id, utcnow
from .scopes import validate_scope


class LoopsManager:
    """Verwaltet Loops in der Persistenz."""

    def __init__(self, store, config):
        self.store = store
        self.config = config

    def add(
        self,
        title: str,
        due: Optional[str] = None,
        repeat: Optional[str] = None,
        priority: int = 1,
        next_action: str = "",
        tags: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
        scope: str = "private",
    ) -> Dict[str, Any]:
        now = utcnow()
        loop = Loop(
            id=new_id(),
            title=title,
            status="open",
            scope=validate_scope(scope),
            priority=priority,
            due=due,
            repeat=repeat,
            next_action=next_action,
            tags=tags or [],
            created_at=now,
            updated_at=now,
            meta=meta or {},
        )
        self.store.add_loop(loop.to_dict())
        return loop.to_dict()

    def add_from_text(
        self, text: str, now: Optional[datetime] = None, scope: str = "private"
    ) -> Dict[str, Any]:
        parsed = parse_loop(text, now)
        return self.add(**parsed, scope=scope)

    def get(self, id_: str) -> Optional[Dict[str, Any]]:
        return self.store.get_loop(id_)

    def list(
        self,
        status: str = "open",
        include_snoozed_until: Optional[str] = None,
        scope: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        loops = self.store.list_loops(status=status, scope=scope, limit=limit)
        if status == "open" and include_snoozed_until:
            loops = [
                lp
                for lp in loops
                if not lp.get("snooze_until")
                or lp["snooze_until"] <= include_snoozed_until
            ]
        return loops

    def complete(
        self, id_: str, now: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """Loop abschliessen; bei Wiederholung neuen offenen Loop anlegen."""
        loop = self.store.get_loop(id_)
        if not loop:
            return None
        now = now or datetime.now()
        ts = utcnow()
        self.store.update_loop(
            id_,
            {"status": "done", "done_at": ts, "updated_at": ts, "snooze_until": None},
        )
        if loop.get("repeat") and loop.get("due"):
            new_due = next_due(loop["due"], loop["repeat"], now)
            self.add(
                title=loop["title"],
                due=new_due,
                repeat=loop["repeat"],
                priority=loop.get("priority", 1),
                next_action=loop.get("next_action", ""),
                tags=loop.get("tags", []),
                meta={**loop.get("meta", {}), "recurring_from": id_},
            )
        return self.store.get_loop(id_)

    def snooze(self, id_: str, days: int = 1) -> Optional[Dict[str, Any]]:
        loop = self.store.get_loop(id_)
        if not loop:
            return None
        until = (datetime.now() + timedelta(days=days)).date().isoformat()
        self.store.update_loop(id_, {"snooze_until": until, "updated_at": utcnow()})
        return self.store.get_loop(id_)

    def reopen(self, id_: str) -> Optional[Dict[str, Any]]:
        loop = self.store.get_loop(id_)
        if not loop:
            return None
        self.store.update_loop(
            id_, {"status": "open", "done_at": None, "updated_at": utcnow()}
        )
        return self.store.get_loop(id_)

    def due_on(self, day_iso: str) -> List[Dict[str, Any]]:
        return [lp for lp in self.list("open") if lp.get("due") == day_iso]

    def overdue(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        today = (now or datetime.now()).date().isoformat()
        return [lp for lp in self.list("open") if lp.get("due") and lp["due"] < today]

    def due_soon(
        self, days: int = 3, now: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        now = now or datetime.now()
        today = now.date().isoformat()
        horizon = (now + timedelta(days=days)).date().isoformat()
        return [
            lp
            for lp in self.list("open")
            if lp.get("due") and today <= lp["due"] <= horizon
        ]

    def stale(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Offene Loops ohne Faelligkeit, die lange nicht aktualisiert wurden."""
        now = now or datetime.now()
        threshold = (
            (now - timedelta(days=self.config.adhd.stale_days)).date().isoformat()
        )
        out = []
        for lp in self.list("open"):
            if lp.get("due"):
                continue
            updated = (lp.get("updated_at") or lp.get("created_at") or "")[:10]
            if updated and updated < threshold:
                out.append(lp)
        return out

    def top_thing(self, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """Der wichtigste offene Loop (Prioritaet, dann Faelligkeit)."""
        loops = self.list("open")
        if not loops:
            return None
        loops.sort(
            key=lambda lp: (-lp.get("priority", 1), lp.get("due") or "9999-12-31")
        )
        return loops[0]
