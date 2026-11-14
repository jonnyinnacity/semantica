"""Datenmodelle fuer das Personal OS.

Alle Persistenz laeuft ueber diese Dataclasses; sie serialisieren nach
JSON-kompatible Dicts fuer den SQLite-Layer.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def new_id() -> str:
    """Kleine eindeutige ID (12 Hex-Zeichen)."""
    return uuid.uuid4().hex[:12]


def utcnow() -> str:
    """Aktueller UTC-Zeitstempel als ISO-String."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class MemoryItem:
    """Ein Wissens-Eintrag im Langzeitgedaechtnis."""

    id: str
    kind: str
    content: str
    source: str = ""
    tags: List[str] = field(default_factory=list)
    hash: str = ""
    entities: List[Dict[str, Any]] = field(default_factory=list)
    triplets: List[Dict[str, Any]] = field(default_factory=list)
    embedding: List[float] = field(default_factory=list)
    created_at: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryItem":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Loop:
    """Ein offener Loop (Aufgabe, Projekt, Versprechen) der laufen bleiben soll."""

    id: str
    title: str
    status: str = "open"
    priority: int = 1
    due: Optional[str] = None
    repeat: Optional[str] = None
    next_action: str = ""
    tags: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    done_at: Optional[str] = None
    snooze_until: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Loop":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Delegation:
    """Eine an einen Agenten delegierte Aufgabe."""

    id: str
    agent: str
    instruction: str
    status: str = "pending"
    result: str = ""
    trace: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Delegation":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
