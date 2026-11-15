"""WP3: Commitment-Erkennung und -Verwaltung.

Deterministischer, offline arbeitender Detector auf Basis des WP1-Kontextmodells.
Unterscheidet Erwaehnung (mentioned), Absicht (intent), verbindliche Zusage
(committed), Erledigung (done) und Absage (rejected). Unklare/hypothetische Faelle
werden nie stillschweigend als verbindlich behandelt (niedrige Konfidenz + Status
intent/mentioned).

Regeln: Dedup gegen bestehende Verpflichtungen (normierter Titel + Scope),
bereits erledigte/verorfene werden nicht wieder geoeffnet, bei widerspruechlichen
Angaben greift die WP1-Konfliktlogik (conflicts_with). Scopes werden 1:1 vom
Quell-Item uebernommen (nie automatische Hochstufung). Mehrere Verpflichtungen
in einer Nachricht werden einzeln erkannt.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from .context_model import ContextModel
from .extract import extract_entities, parse_due
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
    "sind unterwegs",
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
    r"(?:kannst du(?: mir)?|könntest du|koenntest du|bitte)\s+(.+?)(?:\?|!|\.|$)",
    re.IGNORECASE,
)
QUESTION_RE = re.compile(
    r"\b(sagen|wissen|erklären|wann|ob|warum|weshalb|wie)\b", re.IGNORECASE
)
OWN_VERBS = (
    "schicke",
    "liefere",
    "erledige",
    "kümmere",
    "kuemmere",
    "rufe",
    "nehme",
    "kläre",
    "klaere",
    "mache",
    "besorge",
    "prüfe",
    "pruefe",
    "gebe",
    "reiche",
    "verspreche",
)
OWN_RE = re.compile(
    r"ich\s+(?:" + "|".join(OWN_VERBS) + r")\s*,?\s*(.+?)"
    r"(?:\s+(?:bis|am|spätestens)\s+(.+?))?(?:\?|!|\.|$)",
    re.IGNORECASE,
)
INTENT_RE = re.compile(
    r"(?:ich\s+(?:will|möchte|moechte|plane|versuche|nehme\s+mir\s+vor|"
    r"entscheide\s+mich)|wir\s+sollten)",
    re.IGNORECASE,
)
HYPOTHETICAL_RE = re.compile(
    r"(?:vielleicht|eventuell|ggf\.?|mal schauen|ich\s+glaube|"
    r"bin\s+mir\s+nicht\s+sicher)",
    re.IGNORECASE,
)
FOREIGN_RE = re.compile(
    r"([A-ZÄÖÜ][\w-]*|@[\w-]+)\s+hat\s+(zugesagt|versprochen|angekündigt)",
    re.IGNORECASE,
)
MUST_RE = re.compile(r"(?:ich\s+muss|muss\s+ich)", re.IGNORECASE)
SHAFFE_RE = re.compile(r"schaffe\s+ich", re.IGNORECASE)
MENTION_RE = re.compile(
    r"(?:irgendwann|mal schauen|später|spaeter|eventuell)", re.IGNORECASE
)
PERSON_RE = re.compile(r"(?:@([\w-]+)|(?:an|von|bei|fuer|für)\s+([A-ZÄÖÜ][a-zäöüß]+))")

LEADING_FILLER = (
    "ich ",
    "mir ",
    "dir ",
    "mich ",
    "den ",
    "die ",
    "das ",
    "dem ",
    "des ",
    "einen ",
    "eine ",
    "ein ",
)


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _norm_title(title: str) -> str:
    """Titel fuer Dubletten-Abgleich: fuehrende Pronomen/Artikel entfernen."""
    low = _norm(title)
    changed = True
    while changed and low:
        changed = False
        for filler in LEADING_FILLER:
            if low.startswith(filler):
                low = low[len(filler) :]
                changed = True
    return low


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
    m = FOREIGN_RE.search(text)
    if m:
        return {
            "kind": "foreign_commitment",
            "status": "committed",
            "confidence": 0.85,
            "party": "other",
            "person": m.group(1),
            "action": text.strip()[:120],
        }
    m = REQUEST_RE.search(text)
    if m:
        action = m.group(1).strip()
        if " nicht " in f" {action} ":
            return None
        if action.endswith("?") or text.rstrip().endswith("?"):
            if QUESTION_RE.search(action):
                return None
        return {
            "kind": "request_to_me",
            "status": "mentioned",
            "confidence": 0.75,
            "party": "other",
            "action": action,
        }
    if INTENT_RE.search(low):
        return {
            "kind": "intent",
            "status": "intent",
            "confidence": 0.6,
            "party": "self",
        }
    if HYPOTHETICAL_RE.search(low) and OWN_RE.search(text):
        return {
            "kind": "hypothetical",
            "status": "intent",
            "confidence": 0.5,
            "party": "self",
        }
    m = OWN_RE.search(text)
    if m:
        return {
            "kind": "own_commitment",
            "status": "committed",
            "confidence": 0.9,
            "party": "self",
            "action": m.group(1).strip(),
            "due_raw": (m.group(2) or "").strip() or None,
        }
    if SHAFFE_RE.search(low):
        return {
            "kind": "own_commitment",
            "status": "committed",
            "confidence": 0.8,
            "party": "self",
            "action": text.strip()[:120],
        }
    if MUST_RE.search(low):
        return {
            "kind": "obligation",
            "status": "mentioned",
            "confidence": 0.55,
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


def _segments(text: str) -> List[str]:
    """Zerlegt eine Nachricht in Einzelaussagen (Satzgrenzen, 'und'/'sowie')."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out: List[str] = []
    for part in parts:
        if re.search(r"\s+(?:und|sowie)\s+", part):
            chunks = re.split(r"\s+(?:und|sowie)\s+", part)
            out.append(chunks[0])
            for chunk in chunks[1:]:
                chunk = chunk.strip()
                if chunk and not chunk.lower().startswith("ich"):
                    first = chunk.split()[0].lower().rstrip(".,!?")
                    if first in OWN_VERBS:
                        chunk = "ich " + chunk
                out.append(chunk)
        else:
            out.append(part)
    return [s for s in out if s]


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
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Text auf Commitments pruefen; mehrere Aussagen -> mehrere Detektionen."""
        scope = validate_scope(scope)
        results: List[Dict[str, Any]] = []
        for segment in _segments(text):
            results.extend(
                self._scan_one(
                    segment,
                    source=source,
                    scope=scope,
                    source_item_id=source_item_id,
                    created_by=created_by,
                    now=now,
                )
            )
        return results

    def _scan_one(
        self,
        text: str,
        source: str,
        scope: str,
        source_item_id: Optional[str],
        created_by: str,
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        detection = classify(text)
        if not detection:
            return []
        due = None
        try:
            due = parse_due(detection.get("due_raw") or text, now)
        except Exception:  # noqa: BLE001 - Datum optional
            due = None
        person = extract_person(text) or detection.get("person")
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
            "due": due,
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
                            f"bereits {existing['status']} – "
                            "wird nicht wieder geoeffnet"
                        ),
                    }
                ]
            existing_due = (existing.get("meta") or {}).get("due")
            if existing_due == due:
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
            meta=meta,
        )
        self._auto_link(obj, text, source)
        return [{"object": obj, "detection": detection, "duplicate": False}]

    def _auto_link(self, obj: Dict[str, Any], text: str, source: str) -> None:
        """Verknuepft ein Commitment mit vorhandenen Personen/Projekten (WP3 A2)."""
        names = {
            str(e.get("id"))
            for e in extract_entities(text)
            if e.get("type") == "entity"
        }
        person = extract_person(text)
        if person:
            names.add(person.lstrip("@"))
        for type_ in ("person", "project"):
            for existing in self.context.list(type_=type_, scope=obj["scope"]):
                if _norm(existing["title"]) in {_norm(n) for n in names}:
                    already = any(
                        lnk["target_id"] == existing["id"]
                        for lnk in self.context.links(obj["id"])
                    )
                    if not already:
                        self.context.link(
                            obj["id"], existing["id"], "involves", provenance=source
                        )

    def _find_existing(self, title: str, scope: str) -> Optional[Dict[str, Any]]:
        norm = _norm_title(title)
        for obj in self.store.list_context_objects(
            type_="commitment", scope=scope, include_superseded=False
        ):
            if _norm_title(obj["title"]) == norm:
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
