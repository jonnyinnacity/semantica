"""Berechtigungen (WP1): wer darf was in welchem Scope?

Subjekte: ``owner`` (lokale Sitzung/CLI), ``agent`` (lokale Agenten als Proxy des
Owners), ``external`` (externe Modellaufrufe, token-geschuetzte API-Clients).

Default-Policy (sicher): Owner darf alles lokal. Externe Modellaufrufe duerfen nur
den Scope ``work`` sehen (und auch dort nur redacted); ``private`` ist fuer externe
Subjekte immer verweigert, sofern nicht ausdruecklich per ``grant`` freigegeben.
Explizite Regeln in der DB ueberschreiben die Defaults; bei Gleichstand gilt deny.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import utcnow
from .scopes import PRIVATE, WORK

DEFAULT_RULES = [
    ("owner", "*", "*", "allow"),
    ("agent", "*", "*", "allow"),
    ("external", "model_call", WORK, "allow"),
    ("external", "*", PRIVATE, "deny"),
    ("external", "read", WORK, "allow"),
    ("external", "write", WORK, "deny"),
]


def _specificity(subject: str, action: str, scope: str) -> int:
    return sum(1 for v in (subject, action, scope) if v != "*")


def _matches(
    rule_subject: str,
    rule_action: str,
    rule_scope: str,
    subject: str,
    action: str,
    scope: str,
) -> bool:
    def m(rule: str, val: str) -> bool:
        return rule == "*" or rule == val

    return m(rule_subject, subject) and m(rule_action, action) and m(rule_scope, scope)


class PermissionManager:
    """Prueft Aktionen gegen explizite Regeln (DB) + sichere Defaults."""

    def __init__(self, store, config=None):
        self.store = store
        self.config = config

    def _rules(self) -> List[Dict[str, Any]]:
        rules = [
            {"subject": s, "action": a, "scope": sc, "effect": e}
            for s, a, sc, e in DEFAULT_RULES
        ]
        rules.extend(self.store.list_permissions())
        return rules

    def check(self, subject: str, action: str, scope: str) -> bool:
        """True, wenn die Aktion erlaubt ist. Gleichstand/Unsicherheit => deny."""
        matching = [
            r
            for r in self._rules()
            if _matches(r["subject"], r["action"], r["scope"], subject, action, scope)
        ]
        if not matching:
            return False
        best = max(
            _specificity(r["subject"], r["action"], r["scope"]) for r in matching
        )
        best_rules = [
            r
            for r in matching
            if _specificity(r["subject"], r["action"], r["scope"]) == best
        ]
        effects = {r["effect"] for r in best_rules}
        if "deny" in effects:
            return False
        return "allow" in effects

    def grant(
        self, subject: str, action: str, scope: str, effect: str = "allow"
    ) -> Dict[str, Any]:
        """Explizite Regel eintragen (z. B. Freigabe fuer externen Zugriff)."""
        perm = {
            "subject": subject,
            "action": action,
            "scope": scope,
            "effect": effect,
            "created_at": utcnow(),
            "meta": {},
        }
        self.store.add_permission(perm)
        return perm

    def revoke(self, subject: str, action: str, scope: str) -> None:
        self.store.delete_permission(subject, action, scope)

    def can_external_model_call(self, scope: str) -> bool:
        """Darf ein externes Modell Daten dieses Scopes erhalten?"""
        allow_private = bool(
            self.config
            and getattr(self.config.privacy, "external_can_see_private", False)
        )
        if scope == PRIVATE and not allow_private:
            return False
        return self.check("external", "model_call", scope)

    def list_rules(self, subject: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.store.list_permissions(subject)
