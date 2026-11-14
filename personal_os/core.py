"""PersonalOS: die zentrale Klasse des persoenlichen KI-Operating-Systems.

Verbindet Inbox, Langzeitgedaechtnis, Loops, Digest, Delegation und
Connectors zu einem lokalen, verbindbaren System.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from . import inbox as inbox_mod
from .config import OSConfig
from .context_model import ContextModel
from .delegate import DelegationManager
from .digest import build_digest, build_weekly, render_digest, render_weekly
from .loops import LoopsManager
from .memory import KnowledgeMemory
from .permissions import PermissionManager
from .scopes import redact_for_external
from .store import SQLiteStore


class PersonalOS:
    """Dein persoenliches KI-OS (lokal, verbindbar, delegationsfaehig)."""

    def __init__(self, data_dir: Optional[str] = None):
        self.config = OSConfig.load(data_dir)
        self.store = SQLiteStore(self.config.data_dir)
        self.memory = KnowledgeMemory(self.store, self.config)
        self.loops = LoopsManager(self.store, self.config)
        self.delegations = DelegationManager(self.store, self)
        self.context = ContextModel(self.store)
        self.permissions = PermissionManager(self.store, self.config)

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "PersonalOS":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def capture(
        self,
        content: str,
        kind: str = "note",
        source: str = "",
        tags: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
        scope: Optional[str] = None,
    ) -> Dict[str, Any]:
        return inbox_mod.capture(
            self, content, kind=kind, source=source, tags=tags, meta=meta, scope=scope
        )

    def capture_file(self, path: str, scope: Optional[str] = None) -> Dict[str, Any]:
        return inbox_mod.capture_file(self, path, scope=scope)

    def capture_url(self, url: str, scope: Optional[str] = None) -> Dict[str, Any]:
        return inbox_mod.capture_url(self, url, scope=scope)

    def ask(
        self, query: str, limit: int = 5, scope: Optional[str] = None
    ) -> Dict[str, Any]:
        """Suche mit optionalem Scope; scope='work' sieht niemals private Daten."""
        return self.memory.ask(query, limit=limit, scope=scope)

    def redact_for_external(
        self, data: Any, allow_private: Optional[bool] = None
    ) -> Any:
        """Payload fuer externe Modellaufrufe redacten (private default: entfernt)."""
        if allow_private is None:
            allow_private = self.config.privacy.external_can_see_private
        return redact_for_external(data, allow_private=allow_private)

    def add_loop(
        self,
        title: str,
        due: Optional[str] = None,
        repeat: Optional[str] = None,
        priority: int = 1,
        next_action: str = "",
        tags: Optional[List[str]] = None,
        scope: str = "private",
    ) -> Dict[str, Any]:
        return self.loops.add(
            title=title,
            due=due,
            repeat=repeat,
            priority=priority,
            next_action=next_action,
            tags=tags,
            scope=scope,
        )

    def add_loop_from_text(self, text: str, scope: str = "private") -> Dict[str, Any]:
        return self.loops.add_from_text(text, scope=scope)

    def list_loops(
        self, status: str = "open", scope: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        return self.loops.list(status=status, scope=scope)

    def complete_loop(self, id_: str) -> Optional[Dict[str, Any]]:
        return self.loops.complete(id_)

    def snooze_loop(self, id_: str, days: int = 1) -> Optional[Dict[str, Any]]:
        return self.loops.snooze(id_, days)

    def delegate(
        self, instruction: str, agent: str = "default", scope: str = "private"
    ) -> Dict[str, Any]:
        return self.delegations.add(instruction, agent=agent, scope=scope)

    def run_delegation(self, id_: str) -> Optional[Dict[str, Any]]:
        return self.delegations.run(id_)

    def run_pending_delegations(self) -> List[Dict[str, Any]]:
        return self.delegations.run_pending()

    def list_delegations(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.delegations.list(status=status)

    def today(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        return build_digest(self, now=now)

    def digest_text(self, now: Optional[datetime] = None) -> str:
        return render_digest(build_digest(self, now=now), self.config.profile_name)

    def weekly_text(self, now: Optional[datetime] = None) -> str:
        return render_weekly(build_weekly(self, now=now), self.config.profile_name)

    def sync(self, connector: Optional[str] = None) -> Dict[str, Any]:
        from .connectors import sync_all

        return sync_all(self, only=connector)

    def stats(self) -> Dict[str, Any]:
        return {
            "data_dir": self.config.data_dir,
            "profile": self.config.profile_name,
            "memory": self.memory.stats(),
            "context_objects": len(self.context.list()),
            "open_loops": len(self.loops.list("open")),
            "pending_delegations": len(self.list_delegations(status="pending")),
            "connectors": sorted(self.config.connectors.keys()),
        }
