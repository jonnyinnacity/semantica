"""Scopes (WP1): konsequente Trennung privater und beruflicher Daten.

Jeder Eintrag und jedes Kontext-Objekt traegt einen Scope (``private`` oder
``work``). Abfragen mit einem Scope liefern NIEMALS Daten eines anderen Scopes
(beruflicher Kontext sieht keine privaten Daten). Fuer externe Modellaufrufe
gibt es ``redact_for_external``: private Inhalte werden standardmaessig entfernt.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

PRIVATE = "private"
WORK = "work"
SCOPES = (PRIVATE, WORK)

EXTERNAL_ITEM_FIELDS = ("id", "kind", "scope", "tags", "source", "created_at")


def validate_scope(scope: Optional[str], default: str = PRIVATE) -> str:
    """Scope pruefen; unbekannte Scopes werden abgelehnt (nie raten)."""
    scope = (scope or default) or default
    if scope not in SCOPES:
        raise ValueError(f"Unbekannter Scope {scope!r}; erlaubt: {SCOPES}")
    return scope


def redact_item(item: Dict[str, Any], allow_private: bool = False) -> Dict[str, Any]:
    """Item fuer externe Uebertragung aufbereiten: private Inhalte werden maskiert."""
    scope = item.get("scope", PRIVATE)
    if scope == PRIVATE and not allow_private:
        return {
            "id": item.get("id"),
            "kind": item.get("kind"),
            "scope": PRIVATE,
            "redacted": True,
        }
    out = {k: item.get(k) for k in EXTERNAL_ITEM_FIELDS}
    out["content"] = item.get("content", "")
    return out


def redact_object(obj: Dict[str, Any], allow_private: bool = False) -> Dict[str, Any]:
    """Kontext-Objekt fuer externe Uebertragung aufbereiten."""
    scope = obj.get("scope", PRIVATE)
    if scope == PRIVATE and not allow_private:
        return {
            "id": obj.get("id"),
            "type": obj.get("type"),
            "scope": PRIVATE,
            "redacted": True,
        }
    return copy.deepcopy(obj)


def redact_for_external(data: Any, allow_private: bool = False) -> Any:
    """Rekursive Redaction einer beliebigen Payload (Items, Objekte, Listen, Dicts).

    Private Eintraege/Objekte verlieren Inhalt und Titel; Struktur und ID bleiben
    als Nachweis erhalten. ``allow_private=True`` nur nach ausdruecklicher Freigabe.
    """
    if isinstance(data, dict):
        eff_scope = data.get("scope")
        if eff_scope is None and isinstance(data.get("meta"), dict):
            eff_scope = data["meta"].get("scope")
        if eff_scope == PRIVATE and not allow_private:
            stub = {"id": data.get("id"), "scope": PRIVATE, "redacted": True}
            if "type" in data:
                stub["type"] = data.get("type")
            return stub
        if "content" in data and "scope" in data:
            return redact_item(data, allow_private=allow_private)
        if "title" in data and "type" in data and "status" in data:
            return redact_object(data, allow_private=allow_private)
        return {
            k: redact_for_external(v, allow_private=allow_private)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [redact_for_external(v, allow_private=allow_private) for v in data]
    return data


def filter_by_scope(
    items: List[Dict[str, Any]], scope: Optional[str]
) -> List[Dict[str, Any]]:
    """Nur Items des gegebenen Scopes; ``scope=None`` ist die Owner-Ansicht (alle)."""
    if scope is None:
        return items
    return [i for i in items if i.get("scope", PRIVATE) == scope]
