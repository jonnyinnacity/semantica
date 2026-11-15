"""WP1-Abnahme: unabhaengige Negativtests und Pruefluecken (Review gegen PR #1).

Deckt A1 (Migration/Bestandsschutz), A2 (Scope-Isolation inkl. KG-Leck),
A3 (Berechtigungen), A4 (externe Modellaufrufe/Redaction), A5 (Kontextintegritaet).
"""

import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from personal_os import PersonalOS
from personal_os.permissions import PermissionManager
from personal_os.scopes import PRIVATE, WORK, redact_for_external

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
CREATE TABLE delegations (
    id TEXT PRIMARY KEY, agent TEXT NOT NULL, instruction TEXT NOT NULL,
    status TEXT DEFAULT 'pending', result TEXT DEFAULT '', trace TEXT DEFAULT '[]',
    created_at TEXT DEFAULT '', updated_at TEXT DEFAULT '', meta TEXT DEFAULT '{}'
);
CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT DEFAULT '');
"""


class ReviewTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = str(Path(self.tmp.name) / "pos")
        self.os = PersonalOS(self.data_dir)
        self.addCleanup(self.os.close)


class TestA1Migration(ReviewTestCase):
    def _make_old_db(self):
        old_dir = str(Path(self.tmp.name) / "old")
        Path(old_dir).mkdir()
        conn = sqlite3.connect(str(Path(old_dir) / "store.db"))
        conn.executescript(OLD_SCHEMA)
        conn.execute(
            "INSERT INTO items (id, kind, content, hash, meta) "
            "VALUES ('i1', 'note', 'altes Item', 'h1', '{\"k\": 1}')"
        )
        conn.execute(
            "INSERT INTO loops (id, title, status, priority) "
            "VALUES ('l1', 'alter Loop', 'open', 3)"
        )
        conn.execute(
            "INSERT INTO delegations (id, agent, instruction, status) "
            "VALUES ('d1', 'a', 'alte Delegation', 'done')"
        )
        conn.execute("INSERT INTO kv (key, value) VALUES ('conn:git:state', 'abc')")
        conn.commit()
        conn.close()
        return old_dir

    def test_migration_preserves_everything_and_is_idempotent(self):
        old_dir = self._make_old_db()
        os_ = PersonalOS(old_dir)
        kg_path = Path(old_dir) / "kg.json"
        os_.capture("neu nach Migration", scope=WORK)
        kg_path.write_text(
            json.dumps(
                {"entities": [{"id": "X"}], "relationships": [], "metadata": {}}
            ),
            encoding="utf-8",
        )
        os_.close()

        again = PersonalOS(old_dir)
        self.addCleanup(again.close)
        again.close()
        third = PersonalOS(old_dir)
        self.addCleanup(third.close)

        item = third.store.get_item("i1")
        loop = third.store.get_loop("l1")
        dele = third.store.get_delegation("d1")
        self.assertEqual(item["content"], "altes Item")
        self.assertEqual(item["meta"], {"k": 1})
        self.assertEqual(item["scope"], PRIVATE)
        self.assertEqual(loop["title"], "alter Loop")
        self.assertEqual(loop["priority"], 3)
        self.assertEqual(loop["scope"], PRIVATE)
        self.assertEqual(dele["instruction"], "alte Delegation")
        self.assertEqual(third.store.kv_get("conn:git:state"), "abc")
        kg = json.loads(kg_path.read_text(encoding="utf-8"))
        self.assertEqual(kg["entities"], [{"id": "X"}])
        res = third.ask("altes Item")
        self.assertTrue(any(r["id"] == "i1" for r in res["results"]))

    def test_repeated_init_same_dir(self):
        for _ in range(3):
            o = PersonalOS(self.data_dir)
            o.capture("init test", scope=WORK)
            o.close()
        o = PersonalOS(self.data_dir)
        self.addCleanup(o.close)
        self.assertEqual(o.store.count_items(), 1)


class TestA2ScopeIsolation(ReviewTestCase):
    def test_related_entities_do_not_leak_private_via_kg(self):
        self.os.capture("Anna leitet Orion.", scope=PRIVATE)
        self.os.capture("Orion heute.", scope=WORK)
        r = self.os.ask("Orion heute", scope=WORK)
        self.assertTrue(all(x["scope"] == WORK for x in r["results"]))
        ids = [str(e.get("id")) for e in r["related_entities"]]
        self.assertNotIn("Anna", ids)
        owner = self.os.ask("Orion heute")
        self.assertIn("Anna", [str(e.get("id")) for e in owner["related_entities"]])

    def test_today_scope_filter(self):
        today = datetime.now().date().isoformat()
        self.os.add_loop("Privater Zahnarzt", due=today, scope=PRIVATE)
        self.os.add_loop("Work Sprint", due=today, scope=WORK)
        work_today = self.os.today(scope=WORK)
        titles = [lp["title"] for lp in work_today["due_today"]]
        self.assertEqual(titles, ["Work Sprint"])
        all_today = self.os.today()
        self.assertEqual(len(all_today["due_today"]), 2)
        text_work = self.os.digest_text(scope=WORK)
        self.assertNotIn("Zahnarzt", text_work)
        self.assertIn("Zahnarzt", self.os.digest_text())

    def test_connector_default_scopes(self):
        notes = Path(self.tmp.name) / "notes"
        notes.mkdir()
        (notes / "a.md").write_text("private Notiz", encoding="utf-8")
        self.os.config.connectors["filesystem"] = {"path": str(notes)}
        self.os.sync()
        item = self.os.store.list_items(kind="file")[0]
        self.assertEqual(item["scope"], PRIVATE)

        repo = Path(self.tmp.name) / "repo"
        repo.mkdir()
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "t@e.c"],
            ["git", "config", "user.name", "T"],
        ):
            subprocess.run(cmd, cwd=repo, check=True)
        (repo / "f.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "c1"], check=True)
        self.os.config.connectors["git"] = {"path": str(repo)}
        self.os.sync()
        commit_item = self.os.store.list_items(kind="commit")[0]
        self.assertEqual(commit_item["scope"], WORK)


class TestA3Permissions(ReviewTestCase):
    def test_tie_resolves_to_deny(self):
        pm = self.os.permissions
        pm.grant("external", "read", WORK, effect="allow")
        pm.grant("external", "read", WORK, effect="deny")
        self.assertFalse(pm.check("external", "read", WORK))

    def test_specific_grant_overrides_wildcard_deny(self):
        pm = self.os.permissions
        pm.grant("external", "read", PRIVATE, effect="allow")
        self.assertTrue(pm.check("external", "read", PRIVATE))

    def test_missing_config_defaults_to_deny(self):
        pm = PermissionManager(self.os.store, None)
        self.assertFalse(pm.can_external_model_call(PRIVATE))
        self.assertFalse(pm.check("external", "write", WORK))

    def test_rest_token_cannot_escalate(self):
        os.environ["POS_TOKEN"] = "tok"
        try:
            from starlette.testclient import TestClient

            from personal_os.server import create_app

            self.os.capture("privat geheim", scope=PRIVATE)
            self.os.add_loop("privater Loop", scope=PRIVATE)
            obj = self.os.context.add_object(
                type_="goal", title="privates Ziel", scope=PRIVATE
            )
            client = TestClient(create_app(self.os))
            h = {"Authorization": "Bearer tok"}
            self.assertEqual(
                client.post(
                    "/ask", json={"query": "geheim", "scope": "private"}, headers=h
                ).status_code,
                403,
            )
            self.assertEqual(
                client.post(
                    "/capture", json={"content": "x", "scope": "private"}, headers=h
                ).status_code,
                403,
            )
            self.assertEqual(
                client.post(
                    "/context/add",
                    json={"type": "goal", "title": "y", "scope": "private"},
                    headers=h,
                ).status_code,
                403,
            )
            self.assertEqual(
                client.post(
                    f"/context/{obj['id']}/transition",
                    json={"status": "intent"},
                    headers=h,
                ).status_code,
                403,
            )
            loop = self.os.list_loops()[0]
            self.assertEqual(
                client.post(f"/loops/{loop['id']}/done", headers=h).status_code, 403
            )
            today = client.get("/today", headers=h).json()
            self.assertEqual(today["counts"]["open_loops"], 0)
            digest = client.get("/digest", headers=h).json()["text"]
            self.assertNotIn("privater Loop", digest)
            dele = client.get("/delegations", headers=h).json()
            self.assertTrue(
                all((d.get("meta") or {}).get("scope") == WORK for d in dele)
            )
            listed = client.get("/context", headers=h).json()
            self.assertTrue(all(o.get("scope") == WORK for o in listed))
        finally:
            os.environ.pop("POS_TOKEN")


class TestA4ExternalModelCalls(ReviewTestCase):
    def test_redact_delegation_payload_with_meta_scope(self):
        d = self.os.delegate("Privat: Steuer-ID 123 an Finanzamt", scope=PRIVATE)
        red = redact_for_external({"delegation": d})
        self.assertTrue(red["delegation"].get("redacted"))
        self.assertNotIn("Steuer-ID", json.dumps(red))

    def test_redact_nested_mixed_payload(self):
        priv_item = self.os.capture("Geheim 456", scope=PRIVATE)
        work_item = self.os.capture("Phoenix oeffentlich", scope=WORK)
        obj_priv = self.os.context.add_object(
            type_="decision", title=" geheim ", scope=PRIVATE
        )
        payload = {
            "items": [priv_item, work_item],
            "objects": [obj_priv],
            "nested": {"deep": [{"content": "x", "scope": PRIVATE, "id": "z"}]},
        }
        red = redact_for_external(payload)
        self.assertTrue(red["items"][0].get("redacted"))
        self.assertIn("Phoenix", red["items"][1]["content"])
        self.assertTrue(red["objects"][0].get("redacted"))
        self.assertTrue(red["nested"]["deep"][0].get("redacted"))
        self.assertNotIn("Geheim", json.dumps(red))

    def test_structural_boundary_work_object_with_private_text_passes(self):
        item = self.os.capture("Tarnung: Steuer-ID 789", scope=WORK)
        red = redact_for_external([item])
        self.assertIn("Steuer-ID", red[0]["content"])

    def test_llm_guard(self):
        runner = self.os.delegations.runner
        self.os.config.llm.provider = "openai"
        self.os.config.llm.endpoint = "http://127.0.0.1:9/v1"
        self.assertFalse(runner._llm_allowed(PRIVATE))
        self.assertTrue(runner._llm_allowed(WORK))
        self.os.config.llm.provider = "none"
        with mock.patch(
            "requests.post", side_effect=AssertionError("no external call")
        ):
            d = self.os.delegate("privat Delegation", scope=PRIVATE)
            self.os.config.llm.provider = "openai"
            result = self.os.run_delegation(d["id"])
            self.assertEqual(result["status"], "done")
            self.assertIn("Externes Modell nicht genutzt", result["result"])


class TestA5ContextIntegrity(ReviewTestCase):
    def test_all_nine_types_and_invalid_type(self):
        for type_ in (
            "person",
            "area",
            "project",
            "task",
            "commitment",
            "decision",
            "routine",
            "goal",
            "event",
        ):
            obj = self.os.context.add_object(type_=type_, title=f"t-{type_}")
            self.assertEqual(obj["type"], type_)
        with self.assertRaises(ValueError):
            self.os.context.add_object(type_="alien", title="x")

    def test_full_transition_matrix(self):
        obj = self.os.context.add_object(type_="commitment", title="Zusage")
        for status in ("intent", "committed", "done"):
            obj = self.os.context.transition(obj["id"], status)
        self.assertEqual(obj["status"], "done")
        self.assertEqual(len(obj["history"]), 4)
        with self.assertRaises(ValueError):
            self.os.context.transition(obj["id"], "mentioned")
        with self.assertRaises(ValueError):
            self.os.context.transition(obj["id"], "quatsch")

    def test_validity_expiry(self):
        past = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
        future = (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds")
        expired = self.os.context.add_object(
            type_="event", title="alt", valid_until=past
        )
        active = self.os.context.add_object(
            type_="event", title="neu", valid_until=future
        )
        listed = self.os.context.list(type_="event")
        self.assertEqual([o["title"] for o in listed], ["neu"])
        all_objs = self.os.context.list(type_="event", include_expired=True)
        self.assertEqual(len(all_objs), 2)
        self.assertEqual(expired["valid_until"], past)
        self.assertEqual(active["valid_from"] is not None, True)

    def test_conflict_resolution_keeps_both(self):
        a = self.os.context.add_object(type_="decision", title="Umzug")
        b = self.os.context.add_object(type_="decision", title="Umzug", meta={"v": 2})
        self.assertEqual(b.get("conflict_with"), a["id"])
        self.assertEqual(len(self.os.context.conflicts(a["id"])), 1)
        self.os.context.resolve_conflict(b["id"], keep_id=a["id"])
        self.assertIsNotNone(self.os.context.get(b["id"]))
        self.assertEqual(len(self.os.context.list(type_="decision")), 1)
        self.assertEqual(
            len(self.os.context.list(type_="decision", include_superseded=True)), 2
        )


class TestA6MCPNegative(ReviewTestCase):
    def test_mcp_ask_scope_work_hides_private(self):
        from personal_os.mcp_server import handle_request

        self.os.capture("Geheime Steuer-ID 999", scope=PRIVATE)
        self.os.capture("Phoenix Sprint oeffentlich", scope=WORK)
        r = handle_request(
            self.os,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "pos_ask",
                    "arguments": {"query": "Steuer-ID Phoenix", "scope": "work"},
                },
            },
        )
        payload = json.loads(r["result"]["content"][0]["text"])
        self.assertTrue(all(x.get("scope") == WORK for x in payload["results"]))
        self.assertFalse(
            any("Steuer-ID" in x.get("content", "") for x in payload["results"])
        )


if __name__ == "__main__":
    unittest.main()
