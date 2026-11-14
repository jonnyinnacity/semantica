"""MCP-Server (stdio, JSON-RPC 2.0): macht das Personal OS fuer KI-Tools erreichbar.

Damit kann z. B. Claude Desktop / Cursor / ein anderer Agent direkt auf dein
Wissen zugreifen: capture, ask, today, Loops, Delegationen, Sync.
Kommunikation laeuft ausschliesslich ueber stdio (lokal).
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

from .core import PersonalOS

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "pos_capture",
        "description": "Wissen ins Langzeitgedaechtnis schreiben.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "kind": {"type": "string"},
                "source": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["content"],
        },
    },
    {
        "name": "pos_ask",
        "description": "Semantische Frage gegen das Wissensgedaechtnis.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"],
        },
    },
    {
        "name": "pos_today",
        "description": "Tages-Digest: faellige/stale Loops, Delegationen, Neuigkeiten.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "pos_digest_text",
        "description": "Tages- oder Wochen-Digest als Text.",
        "inputSchema": {
            "type": "object",
            "properties": {"weekly": {"type": "boolean"}},
        },
    },
    {
        "name": "pos_add_loop",
        "description": "Loop aus Freitext anlegen, z. B. 'Zahnarzt morgen #gesund'.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "pos_list_loops",
        "description": "Loops listen.",
        "inputSchema": {"type": "object", "properties": {"status": {"type": "string"}}},
    },
    {
        "name": "pos_complete_loop",
        "description": "Loop abschliessen.",
        "inputSchema": {
            "type": "object",
            "properties": {"loop_id": {"type": "string"}},
            "required": ["loop_id"],
        },
    },
    {
        "name": "pos_delegate",
        "description": "Aufgabe an einen Agenten delegieren und ausfuehren.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "instruction": {"type": "string"},
                "agent": {"type": "string"},
            },
            "required": ["instruction"],
        },
    },
    {
        "name": "pos_list_delegations",
        "description": "Delegationen listen.",
        "inputSchema": {"type": "object", "properties": {"status": {"type": "string"}}},
    },
    {
        "name": "pos_sync",
        "description": "Alle konfigurierten Connectors synchronisieren.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "pos_stats",
        "description": "Statistiken des OS.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def handle_request(
    core: PersonalOS, request: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Verarbeitet eine einzelne JSON-RPC-Anfrage."""
    rid = request.get("id")
    method = request.get("method", "")
    params = request.get("params") or {}

    def ok(result: Any) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def err(code: int, message: str) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {"code": code, "message": message},
        }

    if method == "initialize":
        return ok(
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "personal-os", "version": "0.1.0"},
            }
        )
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "resources/list":
        return ok({"resources": []})
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            result = _dispatch(core, name, args)
        except Exception as exc:  # noqa: BLE001
            return err(-32603, str(exc))
        return ok(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            result, ensure_ascii=False, indent=2, default=str
                        ),
                    }
                ],
                "isError": False,
            }
        )
    if rid is None:
        return None
    return err(-32601, f"Methode nicht gefunden: {method}")


def _dispatch(core: PersonalOS, name: str, args: Dict[str, Any]) -> Any:
    if name == "pos_capture":
        return core.capture(
            args.get("content", ""),
            kind=args.get("kind", "note"),
            source=args.get("source", "mcp"),
            tags=args.get("tags", []),
        )
    if name == "pos_ask":
        return core.ask(args.get("query", ""), limit=int(args.get("limit", 5)))
    if name == "pos_today":
        return core.today()
    if name == "pos_digest_text":
        return {
            "text": core.weekly_text() if args.get("weekly") else core.digest_text()
        }
    if name == "pos_add_loop":
        return core.add_loop_from_text(args.get("text", ""))
    if name == "pos_list_loops":
        return core.list_loops(status=args.get("status", "open"))
    if name == "pos_complete_loop":
        return core.complete_loop(args.get("loop_id", ""))
    if name == "pos_delegate":
        d = core.delegate(
            args.get("instruction", ""), agent=args.get("agent", "default")
        )
        return core.run_delegation(d["id"])
    if name == "pos_list_delegations":
        return core.list_delegations(status=args.get("status") or None)
    if name == "pos_sync":
        return core.sync()
    if name == "pos_stats":
        return core.stats()
    raise ValueError(f"Unbekanntes Tool: {name}")


def serve(core: PersonalOS, stdin=None, stdout=None) -> None:
    """stdio-Schleife: liest JSON-RPC-Zeilen von stdin, antwortet auf stdout."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        else:
            response = handle_request(core, request)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


def main(data_dir: str = None) -> None:
    core = PersonalOS(data_dir)
    serve(core)
