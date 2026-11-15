"""Tests fuer Connectors, REST-API (Loopback) und MCP-Server des Personal OS."""

import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from personal_os import PersonalOS
from personal_os.connectors import sync_all
from personal_os.connectors.web import parse_rss
from personal_os.mcp_server import handle_request
from personal_os.server import LOOPBACK_HOSTS, create_app

RSS_SAMPLE = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed</title>
<item><title>A1</title><link>https://ex.com/1</link><description>d1</description></item>
<item><title>A2</title><link>https://ex.com/2</link><description>d2</description></item>
</channel></rss>"""


class ConnectorTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = str(Path(self.tmp.name) / "pos")
        self.os = PersonalOS(self.data_dir)
        self.addCleanup(self.os.close)


class TestConnectors(ConnectorTestCase):
    def test_filesystem_connector(self):
        notes = Path(self.tmp.name) / "notes"
        notes.mkdir()
        (notes / "a.md").write_text("Notiz A ueber KI-Agenten", encoding="utf-8")
        (notes / "b.txt").write_text("Notiz B ueber Graphen", encoding="utf-8")
        (notes / ".hidden.md").write_text("versteckt", encoding="utf-8")
        self.os.config.connectors["filesystem"] = {"path": str(notes)}
        result = sync_all(self.os)
        self.assertEqual(result["filesystem"]["captured"], 2)
        self.assertIsNone(result["filesystem"]["error"])
        again = sync_all(self.os)
        self.assertEqual(again["filesystem"]["captured"], 0)

    def test_git_connector(self):
        repo = Path(self.tmp.name) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "t@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Tester"], check=True
        )
        (repo / "f.txt").write_text("hallo", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-qm", "erstes Commit"], check=True
        )
        self.os.config.connectors["git"] = {"path": str(repo)}
        result = sync_all(self.os)
        self.assertEqual(result["git"]["captured"], 1)
        self.assertIn("erstes Commit", self.os.ask("Commit")["results"][0]["content"])

    def test_unknown_connector_error_isolated(self):
        self.os.config.connectors["gibtsnicht"] = {}
        result = sync_all(self.os)
        self.assertIn("Unbekannter Connector", result["gibtsnicht"]["error"])
        result = sync_all(self.os, only="nichtdaconfig")
        self.assertIn("nicht konfiguriert", result["nichtdaconfig"]["error"])

    def test_parse_rss(self):
        items = parse_rss(RSS_SAMPLE)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "A1")

    def test_email_connector_without_config_is_noop(self):
        for var in ("POS_EMAIL_HOST", "POS_EMAIL_USER", "POS_EMAIL_PASSWORD"):
            os.environ.pop(var, None)
        self.os.config.connectors["email"] = {}
        result = sync_all(self.os)
        self.assertEqual(result["email"]["captured"], 0)


class TestServer(ConnectorTestCase):
    def setUp(self):
        super().setUp()
        os.environ.pop("POS_TOKEN", None)

    def _client(self):
        from starlette.testclient import TestClient

        return TestClient(create_app(self.os))

    def test_health_capture_ask_stats(self):
        client = self._client()
        self.assertEqual(client.get("/health").json()["status"], "ok")
        r = client.post(
            "/capture", json={"content": "Server-Test Phoenix", "tags": ["api"]}
        )
        self.assertEqual(r.status_code, 200)
        r = client.post("/ask", json={"query": "Phoenix Server-Test", "limit": 3})
        self.assertTrue(r.json()["results"])
        self.assertIn("items", client.get("/stats").json()["memory"])

    def test_today_digest_loops_delegate_sync(self):
        client = self._client()
        client.post("/loops/add", json={"text": "Server Loop heute wichtig"})
        today = client.get("/today").json()
        self.assertEqual(len(today["due_today"]), 1)
        self.assertIn("Tages-Digest", client.get("/digest").json()["text"])
        d = client.post(
            "/delegate",
            json={"instruction": "Was weiß ich über Server-Test?", "run": True},
        ).json()
        self.assertEqual(d["status"], "done")
        self.assertEqual(len(client.get("/delegations").json()), 1)
        loops = client.get("/loops?status=open").json()
        done = client.post(f"/loops/{loops[0]['id']}/done").json()
        self.assertEqual(done["status"], "done")
        notes = Path(self.tmp.name) / "notes"
        notes.mkdir(exist_ok=True)
        (notes / "x.md").write_text("Sync-Test", encoding="utf-8")
        self.os.config.connectors["filesystem"] = {"path": str(notes)}
        sync_result = client.post("/sync").json()
        self.assertIn("filesystem", sync_result)
        self.assertEqual(sync_result["filesystem"]["captured"], 1)

    def test_token_auth_enforced(self):
        os.environ["POS_TOKEN"] = "geheim123"
        try:
            client = self._client()
            self.assertEqual(client.get("/health").status_code, 401)
            ok = client.get("/health", headers={"Authorization": "Bearer geheim123"})
            self.assertEqual(ok.status_code, 200)
        finally:
            os.environ.pop("POS_TOKEN")

    def test_loopback_only(self):
        self.assertIn("127.0.0.1", LOOPBACK_HOSTS)
        with self.assertRaises(RuntimeError):
            from personal_os.server import main as serve_main

            serve_main(data_dir=self.data_dir, host="0.0.0.0")


class TestMCPServer(ConnectorTestCase):
    def test_initialize_tools_list(self):
        init = handle_request(
            self.os, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        self.assertEqual(init["result"]["serverInfo"]["name"], "personal-os")
        tools = handle_request(
            self.os, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        names = {t["name"] for t in tools["result"]["tools"]}
        self.assertIn("pos_capture", names)
        self.assertIn("pos_ask", names)
        self.assertIn("pos_delegate", names)

    def test_tool_call_capture_and_ask(self):
        r = handle_request(
            self.os,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "pos_capture",
                    "arguments": {"content": "MCP Test Eintrag KI", "tags": ["mcp"]},
                },
            },
        )
        self.assertFalse(r["result"]["isError"])
        r = handle_request(
            self.os,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "pos_ask", "arguments": {"query": "KI MCP Test"}},
            },
        )
        payload = json.loads(r["result"]["content"][0]["text"])
        self.assertTrue(payload["results"])

    def test_tool_call_add_loop_and_today(self):
        handle_request(
            self.os,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "pos_add_loop",
                    "arguments": {"text": "MCP Loop morgen"},
                },
            },
        )
        today = handle_request(
            self.os,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "pos_today", "arguments": {}},
            },
        )
        payload = json.loads(today["result"]["content"][0]["text"])
        self.assertEqual(payload["counts"]["open_loops"], 1)

    def test_unknown_method_and_tool(self):
        r = handle_request(self.os, {"jsonrpc": "2.0", "id": 9, "method": "nope"})
        self.assertEqual(r["error"]["code"], -32601)
        r = handle_request(
            self.os,
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "gibts_nicht", "arguments": {}},
            },
        )
        self.assertEqual(r["error"]["code"], -32603)

    def test_serve_stdio_roundtrip(self):
        from personal_os.mcp_server import serve

        inp = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n"
        )
        out = io.StringIO()
        serve(self.os, stdin=inp, stdout=out)
        response = json.loads(out.getvalue().strip())
        self.assertEqual(response["result"], {})


if __name__ == "__main__":
    unittest.main()
