"""Leichtgewichtige, lokale Extraktion: Entitaeten, Tripletten, Loop-Parsing.

Bewusst dependency-frei (nur stdlib), damit das OS sofort und offline
funktioniert. Wenn ``semantica`` mit seinen Backends verfuegbar ist, kann
die Memory-Schicht zusaetzlich den Semantica-GraphBuilder verwenden.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüßàâæçéèêëîïôœùûÿ]+")
CAPITALIZED_RE = re.compile(
    r"(?<![\w.])((?:[A-ZÄÖÜ][a-zäöüß]+)(?:\s+[A-ZÄÖÜ][a-zäöüß]+){0,3})"
)
URL_EMAIL_RE = re.compile(r"(https?://[^\s]+|[\w.+-]+@[\w-]+\.[\w.]+)")
TAG_RE = re.compile(r"#([\w-]+)")
MENTION_RE = re.compile(r"@([\w-]+)")
DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b")
ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
IN_DAYS_RE = re.compile(r"\bin\s+(\d+)\s+(?:tagen?|d)\b", re.IGNORECASE)

WEEKDAYS = {
    "montag": 0,
    "dienstag": 1,
    "mittwoch": 2,
    "donnerstag": 3,
    "freitag": 4,
    "samstag": 5,
    "sonntag": 6,
}

REPEATS = {
    "täglich": "daily",
    "täglich.": "daily",
    "jeden tag": "daily",
    "wöchentlich": "weekly",
    "monatlich": "monthly",
    "jährlich": "yearly",
}

VERBS = {
    "ist",
    "war",
    "sind",
    "waren",
    "hat",
    "hatte",
    "arbeitet",
    "arbeitete",
    "leitet",
    "leitete",
    "liebt",
    "liebte",
    "baut",
    "baute",
    "entwickelt",
    "entwickelte",
    "gründete",
    "gründete",
    "besitzt",
    "besaß",
    "passiert",
    "ist passiert",
    "kümmert sich um",
    "kümmert",
    "unterstützt",
    "muss",
    "soll",
    "will",
    "erledigt",
    "erledigte",
}


def tokenize(text: str) -> List[str]:
    """Lowercase-Woerter eines Textes."""
    return [w.lower() for w in WORD_RE.findall(text)]


def extract_entities(text: str) -> List[Dict[str, Any]]:
    """Entitaeten per Heuristik: URLs, E-Mails, #Tags, @Mentions, Eigennamen."""
    entities: List[Dict[str, Any]] = []
    seen = set()

    def add(value: str, type_: str) -> None:
        key = (type_, value.lower())
        if key not in seen:
            seen.add(key)
            entities.append({"id": value, "type": type_})

    for m in URL_EMAIL_RE.finditer(text):
        raw = m.group(1)
        add(raw, "url" if raw.startswith("http") else "email")
    for m in TAG_RE.finditer(text):
        add("#" + m.group(1), "tag")
    for m in MENTION_RE.finditer(text):
        add("@" + m.group(1), "person")
    for m in CAPITALIZED_RE.finditer(text):
        add(m.group(1), "entity")
    return entities


def extract_triplets(text: str) -> List[Dict[str, Any]]:
    """Einfache Subjekt-Prädikat-Objekt-Tripletts aus Satzheuristiken."""
    triplets: List[Dict[str, Any]] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        words = WORD_RE.findall(sentence)
        lower = [w.lower() for w in words]
        for i, w in enumerate(lower):
            if w in VERBS and 0 < i < len(words) - 1:
                subject = " ".join(words[:i]).strip(" ,;:")
                obj = " ".join(words[i + 1 :]).strip(" ,;:.")
                if subject and obj:
                    triplets.append({"subject": subject, "predicate": w, "object": obj})
                break
    return triplets


def parse_due(text: str, now: Optional[datetime] = None) -> Optional[str]:
    """Fälligkeitsdatum aus natürlichem Text (deutsch) parsen."""
    now = now or datetime.now()
    low = text.lower()
    m = IN_DAYS_RE.search(low)
    if m:
        return (now + timedelta(days=int(m.group(1)))).date().isoformat()
    if "übermorgen" in low or "uebermorgen" in low:
        return (now + timedelta(days=2)).date().isoformat()
    if "morgen" in low:
        return (now + timedelta(days=1)).date().isoformat()
    if "heute" in low:
        return now.date().isoformat()
    for name, wd in WEEKDAYS.items():
        if name in low:
            if re.search(rf"jeden\s+{name}", low) or "wöchentlich" in low:
                days_ahead = (wd - now.weekday()) % 7
                return (now + timedelta(days=days_ahead or 7)).date().isoformat()
            days_ahead = (wd - now.weekday()) % 7
            return (now + timedelta(days=days_ahead)).date().isoformat()
    m = ISO_DATE_RE.search(low)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    m = DATE_RE.search(low)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None
    return None


def parse_repeat(text: str) -> Optional[str]:
    low = text.lower()
    for key, val in REPEATS.items():
        if key in low:
            return val
    for name, wd in WEEKDAYS.items():
        if re.search(rf"jeden\s+{name}", low):
            return "weekly"
    return None


def parse_priority(text: str) -> int:
    low = text.lower()
    if "dringend" in low or "!!!" in low or "asap" in low:
        return 3
    if "wichtig" in low or "!" in low:
        return 2
    return 1


def parse_loop(text: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Parst einen Loop aus Freitext (Titel, Fälligkeit, Tags, Next Action)."""
    now = now or datetime.now()
    next_action = ""
    for sep in ("→", "->", "als nächstes:", "als naechstes:"):
        if sep in text.lower():
            idx = text.lower().index(sep)
            text, next_action = text[:idx].strip(), text[idx + len(sep) :].strip()
            break
    tags = [t.lower() for t in TAG_RE.findall(text)]
    title = TAG_RE.sub("", text).strip()
    return {
        "title": title or text.strip(),
        "due": parse_due(text, now),
        "repeat": parse_repeat(text),
        "priority": parse_priority(text),
        "next_action": next_action,
        "tags": tags,
    }


def _add_months(d: date, months: int) -> date:
    import calendar

    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def next_due(
    due_iso: str, repeat: Optional[str], now: Optional[datetime] = None
) -> str:
    """Nächste Fälligkeit nach Abschluss eines wiederkehrenden Loops."""
    now = now or datetime.now()
    d = date.fromisoformat(due_iso)
    if repeat == "daily":
        d += timedelta(days=1)
        while d < now.date():
            d += timedelta(days=1)
    elif repeat == "weekly":
        d += timedelta(days=7)
        while d < now.date():
            d += timedelta(days=7)
    elif repeat in ("monthly", "yearly"):
        months = 1 if repeat == "monthly" else 12
        d = _add_months(d, months)
        while d < now.date():
            d = _add_months(d, months)
    else:
        return due_iso
    return d.isoformat()
