"""WP3: Commitment-Erkennung und -Verwaltung.

Deterministischer, offline arbeitender Detector auf Basis des WP1-Kontextmodells.
Unterscheidet Erwaehnung (mentioned), Absicht (intent), verbindliche Zusage
(committed), Erledigung (done) und Absage (rejected). Unklare Faelle werden nie
stillschweigend als verbindlich behandelt (niedrige Konfidenz + Status mentioned).

Regeln: Dedup gegen bestehende Verpflichtungen (gleicher Titel+Scope+Frist =>
Duplikat), bereits erledigte/verorfene werden nicht wieder geoeffnet, bei
widerspruechlichen Angaben greift die WP1-Konfliktlogik (conflicts_with).
Scopes werden 1:1 vom Quell-Item uebernommen (nie automatische Hochstufung).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .context_model import ContextModel
from .extract import parse_due
from .scopes import PRIVATE, validate_scope

DONE_MARKERS = (
    "habe ich schon",
    "habe ich bereits",
    "ich habe es",
    "ist erledigt",
    "schon erledigt",
    "bereits geschickt",
    "ist durch",
    "habe ich geschickt",
    "habe ich gemacht",
    "habe ich angerufen",
    "erledigt am",
)
REJECT_MARKERS = (
    "abgesagt",
    "fällt aus",
    "faellt aus",
    "nicht mehr nötig",
    "nicht mehr noetig",
    "vergiss es",
    "lass es",
    "brauchen wir nicht mehr",
)
REQUEST_RE = re.compile(
    r"(?:kannst du|könntest du|koenntest du|kannst du mir|bitte)\s+(.+?)(?:\?|!|\.|$)",
    re.IGNORECASE,
)
OWN_RE = re.compile(
    r"ich\s+(schicke|liefere|erledige|kümmere|kuemmere|rufe|nehme|kläre|klaere|"
    r"mache|besorge|prüfe|pruefe|gebe|reiche)\s+(.+?)(?:\s+(?:bis|am|spätestens)\s+"
    r"(.+?))?(?:\?|!|\.|$)",
    re.IGNORECASE,
)
INTENT_RE = re.compile(
    r"(?:ich\s+(will|m\u00f6chte|moechte|plane|versuche)"
    r"|wir\s+sollten|ich\s+nehme\s+mir\s+vor)",
    re.IGNORECASE,
)
MENTION_RE = re.compile(
    r"(?:irgendwann|mal schauen|später|spaeter|eventuell)", re.IGNORECASE
)
PERSON_RE = re.compile(r"(?:@([\w-]+)|(?:an|von|bei|fuer|für)\s+([A-ZÄÖÜ][a-zäöüß]+))")


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def classify(text: str) -> Optional[Dict[str, Any]]:
    """Klassifiziert einen Text deterministisch; None = kein Commitment-Signal."""
    low = text.lower()
    if any(m in low for m in DONE_MARKERS):
        return {"kind": "done", "status": "done", "confidence": 0.9, "party": "self"}
    if any(m in low for m in REJECT_MARKERS):
        return {
            "kind": "rejected",
            "status": "rejected",
            "confidence": 0.85,
            "party": "self",
        }
    m = REQUEST_RE.search(text)
    if m:
        return {
            "kind": "request_to_me",
            "status": "mentioned",
            "confidence": 0.75,
            "party": "other",
            "action": m.group(1).strip(),
        }
    m = OWN_RE.search(text)
    if m:
        return {
            "kind": "own_commitment",
            "status": "committed",
            "confidence": 0.9,
            "party": "self",
            "action": m.group(2).strip(),
            "due_raw": (m.group(3) or "").strip() or None,
        }
    if INTENT_RE.search(low):
        return {
            "kind": "intent",
            "status": "intent",
            "confidence": 0.6,
            "party": "self",
        }
    if MENTION_RE.search(low):
        return {
            "kind": "mention",
            "status": "mentioned",
            "confidence": 0.4,
            "party": "self",
        }
    return None


def extract_person(text: str) -> Optional[str]:
    """Verantwortliche/erwartende Person per @Mention oder Präposition."""
    m = PERSON_RE.search(text)
    if not m:
        return None
    return ("@" + m.group(1)) if m.group(1) else m.group(2)


class CommitmentManager:
    """Erkennt, dedupliziert und verwaltet Verpflichtungen im Kontextmodell."""

    def __init__(self, store):
        self.store = store
        self.context = ContextModel(store)

    def scan_text(
        self,
        text: str,
        source: str = "",
        scope: str = PRIVATE,
        source_item_id: Optional[str] = None,
        created_by: str = "owner",
    ) -> List[Dict[str, Any]]:
        """Text auf Commitments pruefen; liefert Detektionen inkl. Objekten."""
        scope = validate_scope(scope)
        detection = classify(text)
        if not detection:
            return []
        due = None
        due_raw = detection.get("due_raw") or text
        try:
            due = parse_due(due_raw)
        except Exception:  # noqa: BLE001 - Datum optional
            due = None
        person = extract_person(text)
        if detection["kind"] == "request_to_me":
            title = detection.get("action") or text.strip()[:80]
            responsible = person
        else:
            title = detection.get("action") or text.strip()[:80]
            responsible = "ich" if detection.get("party") == "self" else person
        title = title.strip(" .,;:!?")[:120]
        meta = {
            "kind": detection["kind"],
            "party": detection.get("party", "self"),
            "responsible": responsible,
            "detection_confidence": detection["confidence"],
        }
        existing = self._find_existing(title, scope)
        if existing:
            if existing["status"] in ("done", "rejected"):
                return [
                    {
                        "object": existing,
                        "detection": detection,
                        "duplicate": True,
                        "note": (
                            f"bereits {existing['status']} \u2013 "
                            "wird nicht wieder geoeffnet"
                        ),
                    }
                ]
            if (
                (existing.get("meta") or {}).get("due") == due
                or (existing.get("meta") or {}).get("due") is None
                and due is None
            ):
                return [
                    {
                        "object": existing,
                        "detection": detection,
                        "duplicate": True,
                        "note": "identische Verpflichtung bereits erfasst",
                    }
                ]
        obj = self.context.add_object(
            type_="commitment",
            title=title,
            scope=scope,
            status=detection["status"],
            confidence=detection["confidence"],
            source=source,
            source_item_id=source_item_id,
            created_by=created_by,
            meta={**meta, "due": due},
        )
        return [{"object": obj, "detection": detection, "duplicate": False}]

    def _find_existing(self, title: str, scope: str) -> Optional[Dict[str, Any]]:
        for obj in self.store.list_context_objects(
            type_="commitment", scope=scope, include_superseded=False
        ):
            if _norm(obj["title"]) == _norm(title):
                return obj
        return None

    def scan_item(self, item: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Capture-Hook: Item scope-sicher scannen (nie ohne Scope, nie hochstufen)."""
        return self.scan_text(
            item.get("content", ""),
            source=item.get("source", ""),
            scope=item.get("scope", PRIVATE),
            source_item_id=item.get("id"),
            created_by="capture",
        )

    def list(
        self,
        scope: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return self.context.list(
            type_="commitment", scope=scope, status=status, limit=limit
        )

    def get(self, id_: str) -> Optional[Dict[str, Any]]:
        return self.context.get(id_)

    def confirm(self, id_: str, by: str = "owner") -> Dict[str, Any]:
        """Anfrage/Absicht bestaetigen (mentioned/intent -> committed)."""
        return self.context.transition(id_, "committed", by=by)

    def close(
        self, id_: str, status: str = "done", by: str = "owner"
    ) -> Dict[str, Any]:
        return self.context.transition(id_, status, by=by)
