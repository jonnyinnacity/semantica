"""Connector-Basisklasse: jedes externe System speist die Inbox."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class ConnectorError(RuntimeError):
    """Fehler eines Connectors beim Sync."""


class Connector(ABC):
    """Basisklasse fuer alle Anschluesse (Dateien, Git, E-Mail, Web, MCP)."""

    name = "base"

    def __init__(self, core, config: Dict[str, Any]):
        self.core = core
        self.config = config or {}

    @abstractmethod
    def sync(self) -> int:
        """Neue Inhalte ins OS einspeisen; liefert Anzahl neuer Eintraege."""

    def state_key(self) -> str:
        return f"conn:{self.name}:state"
