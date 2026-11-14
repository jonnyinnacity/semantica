"""Inbox: einheitlicher Eingang fuer alles Wissen.

 egal ob manuell, Datei, URL oder Connector - alles landet ueber
``capture`` im selben Speicher und wird dedupliziert.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import MemoryItem, new_id, utcnow
from .scopes import validate_scope

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".json",
    ".csv",
    ".tsv",
    ".xml",
    ".html",
    ".htm",
    ".py",
    ".js",
    ".ts",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".log",
    ".eml",
}


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def capture(
    core,
    content: str,
    kind: str = "note",
    source: str = "",
    tags: Optional[List[str]] = None,
    meta: Optional[Dict[str, Any]] = None,
    scope: Optional[str] = None,
) -> Dict[str, Any]:
    """Text ins Langzeitgedaechtnis schreiben (Duplikate werden erkannt).

    ``scope`` trennt private von beruflichen Daten (Default: private, sicher).
    """
    content = (content or "").strip()
    if not content:
        raise ValueError("Leerer Inhalt kann nicht erfasst werden.")
    scope = validate_scope(scope, default=core.config.privacy.default_capture_scope)
    digest = content_hash(content)
    existing = core.store.find_item_by_hash(digest)
    if existing:
        return {**existing, "duplicate": True}
    item = MemoryItem(
        id=new_id(),
        kind=kind,
        content=content,
        source=source,
        scope=scope,
        tags=tags or [],
        hash=digest,
        created_at=utcnow(),
        meta=meta or {},
    )
    core.memory.add(item)
    result = item.to_dict()
    result["duplicate"] = False
    return result


def capture_file(core, path: str, scope: Optional[str] = None) -> Dict[str, Any]:
    """Datei ins Gedaechtnis laden (Text-Formate direkt, Rest via Semantica)."""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(str(p))
    if p.suffix.lower() in TEXT_EXTENSIONS:
        text = p.read_text(encoding="utf-8", errors="replace")
    else:
        text = _extract_via_semantica(str(p))
    return capture(
        core, text, kind="file", source=str(p), meta={"filename": p.name}, scope=scope
    )


def _extract_via_semantica(path: str) -> str:
    """Binär-/Office-Formate ueber semantica.FileIngestor, falls installiert."""
    try:
        from semantica.ingest import FileIngestor

        obj = FileIngestor().ingest_file(path)
        return getattr(obj, "content", "") or str(obj)
    except Exception as exc:  # noqa: BLE001 - klarer Fehler statt Absturz
        raise RuntimeError(
            f"Dateiformat nicht direkt lesbar und semantica nicht verfuegbar: {exc}"
        ) from exc


def capture_url(core, url: str, scope: Optional[str] = None) -> Dict[str, Any]:
    """Webseite ins Gedaechtnis laden ( siehe connectors.web )."""
    from .connectors.web import fetch_text

    text, title = fetch_text(url)
    return capture(
        core,
        text,
        kind="web",
        source=url,
        meta={"title": title, "url": url},
        scope=scope,
    )
