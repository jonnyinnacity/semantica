"""Delegation: Aufgaben an Agenten abgeben, die auf das OS zugreifen duerfen.

Ein Agent bekommt einen Satz von Tools (Gedächtnis fragen, capture, Loop
anlegen, Loops listen). Ohne konfiguriertes LLM laeuft ein deterministischer
Regel-Agent (offline, reproduzierbar); mit LLM-Endpoint (OpenAI-kompatibel,
Key nur ueber Umgebungsvariable) ein Tool-Calling-Agent.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

from .models import Delegation, new_id, utcnow

TOOL_NAMES = [
    "memory_ask",
    "memory_capture",
    "loop_add",
    "loops_list",
    "delegations_list",
]


class AgentRunner:
    """Fuehrt Delegationen aus und protokolliert jeden Tool-Call im Trace."""

    def __init__(self, core):
        self.core = core
        self._scope: Optional[str] = None
        self.tools: Dict[str, Callable[..., Any]] = {
            "memory_ask": self._t_memory_ask,
            "memory_capture": self._t_capture,
            "loop_add": self._t_loop_add,
            "loops_list": self._t_loops_list,
            "delegations_list": self._t_delegations_list,
        }

    def _t_memory_ask(self, query: str, limit: int = 5) -> Dict[str, Any]:
        return self.core.ask(query, limit=limit, scope=self._scope)

    def _t_capture(
        self, content: str, tags: str = "", kind: str = "agent"
    ) -> Dict[str, Any]:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        return self.core.capture(
            content, kind=kind, source="agent", tags=tag_list, scope=self._scope
        )

    def _t_loop_add(self, text: str) -> Dict[str, Any]:
        return self.core.add_loop_from_text(text, scope=self._scope or "private")

    def _t_loops_list(self, status: str = "open") -> List[Dict[str, Any]]:
        return self.core.list_loops(status=status)

    def _t_delegations_list(self, status: str = "") -> List[Dict[str, Any]]:
        return self.core.list_delegations(status=status or None)

    def _llm_allowed(self, scope: str) -> bool:
        """Externe Modellaufrufe nur, wenn der Scope dafuer freigegeben ist (WP1)."""
        return self.core.permissions.can_external_model_call(scope)

    def run(self, delegation: Dict[str, Any]) -> Dict[str, Any]:
        """Delegation ausfuehren; Ergebnis und Trace in der DB ablegen."""
        core = self.core
        did = delegation["id"]
        self._scope = (delegation.get("meta") or {}).get("scope", "private")
        core.store.update_delegation(did, {"status": "running", "updated_at": utcnow()})
        trace: List[Dict[str, Any]] = []
        try:
            llm_configured = core.config.llm.provider not in ("", "none")
            if llm_configured and self._llm_allowed(self._scope):
                result = self._llm_agent(delegation["instruction"], trace)
            else:
                result = self._rule_agent(delegation["instruction"], trace)
                if llm_configured:
                    result += (
                        "\n[Hinweis] Externes Modell nicht genutzt: Scope "
                        f"'{self._scope}' ist nicht fuer externe Aufrufe freigegeben."
                    )
            core.store.update_delegation(
                did,
                {
                    "status": "done",
                    "result": result,
                    "trace": trace,
                    "updated_at": utcnow(),
                },
            )
        except Exception as exc:  # noqa: BLE001 - Fehler gehoeren ins Ergebnis
            core.store.update_delegation(
                did,
                {
                    "status": "failed",
                    "result": f"Fehler: {exc}",
                    "trace": trace,
                    "updated_at": utcnow(),
                },
            )
        return core.store.get_delegation(did)

    def _call(
        self, name: str, args: Dict[str, Any], trace: List[Dict[str, Any]]
    ) -> Any:
        result = self.tools[name](**args)
        trace.append({"tool": name, "args": args, "ok": True})
        return result

    def _rule_agent(self, instruction: str, trace: List[Dict[str, Any]]) -> str:
        """Deterministischer Offline-Agent: intentbasiert, ohne LLM."""
        low = instruction.lower()
        parts: List[str] = []
        asks = any(
            k in low
            for k in (
                "was weiß ich",
                "was weisst ich",
                "suche",
                "finde",
                "frage",
                "recherch",
                "überblick über",
                "ueberblick ueber",
                "was ist mit",
            )
        )
        wants_loop = any(
            k in low
            for k in (
                "erinner",
                "todo",
                "aufgabe",
                "loop",
                "mach",
                "erledige",
                "anrufen",
                "nicht vergessen",
            )
        )
        if wants_loop:
            loop = self._call("loop_add", {"text": instruction}, trace)
            parts.append(
                f"Loop angelegt: **{loop['title']}**"
                + (f" (fällig {loop['due']})" if loop.get("due") else "")
                + f" – ID `{loop['id']}`"
            )
        if asks or not wants_loop:
            answer = self._call("memory_ask", {"query": instruction, "limit": 3}, trace)
            hits = answer.get("results", [])
            if hits:
                parts.append("Gefundene Einträge im Wissensspeicher:")
                for h in hits:
                    snippet = h["content"].replace("\n", " ")[:120]
                    parts.append(f"- ({h['score']}) {snippet}…")
            else:
                parts.append("Dazu habe ich im Wissensspeicher nichts gefunden.")
                parts.append(
                    "Tipp: Erst `pos capture` mit dem Wissen, dann erneut delegieren."
                )
        return "\n".join(parts)

    def _llm_agent(self, instruction: str, trace: List[Dict[str, Any]]) -> str:
        """Tool-Calling-Agent ueber OpenAI-kompatibles Endpoint (Key via Env)."""
        import requests

        cfg = self.core.config.llm
        api_key = os.environ.get(cfg.api_key_env, "")
        tool_schemas = [
            {
                "type": "function",
                "function": {
                    "name": n,
                    "description": n,
                    "parameters": {"type": "object", "properties": {}},
                },
            }
            for n in TOOL_NAMES
        ]
        payload = {
            "model": cfg.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Du bist ein Agent des Personal OS. Nutze die Tools, um die "
                        "Aufgabe zu erledigen. Antworte kurz auf Deutsch."
                    ),
                },
                {"role": "user", "content": instruction},
            ],
            "tools": tool_schemas,
            "tool_choice": "auto",
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        resp = requests.post(
            cfg.endpoint.rstrip("/") + "/chat/completions",
            headers=headers,
            data=json.dumps(payload),
            timeout=60,
        )
        resp.raise_for_status()
        message = resp.json()["choices"][0]["message"]
        for call in message.get("tool_calls", []) or []:
            fn = call["function"]
            args = json.loads(fn.get("arguments") or "{}")
            self._call(fn["name"], args, trace)
        return message.get("content") or "Erledigt (siehe Trace)."


class DelegationManager:
    """Anlegen und Auflisten von Delegationen."""

    def __init__(self, store, core):
        self.store = store
        self.core = core
        self.runner = AgentRunner(core)

    def add(
        self, instruction: str, agent: str = "default", scope: str = "private"
    ) -> Dict[str, Any]:
        now = utcnow()
        delegation = Delegation(
            id=new_id(),
            agent=agent,
            instruction=instruction,
            status="pending",
            created_at=now,
            updated_at=now,
            meta={"scope": scope},
        )
        self.store.add_delegation(delegation.to_dict())
        return delegation.to_dict()

    def run(self, id_: str) -> Optional[Dict[str, Any]]:
        delegation = self.store.get_delegation(id_)
        if not delegation:
            return None
        return self.runner.run(delegation)

    def run_pending(self) -> List[Dict[str, Any]]:
        out = []
        for d in self.store.list_delegations(status="pending"):
            out.append(self.run(d["id"]))
        return out

    def list(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.store.list_delegations(status=status)
