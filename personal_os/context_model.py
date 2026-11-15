"""Kontextmodell (WP1): typtisierte Objekte mit Provenienz, Status und Scopes.

Objekttypen: person, area, project, task, commitment, decision, routine, goal,
event. Status-Lebenszyklus: mentioned -> intent -> committed -> done (sowie
rejected). Jede Aenderung landet in ``history``. Widerspruechliche Eintraege zum
selben Objekt werden NICHT ueberschrieben, sondern als ``conflicts_with``-Link
 markiert; erst ``resolve_conflict`` setzt ``superseded_by`` (Nachweis bleibt).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import ContextObject, new_id, utcnow
from .scopes import PRIVATE, validate_scope

OBJECT_TYPES = (
    "person",
    "area",
    "project",
    "task",
    "commitment",
    "decision",
    "routine",
    "goal",
    "event",
)

STATUSES = ("mentioned", "intent", "committed", "done", "rejected")

TRANSITIONS = {
    "mentioned": {"intent", "committed", "done", "rejected"},
    "intent": {"committed", "done", "rejected"},
    "committed": {"done", "rejected"},
    "done": set(),
    "rejected": set(),
}


class ContextModel:
    """Verwaltet Kontext-Objekte und deren Links in SQLite."""

    def __init__(self, store):
        self.store = store

    @staticmethod
    def _norm(title: str) -> str:
        return " ".join(title.lower().split())

    def add_object(
        self,
        type_: str,
        title: str,
        scope: str = PRIVATE,
        status: str = "mentioned",
        confidence: float = 1.0,
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
        source: str = "",
        source_item_id: Optional[str] = None,
        created_by: str = "owner",
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Objekt anlegen; bei gleichem (type, title) wird ein Konflikt vermerkt."""
        if type_ not in OBJECT_TYPES:
            raise ValueError(
                f"Unbekannter Objekttyp {type_!r}; erlaubt: {OBJECT_TYPES}"
            )
        if status not in STATUSES:
            raise ValueError(f"Unbekannter Status {status!r}; erlaubt: {STATUSES}")
        scope = validate_scope(scope)
        now = utcnow()
        obj = ContextObject(
            id=new_id(),
            type=type_,
            title=title,
            scope=scope,
            status=status,
            confidence=confidence,
            valid_from=valid_from or now,
            valid_until=valid_until,
            source=source,
            source_item_id=source_item_id,
            created_by=created_by,
            history=[{"from": None, "to": status, "at": now, "by": created_by}],
            created_at=now,
            updated_at=now,
            meta=meta or {},
        )
        result = obj.to_dict()
        conflict = self._find_conflict(type_, title, exclude_id=obj.id)
        if conflict:
            self.link(obj.id, conflict["id"], "conflicts_with", provenance=source)
            result["conflict_with"] = conflict["id"]
            obj.meta["conflict_with"] = conflict["id"]
        self.store.add_context_object(obj.to_dict())
        return result

    def _find_conflict(
        self, type_: str, title: str, exclude_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        for obj in self.store.list_context_objects(
            type_=type_, include_superseded=True
        ):
            if obj["id"] == exclude_id:
                continue
            if self._norm(obj["title"]) == self._norm(title):
                return obj
        return None

    def get(self, id_: str) -> Optional[Dict[str, Any]]:
        obj = self.store.get_context_object(id_)
        return self._surface_conflict(obj)

    @staticmethod
    def _surface_conflict(obj: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if obj and (obj.get("meta") or {}).get("conflict_with"):
            obj["conflict_with"] = obj["meta"]["conflict_with"]
        return obj

    def list(
        self,
        type_: Optional[str] = None,
        scope: Optional[str] = None,
        status: Optional[str] = None,
        include_superseded: bool = False,
        include_expired: bool = False,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        objs = self.store.list_context_objects(
            type_=type_,
            scope=scope,
            status=status,
            include_superseded=include_superseded,
            limit=limit,
        )
        if not include_expired:
            today = utcnow()[:10]
            objs = [
                o
                for o in objs
                if not o.get("valid_until") or str(o["valid_until"])[:10] >= today
            ]
        return [self._surface_conflict(o) for o in objs]

    def transition(
        self, id_: str, new_status: str, by: str = "owner"
    ) -> Dict[str, Any]:
        """Status-Wechsel mit Pruefung; ungueltige Uebergaenge werden abgelehnt."""
        obj = self.store.get_context_object(id_)
        if not obj:
            raise KeyError(f"Kontext-Objekt {id_} nicht gefunden")
        if new_status not in STATUSES:
            raise ValueError(f"Unbekannter Status {new_status!r}")
        current = obj["status"]
        if new_status == current:
            return obj
        if new_status not in TRANSITIONS.get(current, set()):
            raise ValueError(
                f"Ungueltiger Uebergang {current} -> {new_status} fuer Objekt {id_}"
            )
        now = utcnow()
        history = list(obj.get("history") or [])
        history.append({"from": current, "to": new_status, "at": now, "by": by})
        self.store.update_context_object(
            id_, {"status": new_status, "history": history, "updated_at": now}
        )
        return self.store.get_context_object(id_)

    def link(
        self, source_id: str, target_id: str, relation: str, provenance: str = ""
    ) -> Dict[str, Any]:
        """Beziehung zwischen zwei Objekten mit Provenienz anlegen."""
        link = {
            "id": new_id(),
            "source_id": source_id,
            "target_id": target_id,
            "relation": relation,
            "provenance": provenance,
            "created_at": utcnow(),
            "meta": {},
        }
        self.store.add_object_link(link)
        return link

    def links(self, object_id: str) -> List[Dict[str, Any]]:
        return self.store.list_links(object_id)

    def conflicts(self, id_: str) -> List[Dict[str, Any]]:
        """Alle Objekte, die mit diesem Objekt in Widerspruch markiert sind."""
        out = []
        for link in self.store.list_links(id_):
            if link["relation"] != "conflicts_with":
                continue
            other = link["target_id"] if link["source_id"] == id_ else link["source_id"]
            obj = self.store.get_context_object(other)
            if obj:
                out.append(obj)
        return out

    def resolve_conflict(self, id_: str, keep_id: str) -> Dict[str, Any]:
        """Widerspruch aufloesen: anderes Objekt wird superseded (nicht geloescht)."""
        loser = self.store.get_context_object(id_)
        keeper = self.store.get_context_object(keep_id)
        if not loser or not keeper:
            raise KeyError("Konflikt-Objekt nicht gefunden")
        if loser.get("superseded_by"):
            raise ValueError(f"Objekt {id_} ist bereits superseded")
        self.store.update_context_object(
            id_, {"superseded_by": keep_id, "updated_at": utcnow()}
        )
        return self.store.get_context_object(id_)

    def link_item(
        self,
        item_id: str,
        type_: str = "task",
        title: Optional[str] = None,
        status: str = "mentioned",
    ) -> Dict[str, Any]:
        """Wissens-Eintrag mit einem Kontext-Objekt verknuepfen (Provenienz)."""
        item = self.store.get_item(item_id)
        if not item:
            raise KeyError(f"Item {item_id} nicht gefunden")
        return self.add_object(
            type_=type_,
            title=title or item["content"][:80],
            scope=item.get("scope", PRIVATE),
            status=status,
            source=item.get("source", ""),
            source_item_id=item_id,
            created_by="owner",
        )
