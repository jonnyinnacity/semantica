"""Connectors: Anschluesse fuer externe Systeme (Dateien, Git, E-Mail, Web, MCP)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import Connector, ConnectorError
from .email import EmailConnector
from .filesystem import FilesystemConnector, GitConnector
from .mcp_client import MCPClientConnector
from .web import WebConnector

REGISTRY = {
    "filesystem": FilesystemConnector,
    "git": GitConnector,
    "email": EmailConnector,
    "web": WebConnector,
    "mcp": MCPClientConnector,
}


def create(core, name: str, config: Dict[str, Any]) -> Connector:
    if name not in REGISTRY:
        raise ConnectorError(f"Unbekannter Connector: {name}")
    return REGISTRY[name](core, config)


def sync_all(core, only: Optional[str] = None) -> Dict[str, Any]:
    """Alle Connectors synchronisieren; Fehler pro Connector isolieren."""
    results: Dict[str, Any] = {}
    names = [only] if only else sorted(core.config.connectors.keys())
    for name in names:
        cfg = core.config.connectors.get(name)
        if cfg is None:
            results[name] = {"captured": 0, "error": "nicht konfiguriert"}
            continue
        try:
            connector = create(core, name, cfg)
            results[name] = {"captured": connector.sync(), "error": None}
        except Exception as exc:  # noqa: BLE001 - einzelner Connector stoppt nicht alle
            results[name] = {"captured": 0, "error": str(exc)}
    return results


__all__ = [
    "Connector",
    "ConnectorError",
    "REGISTRY",
    "create",
    "sync_all",
    "FilesystemConnector",
    "GitConnector",
    "EmailConnector",
    "WebConnector",
    "MCPClientConnector",
]
