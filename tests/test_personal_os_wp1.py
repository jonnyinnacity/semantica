"""WP1-Tests: Kontextmodell, Scopes, Provenienz, Berechtigungen, Migration."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from personal_os import PersonalOS
from personal_os.permissions import PermissionManager
from personal_os.scopes import PRIVATE, WORK, redact_for_external, validate_scope

OLD_SCHEMA = """
CREATE TABLE items (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, content TEXT NOT NULL,
    source TEXT DEFAULT '', tags TEXT DEFAULT '[]', hash TEXT UNIQUE,
    entities TEXT DEFAULT '[]', triplets TEXT DEFAULT '[]',
    embedding TEXT DEFAULT '[]', created_at TEXT DEFAULT '', meta TEXT DEFAULT '{}'
);
CREATE TABLE loops (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT DEFAULT 'open',
    priority INTEGER DEFAULT 1, due TEXT, repeat TEXT, next_action TEXT DEFAULT '',
    tags TEXT DEFAULT '[]', created_at TEXT DEFAULT '', updated_at TEXT DEFAULT '',
    done_at TEXT, snooze_until TEXT, meta TEXT DEFAULT '{}'
);
"""


class WP1TestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = str(Path(self.tmp.name) / "pos")
        self.os = PersonalOS(self.data_dir)
        self.addCleanup(self.os.close)


class TestMigration(WP1TestCase):
    def test_old_database_migrated_additively(self):
        old_dir = str(Path(self.tmp.name) / "old")
        Path(old_dir).mkdir()
        conn = sqlite3.connect(str(Path(old_dir) / "store.db"))
        conn.executescript(OLD_SCHEMA)
        conn.execute(
            "INSERT INTO items (id, kind, content, hash) "
            "VALUES ('alt1', 'note', 'altes Wissen', 'h1')"
        )
        conn.execute(
            "INSERT INTO loops (id, title, status) "
            "VALUES ('loop1', 'alter Loop', 'open')"
        )
        conn.commit()
        conn.close()

        os_ = PersonalOS(old_dir)
        self.addCleanup(os_.close)
        item = os_.store.get_item("alt1")
        loop = os_.store.get_loop("loop1")
        self.assertEqual(item["content"], "altes Wissen")
        self.assertEqual(item["scope"], PRIVATE)
        self.assertEqual(loop["scope"], PRIVATE)
        tables = {
            r["name"]
            for r in os_.store.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertIn("context_objects", tables)
        self.assertIn("object_links", tables)
        self.assertIn("permissions", tables)
        result = os_.ask("altes Wissen")
        self.assertTrue(result["results"])

    def test_existing_api_still_works(self):
        item = self.os.capture("Bestehendes Verhalten bleibt.", tags=["regression"])
        self.assertFalse(item["duplicate"])
        loop = self.os.add_loop_from_text("Regressionstest morgen")
        self.assertTrue(loop["due"])
        self.assertIn("Tages-Digest", self.os.digest_text())
        self.assertIn("memory", self.os.stats())


class TestScopes(WP1TestCase):
    def test_validate_scope(self):
        self.assertEqual(validate_scope(None), PRIVATE)
        self.assertEqual(validate_scope("work"), WORK)
        with self.assertRaises(ValueError):
            validate_scope("geheim")

    def test_work_scope_never_sees_private(self):
        self.os.capture("Privat: Krankenkasse anrufen.", scope=PRIVATE)
        self.os.capture("Work: Phoenix Release planen.", scope=WORK)
        work_items = self.os.store.list_items(scope=WORK)
        self.assertEqual(len(work_items), 1)
        self.assertIn("Phoenix", work_items[0]["content"])
        work_answer = self.os.ask("Krankenkasse Phoenix Release", scope=WORK)
        self.assertTrue(all(r.get("scope") == WORK for r in work_answer["results"]))
        self.assertFalse(
            any("Krankenkasse" in r["content"] for r in work_answer["results"])
        )
        owner_answer = self.os.ask("Krankenkasse")
        self.assertTrue(
            any("Krankenkasse" in r["content"] for r in owner_answer["results"])
        )

    def test_loops_scope_filter(self):
        self.os.add_loop("Privater Loop", scope=PRIVATE)
        self.os.add_loop("Work Loop", scope=WORK)
        work_loops = self.os.list_loops(scope=WORK)
        self.assertEqual([lp["title"] for lp in work_loops], ["Work Loop"])
        self.assertEqual(len(self.os.list_loops()), 2)

    def test_redact_for_external(self):
        self.os.capture("Geheim: Steuer-ID 123456.", scope=PRIVATE)
        self.os.capture("Release Phoenix am Freitag.", scope=WORK)
        items = self.os.store.list_items()
        redacted = redact_for_external(items)
        self.assertEqual(len(redacted), 2)
        priv = [r for r in redacted if r.get("scope") == PRIVATE][0]
        work = [r for r in redacted if r.get("scope") == WORK][0]
        self.assertTrue(priv.get("redacted"))
        self.assertNotIn("content", priv)
        self.assertNotIn("123456", str(priv))
        self.assertIn("Release Phoenix", work["content"])
        allowed = redact_for_external(items, allow_private=True)
        self.assertIn("123456", str(allowed))

    def test_core_redact_uses_config(self):
        self.os.capture("Privat X", scope=PRIVATE)
        data = self.os.store.list_items()
        self.assertTrue(self.os.redact_for_external(data)[0].get("redacted"))
        self.os.config.privacy.external_can_see_private = True
        self.assertNotIn("redacted", str(self.os.redact_for_external(data)))


class TestPermissions(WP1TestCase):
    def test_defaults(self):
        pm = self.os.permissions
        self.assertIsInstance(pm, PermissionManager)
        self.assertTrue(pm.check("owner", "read", PRIVATE))
        self.assertTrue(pm.check("owner", "write", WORK))
        self.assertFalse(pm.check("external", "model_call", PRIVATE))
        self.assertTrue(pm.check("external", "model_call", WORK))
        self.assertFalse(pm.check("external", "write", WORK))
        self.assertFalse(pm.check("external", "read", PRIVATE))
        self.assertFalse(pm.can_external_model_call(PRIVATE))
        self.assertTrue(pm.can_external_model_call(WORK))

    def test_grant_revoke_override(self):
        pm = self.os.permissions
        pm.grant("external", "model_call", WORK, effect="deny")
        self.assertFalse(pm.can_external_model_call(WORK))
        pm.revoke("external", "model_call", WORK)
        self.assertTrue(pm.can_external_model_call(WORK))
        self.os.config.privacy.external_can_see_private = True
        pm2 = PermissionManager(self.os.store, self.os.config)
        pm2.grant("external", "model_call", PRIVATE)
        self.assertTrue(pm2.can_external_model_call(PRIVATE))
        pm2.revoke("external", "model_call", PRIVATE)
        self.assertFalse(pm2.can_external_model_call(PRIVATE))

    def test_config_flag_allows_private_for_external(self):
        self.os.config.privacy.external_can_see_private = True
        pm = PermissionManager(self.os.store, self.os.config)
        pm.grant("external", "model_call", PRIVATE)
        self.assertTrue(pm.can_external_model_call(PRIVATE))


class TestContextModel(WP1TestCase):
    def test_add_and_list_with_provenance(self):
        obj = self.os.context.add_object(
            type_="person",
            title="Maria",
            scope=PRIVATE,
            source="email:123",
            confidence=0.9,
        )
        self.assertEqual(obj["status"], "mentioned")
        self.assertEqual(obj["source"], "email:123")
        self.assertEqual(obj["confidence"], 0.9)
        self.assertTrue(obj["valid_from"])
        listed = self.os.context.list(type_="person", scope=PRIVATE)
        self.assertEqual(len(listed), 1)
        with self.assertRaises(ValueError):
            self.os.context.add_object(type_="alien", title="x")

    def test_status_transitions(self):
        obj = self.os.context.add_object(
            type_="commitment", title="Unterlagen schicken"
        )
        obj = self.os.context.transition(obj["id"], "intent")
        obj = self.os.context.transition(obj["id"], "committed")
        obj = self.os.context.transition(obj["id"], "done")
        self.assertEqual(obj["status"], "done")
        self.assertEqual(len(obj["history"]), 4)
        with self.assertRaises(ValueError):
            self.os.context.transition(obj["id"], "committed")

    def test_conflict_not_silently_overwritten(self):
        a = self.os.context.add_object(type_="decision", title="Urlaub im August")
        b = self.os.context.add_object(
            type_="decision",
            title="Urlaub im August",
            meta={"alternative": "September"},
        )
        self.assertEqual(b.get("conflict_with"), a["id"])
        self.assertEqual(self.os.context.get(a["id"])["title"], "Urlaub im August")
        conflicts = self.os.context.conflicts(b["id"])
        self.assertEqual(len(conflicts), 1)
        resolved = self.os.context.resolve_conflict(b["id"], keep_id=a["id"])
        self.assertEqual(resolved["superseded_by"], a["id"])
        self.assertEqual(len(self.os.context.list(type_="decision")), 1)
        self.assertEqual(
            len(self.os.context.list(type_="decision", include_superseded=True)), 2
        )

    def test_links_and_link_item(self):
        p = self.os.context.add_object(type_="person", title="Maria")
        proj = self.os.context.add_object(type_="project", title="Phoenix", scope=WORK)
        link = self.os.context.link(
            p["id"], proj["id"], "works_on", provenance="capture"
        )
        self.assertEqual(link["relation"], "works_on")
        item = self.os.capture("Maria leitet Phoenix.", scope=WORK)
        obj = self.os.context.link_item(item["id"], type_="task", title="Phoenix docs")
        self.assertEqual(obj["source_item_id"], item["id"])
        self.assertEqual(obj["scope"], WORK)


class TestDelegationPrivacy(WP1TestCase):
    def test_private_delegation_never_calls_external_llm(self):
        self.os.config.llm.provider = "openai"
        self.os.config.llm.endpoint = "http://127.0.0.1:9/v1"
        self.os.config.llm.model = "fake"
        d = self.os.delegate("Was weiß ich über private Krankenkasse?", scope=PRIVATE)
        with mock.patch(
            "requests.post", side_effect=AssertionError("kein externer Call")
        ):
            result = self.os.run_delegation(d["id"])
        self.assertEqual(result["status"], "done")
        self.assertIn("Externes Modell nicht genutzt", result["result"])

    def test_work_delegation_may_call_llm(self):
        self.os.config.llm.provider = "openai"
        self.os.config.llm.endpoint = "http://127.0.0.1:9/v1"
        self.os.config.llm.model = "fake"
        d = self.os.delegate("Was weiß ich über Phoenix?", scope=WORK)
        fake_resp = mock.Mock()
        fake_resp.json.return_value = {
            "choices": [{"message": {"content": "ok", "tool_calls": []}}]
        }
        fake_resp.raise_for_status = lambda: None
        with mock.patch("requests.post", return_value=fake_resp) as post:
            result = self.os.run_delegation(d["id"])
        self.assertEqual(result["status"], "done")
        post.assert_called_once()


class TestServerScopes(WP1TestCase):
    def setUp(self):
        super().setUp()
        os.environ.pop("POS_TOKEN", None)

    def _client(self):
        from starlette.testclient import TestClient

        from personal_os.server import create_app

        return TestClient(create_app(self.os))

    def test_owner_sees_all_external_only_work(self):
        self.os.capture("Privat: Steuer 2025.", scope=PRIVATE)
        self.os.capture("Work: Phoenix Sprint.", scope=WORK)
        client = self._client()
        owner = client.post("/ask", json={"query": "Steuer Phoenix"})
        self.assertEqual(len(owner.json()["results"]), 2)

        os.environ["POS_TOKEN"] = "tok123"
        try:
            ext = self._client()
            self.assertEqual(ext.get("/health").status_code, 401)
            h = {"Authorization": "Bearer tok123"}
            res = ext.post("/ask", json={"query": "Steuer Phoenix"}, headers=h).json()
            self.assertTrue(all(r.get("scope") == WORK for r in res["results"]))
            self.assertFalse(any("Steuer" in r["content"] for r in res["results"]))
            r = ext.post("/ask", json={"query": "x", "scope": "private"}, headers=h)
            self.assertEqual(r.status_code, 403)
            r = ext.post(
                "/capture",
                json={"content": "extern privat", "scope": "private"},
                headers=h,
            )
            self.assertEqual(r.status_code, 403)
            r = ext.post(
                "/capture", json={"content": "extern work", "scope": "work"}, headers=h
            )
            self.assertEqual(r.status_code, 403)
        finally:
            os.environ.pop("POS_TOKEN")

    def test_context_endpoints(self):
        client = self._client()
        obj = client.post(
            "/context/add",
            json={"type": "project", "title": "Phoenix", "scope": "work"},
        ).json()
        self.assertEqual(obj["scope"], WORK)
        listed = client.get("/context?scope=work").json()
        self.assertEqual(len(listed), 1)
        tr = client.post(
            f"/context/{obj['id']}/transition", json={"status": "committed"}
        ).json()
        self.assertEqual(tr["status"], "committed")


class TestMCPScopeTools(WP1TestCase):
    def test_context_tools_and_scope_ask(self):
        from personal_os.mcp_server import handle_request

        self.os.capture("Privat Wort", scope=PRIVATE)
        self.os.capture("Work Wort Phoenix", scope=WORK)
        r = handle_request(
            self.os,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "pos_ask",
                    "arguments": {"query": "Wort", "scope": "work"},
                },
            },
        )
        import json as _json

        payload = _json.loads(r["result"]["content"][0]["text"])
        self.assertTrue(all(x.get("scope") == WORK for x in payload["results"]))

        r = handle_request(
            self.os,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "pos_context_add",
                    "arguments": {
                        "type": "goal",
                        "title": "Fitness",
                        "scope": "private",
                    },
                },
            },
        )
        payload = _json.loads(r["result"]["content"][0]["text"])
        self.assertEqual(payload["type"], "goal")

        r = handle_request(
            self.os,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "pos_redact",
                    "arguments": {"data": self.os.store.list_items()},
                },
            },
        )
        payload = _json.loads(r["result"]["content"][0]["text"])
        self.assertTrue(any(x.get("redacted") for x in payload))


if __name__ == "__main__":
    unittest.main()
