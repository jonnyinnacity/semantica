"""WP3-Tests: Commitment-Erkennung (Zusage vs. Absicht vs. Erwaehnung), Dedup,
Lebenszyklus, Konflikte, Scope-Isolation, Capture-Integration."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from personal_os import PersonalOS
from personal_os.scopes import PRIVATE, WORK


class WP3TestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = str(Path(self.tmp.name) / "pos")
        self.os = PersonalOS(self.data_dir)
        self.addCleanup(self.os.close)


class TestRecognition(WP3TestCase):
    def test_explicit_own_promise_is_committed_not_mentioned(self):
        found = self.os.commitments.scan_text(
            "Ich schicke dir die Unterlagen bis Donnerstag.", source="email:1"
        )
        self.assertEqual(len(found), 1)
        obj = found[0]["object"]
        self.assertEqual(obj["type"], "commitment")
        self.assertEqual(obj["status"], "committed")
        self.assertGreaterEqual(obj["confidence"], 0.9)
        self.assertEqual((obj["meta"] or {}).get("due"), self._thursday())
        self.assertEqual(obj["source"], "email:1")
        self.assertEqual((obj["meta"] or {}).get("party"), "self")

    def test_request_is_mentioned_not_committed(self):
        found = self.os.commitments.scan_text(
            "Kannst du mir die Unterlagen bis Donnerstag schicken?", source="email:2"
        )
        obj = found[0]["object"]
        self.assertEqual(obj["status"], "mentioned")
        self.assertEqual((obj["meta"] or {}).get("kind"), "request_to_me")
        self.assertLess(obj["confidence"], 0.9)
        confirmed = self.os.commitments.confirm(obj["id"])
        self.assertEqual(confirmed["status"], "committed")
        self.assertEqual(len(confirmed["history"]), 2)

    def test_intent_is_not_a_commitment(self):
        found = self.os.commitments.scan_text("Ich will das Projekt Phoenix starten.")
        obj = found[0]["object"]
        self.assertEqual(obj["status"], "intent")
        self.assertNotEqual(obj["status"], "committed")

    def test_foreign_commitment_vs_own(self):
        own = self.os.commitments.scan_text("Ich rufe den Kunden morgen an.")[0][
            "object"
        ]
        other = self.os.commitments.scan_text(
            "Anna hat zugesagt, @Anna liefert bis Freitag."
        )
        self.assertEqual((own["meta"] or {}).get("party"), "self")
        self.assertEqual((own["meta"] or {}).get("responsible"), "ich")
        if other:
            self.assertEqual(
                (other[0]["object"]["meta"] or {}).get("responsible"), "@Anna"
            )

    def test_done_and_rejected_detection(self):
        done = self.os.commitments.scan_text(
            "Ich habe die Unterlagen bereits geschickt."
        )
        self.assertEqual(done[0]["object"]["status"], "done")
        rej = self.os.commitments.scan_text("Der Termin ist abgesagt.")
        self.assertEqual(rej[0]["object"]["status"], "rejected")

    def test_no_commitment_in_plain_text(self):
        self.assertEqual(
            self.os.commitments.scan_text("Projekt Phoenix startet im Juni."), []
        )
        self.assertEqual(
            self.os.commitments.scan_text("Rezept: Mehl, Eier, Milch."), []
        )

    def test_missing_due_and_responsible_allowed(self):
        found = self.os.commitments.scan_text("Ich kümmere mich drum.")
        obj = found[0]["object"]
        self.assertIsNone((obj["meta"] or {}).get("due"))
        self.assertEqual(obj["status"], "committed")

    def _thursday(self):
        from datetime import datetime, timedelta

        now = datetime.now()
        days = (3 - now.weekday()) % 7
        return (now + timedelta(days=days)).date().isoformat()


class TestDedupLifecycleConflicts(WP3TestCase):
    def test_duplicate_capture_creates_one_object(self):
        self.os.capture(
            "Ich schicke dir die Unterlagen bis Donnerstag.", source="email"
        )
        again = self.os.capture(
            "Ich schicke dir die Unterlagen bis Donnerstag.", source="email"
        )
        self.assertTrue(again["duplicate"])
        self.assertEqual(len(self.os.commitments.list()), 1)
        self.os.commitments.scan_text("Ich schicke dir die Unterlagen bis Donnerstag.")
        self.assertEqual(len(self.os.commitments.list()), 1)

    def test_done_not_reopened_by_new_mention(self):
        found = self.os.commitments.scan_text(
            "Ich schicke dir die Unterlagen bis Donnerstag."
        )
        obj = found[0]["object"]
        self.os.commitments.close(obj["id"], status="done")
        again = self.os.commitments.scan_text(
            "Ich schicke dir die Unterlagen bis Donnerstag."
        )
        self.assertTrue(again[0]["duplicate"])
        self.assertIn("nicht wieder geoeffnet", again[0]["note"])
        self.assertEqual(self.os.commitments.get(obj["id"])["status"], "done")
        self.assertEqual(
            len(
                self.os.commitments.list(status="open")
                or self.os.commitments.list(status="mentioned")
            ),
            0,
        )

    def test_conflicting_due_uses_wp1_conflict_logic(self):
        a = self.os.commitments.scan_text("Ich schicke die Unterlagen bis Donnerstag.")[
            0
        ]["object"]
        b = self.os.commitments.scan_text("Ich schicke die Unterlagen bis Freitag.")[0]
        self.assertEqual(b["object"].get("conflict_with"), a["id"])
        self.assertEqual(len(self.os.commitments.list()), 2)
        self.assertEqual(len(self.os.context.conflicts(a["id"])), 1)
        self.os.context.resolve_conflict(b["object"]["id"], keep_id=a["id"])
        self.assertEqual(len(self.os.commitments.list()), 1)

    def test_capture_integration_with_provenance(self):
        item = self.os.capture(
            "Kannst du mir den Bericht bis morgen schicken?",
            scope=WORK,
            source="email:9",
        )
        self.assertIn("commitments", item)
        self.assertEqual(len(item["commitments"]), 1)
        obj = item["commitments"][0]["object"]
        self.assertEqual(obj["source_item_id"], item["id"])
        self.assertEqual(obj["scope"], WORK)
        self.assertEqual(obj["source"], "email:9")
        self.assertEqual(obj["history"][0]["by"], "capture")


class TestScopeIsolation(WP3TestCase):
    def test_private_commitment_not_in_work(self):
        self.os.commitments.scan_text("Ich rufe die Krankenkasse an.", scope=PRIVATE)
        self.os.commitments.scan_text("Ich schicke den Bericht.", scope=WORK)
        work = self.os.commitments.list(scope=WORK)
        self.assertEqual(len(work), 1)
        self.assertIn("Bericht", work[0]["title"])
        self.assertEqual(len(self.os.commitments.list(scope=PRIVATE)), 1)
        self.assertEqual(len(self.os.commitments.list()), 2)

    def test_no_auto_upgrade_private_to_work(self):
        found = self.os.commitments.scan_text(
            "Ich schicke die Unterlagen.", scope=PRIVATE
        )
        self.assertEqual(found[0]["object"]["scope"], PRIVATE)

    def test_rest_external_sees_only_work_commitments(self):
        os.environ["POS_TOKEN"] = "tok"
        try:
            from starlette.testclient import TestClient

            from personal_os.server import create_app

            self.os.commitments.scan_text(
                "Ich rufe die Krankenkasse an.", scope=PRIVATE
            )
            self.os.commitments.scan_text(
                "Ich schicke den Bericht bis morgen.", scope=WORK
            )
            client = TestClient(create_app(self.os))
            h = {"Authorization": "Bearer tok"}
            listed = client.get("/commitments", headers=h).json()
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["scope"], WORK)
            scan_priv = client.post(
                "/commitments/scan",
                json={"text": "Ich schicke geheim.", "scope": "private"},
                headers=h,
            )
            self.assertEqual(scan_priv.status_code, 403)
            obj = self.os.commitments.list(scope=PRIVATE)[0]
            tr = client.post(
                f"/commitments/{obj['id']}/transition",
                json={"status": "committed"},
                headers=h,
            )
            self.assertEqual(tr.status_code, 403)
        finally:
            os.environ.pop("POS_TOKEN")

    def test_mcp_commitment_tools(self):
        from personal_os.mcp_server import handle_request

        r = handle_request(
            self.os,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "pos_commitments_scan",
                    "arguments": {
                        "text": "Kannst du mir X bis morgen schicken?",
                        "scope": "work",
                    },
                },
            },
        )
        payload = json.loads(r["result"]["content"][0]["text"])
        obj = payload[0]["object"]
        self.assertEqual(obj["status"], "mentioned")
        r = handle_request(
            self.os,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "pos_commitments_transition",
                    "arguments": {"object_id": obj["id"], "status": "committed"},
                },
            },
        )
        payload = json.loads(r["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], "committed")
        r = handle_request(
            self.os,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "pos_commitments_list",
                    "arguments": {"scope": "work"},
                },
            },
        )
        payload = json.loads(r["result"]["content"][0]["text"])
        self.assertEqual(len(payload), 1)


if __name__ == "__main__":
    unittest.main()
