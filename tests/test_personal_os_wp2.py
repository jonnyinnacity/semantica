"""WP2-Tests: Attention Engine (Bewertung, Erklaerbarkeit, Dedup, Scope, Read-only)."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from personal_os import PersonalOS
from personal_os.scopes import PRIVATE, WORK

NOW = datetime(2026, 11, 14, 8, 0)  # Samstag
TODAY = NOW.date().isoformat()


class WP2TestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = str(Path(self.tmp.name) / "pos")
        self.os = PersonalOS(self.data_dir)
        self.addCleanup(self.os.close)

    def _commitment(self, text, scope=PRIVATE, due=None, confidence=None, status=None):
        found = self.os.commitments.scan_text(text, scope=scope)
        obj = found[0]["object"]
        if due or confidence is not None or status:
            meta = dict(obj.get("meta") or {})
            if due:
                meta["due"] = due
            self.os.store.update_context_object(
                obj["id"],
                {
                    "meta": meta,
                    **({"confidence": confidence} if confidence is not None else {}),
                    **({"status": status} if status else {}),
                },
            )
            obj = self.os.context.get(obj["id"])
        return obj


class TestScoring(WP2TestCase):
    def test_overdue_beats_future(self):
        old = self._commitment("Ich schicke die Unterlagen.", due="2026-11-10")
        future = self._commitment("Ich schicke den Bericht.", due="2026-11-20")
        ev = self.os.attention_points(now=NOW)
        by_id = {i["object_id"]: i for i in ev["items"]}
        self.assertGreater(by_id[old["id"]]["score"], by_id[future["id"]]["score"])
        self.assertIn("overdue", by_id[old["id"]]["factors"])
        self.assertEqual(by_id[old["id"]]["category"], "action")
        self.assertIn("überfällig", by_id[old["id"]]["reason"])

    def test_due_today_is_action(self):
        obj = self._commitment("Ich schicke die Unterlagen.", due=TODAY)
        ev = self.os.attention_points(now=NOW)
        item = [i for i in ev["items"] if i["object_id"] == obj["id"]][0]
        self.assertEqual(item["category"], "action")
        self.assertIn("heute fällig", item["reason"])

    def test_low_confidence_not_downgraded_but_clarification(self):
        low = self._commitment(
            "Ich schicke die Unterlagen.", confidence=0.4, due="2026-11-30"
        )
        high = self._commitment(
            "Ich schicke den Bericht.", confidence=0.95, due="2026-11-30"
        )
        ev = self.os.attention_points(now=NOW)
        by_id = {i["object_id"]: i for i in ev["items"]}
        self.assertEqual(by_id[low["id"]]["score"], by_id[high["id"]]["score"])
        self.assertEqual(by_id[low["id"]]["category"], "clarification")
        self.assertTrue(
            any(
                "geringe Erkennungskonfidenz" in m
                for m in by_id[low["id"]]["missing_info"]
            )
        )
        self.assertEqual(by_id[high["id"]]["category"], "observe")

    def test_missing_due_and_responsible_flagged(self):
        obj = self._commitment("Ich kümmere mich drum.", due=None)
        req = self.os.commitments.scan_text("Kannst du mir den Bericht schicken?")[0][
            "object"
        ]
        ev = self.os.attention_points(now=NOW)
        by_id = {i["object_id"]: i for i in ev["items"]}
        self.assertIn("keine Frist hinterlegt", by_id[obj["id"]]["missing_info"])
        self.assertTrue(
            any(
                "keine verantwortliche Person" in m
                for m in by_id[req["id"]]["missing_info"]
            )
        )

    def test_dependency_via_existing_link_only(self):
        proj = self.os.context.add_object(type_="project", title="Phoenix", scope=WORK)
        com = self._commitment(
            "Ich schicke die Unterlagen.", scope=WORK, due="2026-11-16"
        )
        self.os.context.link(com["id"], proj["id"], "blocks", provenance="test")
        ev = self.os.attention_points(now=NOW, scope=WORK)
        item = [i for i in ev["items"] if i["object_id"] == com["id"]][0]
        self.assertIn("blocked", item["factors"])
        self.assertIn("Phoenix", item["reason"])
        alone = self._commitment(
            "Ich schicke den Bericht.", scope=WORK, due="2026-11-16"
        )
        ev2 = self.os.attention_points(now=NOW, scope=WORK)
        item2 = [i for i in ev2["items"] if i["object_id"] == alone["id"]][0]
        self.assertNotIn("blocked", item2["factors"])

    def test_done_rejected_expired_excluded(self):
        done = self._commitment("Ich schicke die Unterlagen.")
        self.os.commitments.close(done["id"], "done")
        rej = self._commitment("Ich schicke den Bericht.")
        self.os.store.update_context_object(rej["id"], {"status": "rejected"})
        past = (NOW - timedelta(days=2)).date().isoformat()
        exp = self.os.context.add_object(
            type_="event", title="Abgelaufen", valid_until=past
        )
        ev = self.os.attention_points(now=NOW)
        ids = {i["object_id"] for i in ev["items"]}
        self.assertNotIn(done["id"], ids)
        self.assertNotIn(rej["id"], ids)
        self.assertNotIn(exp["id"], ids)

    def test_dedup_same_theme_once(self):
        self.os.commitments.scan_text("Ich schicke dir die Unterlagen.")
        self.os.add_loop("Ich schicke die Unterlagen", scope=PRIVATE)
        ev = self.os.attention_points(now=NOW)
        titles = [i["title"] for i in ev["items"]]
        self.assertEqual(len(titles), len(set(titles)))

    def test_read_only_no_status_change(self):
        obj = self._commitment("Ich schicke die Unterlagen.", due="2026-11-10")
        before = self.os.context.get(obj["id"])
        self.os.attention_points(now=NOW)
        after = self.os.context.get(obj["id"])
        self.assertEqual(before["status"], after["status"])
        self.assertEqual(before["history"], after["history"])


class TestExplainability(WP2TestCase):
    def test_reproducible_and_explained(self):
        self._commitment("Ich schicke die Unterlagen.", due="2026-11-10")
        a = self.os.attention_points(now=NOW)
        b = self.os.attention_points(now=NOW)

        def strip(ev):
            return [
                {k: v for k, v in i.items() if k != "evaluated_at"} for i in ev["items"]
            ]

        self.assertEqual(strip(a), strip(b))
        item = a["items"][0]
        for key in (
            "object_id",
            "scope",
            "score",
            "priority",
            "category",
            "factors",
            "reason",
            "sources",
            "evaluated_at",
            "missing_info",
        ):
            self.assertIn(key, item)
        self.assertTrue(item["evaluated_at"])
        evals = self.os.store.list_attention_evals(object_id=item["object_id"])
        self.assertTrue(evals)
        self.assertEqual(evals[0]["score"], item["score"])


class TestScopeAndInterfaces(WP2TestCase):
    def test_private_not_in_work(self):
        self._commitment(
            "Ich rufe die Krankenkasse an.", scope=PRIVATE, due="2026-11-10"
        )
        self._commitment("Ich schicke den Bericht.", scope=WORK, due="2026-11-10")
        work = self.os.attention_points(now=NOW, scope=WORK)
        self.assertTrue(all(i["scope"] == WORK for i in work["items"]))
        self.assertFalse(any("Krankenkasse" in i["title"] for i in work["items"]))
        all_ev = self.os.attention_points(now=NOW)
        self.assertEqual(len(all_ev["items"]), 2)

    def test_rest_external_work_only(self):
        os.environ["POS_TOKEN"] = "tok"
        try:
            from starlette.testclient import TestClient

            from personal_os.server import create_app

            self._commitment(
                "Ich rufe die Krankenkasse an.", scope=PRIVATE, due="2026-11-10"
            )
            self._commitment("Ich schicke den Bericht.", scope=WORK, due="2026-11-10")
            client = TestClient(create_app(self.os))
            h = {"Authorization": "Bearer tok"}
            r = client.get("/attention", headers=h).json()
            self.assertTrue(all(i["scope"] == WORK for i in r["items"]))
            self.assertNotIn("Krankenkasse", json.dumps(r))
            r = client.get("/attention?scope=private", headers=h)
            self.assertEqual(r.status_code, 403)
        finally:
            os.environ.pop("POS_TOKEN")

    def test_mcp_attention(self):
        from personal_os.mcp_server import handle_request

        self._commitment("Ich schicke den Bericht.", scope=WORK, due="2026-11-10")
        r = handle_request(
            self.os,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "pos_attention", "arguments": {"scope": "work"}},
            },
        )
        payload = json.loads(r["result"]["content"][0]["text"])
        self.assertEqual(len(payload["items"]), 1)
        self.assertIn("reason", payload["items"][0])

    def test_digest_and_weekly_include_attention(self):
        self._commitment("Ich schicke die Unterlagen.", due="2026-11-10")
        d = self.os.today(now=NOW)
        self.assertIn("attention", d)
        self.assertEqual(len(d["attention"]), 1)
        self.assertLessEqual(len(d["attention"]), self.os.config.adhd.attention_points)
        text = self.os.digest_text(now=NOW)
        self.assertIn("Aufmerksamkeitspunkte", text)
        self.assertIn("überfällig", text)
        w = self.os.weekly_text(now=NOW)
        self.assertIn("Aufmerksamkeit", w)


if __name__ == "__main__":
    unittest.main()
