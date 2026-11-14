"""MCP-Client-Connector: holt Daten aus externen MCP-Servern (stdio) ins OS."""

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, List, Optional

from .base import Connector, ConnectorError


class MCPClientConnector(Connector):
    """Ruft ein konfiguriertes Tool eines externen MCP-Servers auf und captured es.

    Config: {"command": ["..."], "args": [...], "tool": "name", "arguments": {...},
             "max_chars": 8000}
    """

    name = "mcp"

    def sync(self) -> int:
        cmd = self.config.get("command") or []
        tool = self.config.get("tool", "")
        if not cmd or not tool:
            return 0
        try:
            proc = subprocess.Popen(
                list(cmd) + list(self.config.get("args", [])),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError as exc:
            raise ConnectorError(f"MCP-Server nicht startbar: {exc}") from exc
        try:
            self._send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "personal-os", "version": "0.1"},
                    },
                },
            )
            self._send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            result = self._send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": tool,
                        "arguments": self.config.get("arguments", {}),
                    },
                },
            )
        finally:
            try:
                proc.terminate()
            except OSError:
                pass
        content_parts: List[str] = []
        for item in (result or {}).get("result", {}).get("content", []):
            if item.get("type") == "text":
                content_parts.append(item.get("text", ""))
        text = "\n".join(content_parts)
        if not text:
            return 0
        max_chars = int(self.config.get("max_chars", 8000))
        item = self.core.capture(
            text[:max_chars], kind="mcp", source=f"mcp:{tool}", tags=["mcp", tool]
        )
        return 0 if item.get("duplicate") else 1

    def _send(self, proc, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            return None
        try:
            return json.loads(line)
        except ValueError:
            return None
