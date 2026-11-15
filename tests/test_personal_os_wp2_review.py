"""WP2-Abnahme: Praxiskorpus + Negativtests (Basis 01edc6a)."""

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from personal_os import PersonalOS
from personal_os.scopes import PRIVATE, WORK

NOW = datetime(2026, 11, 14, 8, 0)  # Samstag
TODAY = NOW.date().isoformat()


class ReviewCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = str(Path(self.tmp.name) / "pos")
        self.os = PersonalOS(self.data_dir)
        self.addCleanup(self.os.close)

    def com(self, text, scope=PRIVATE, due=None, confidence=None, status=None):
        found = self.os.commitments.scan_text(text, scope=scope)
        if not found:
            raise AssertionError(f"kein Commitment erkannt: {text}")
        obj = found[0]["object"]
        meta = dict(obj.get("meta") or {})
        if due:
            meta["due"] = due
        upd = {"meta": meta}
        if confidence is not None:
            upd["confidence"] = confidence
        if status:
            upd["status"] = status
        self.os.store.update_context_object(obj["id"], upd)
        return self.os.context.get(obj["id"])

    def item_for(self, obj_id, ev=None):
        ev = ev or self.os.attention_points(now=NOW)
        return next((i for i in ev["items"] if i["object_id"] == obj_id), None)


class TestPraxisCorpus(ReviewCase):
    """20 Alltagsszenarien; Erwartungen fachlich begruendet."""

    def test_corpus(self):
        c_overdue = self.com("Ich schicke die Unterlagen.", due="2026-11-10")
        c_today = self.com("Ich schicke den Bericht.", due=TODAY)
        c_soon = self.com("Ich rufe den Kunden an.", due="2026-11-16")
        c_nodue = self.com("Ich kümmere mich um die Steuer.", status="committed")
        c_request = self.com("Kannst du mir X schicken?", status="mentioned")
        c_foreign = self.com(
            "Anna hat zugesagt, die Liste zu liefern.", due="2026-11-13"
        )
        c_lowconf = self.com(
            "Ich schicke vielleicht die Akte.", confidence=0.4, due="2026-11-20"
        )
        goal = self.os.context.add_object(
            type_="goal", title="Gesundheit", scope=PRIVATE
        )
        proj = self.os.context.add_object(type_="project", title="Umzug", scope=PRIVATE)
        c_blocked = self.com(
            "Ich schicke die Umzugsliste.", due="2026-12-01", status="committed"
        )
        self.os.context.link(c_blocked["id"], proj["id"], "blocks")
        loop_routine = self.os.add_loop("Wäsche waschen", scope=PRIVATE)
        loop_stale = self.os.add_loop("Alte Sache", scope=PRIVATE)
        self.os.store.update_loop(
            loop_stale["id"], {"updated_at": "2026-10-01T00:00:00+00:00"}
        )
        loop_snoozed = self.os.add_loop("Verschobene Aufgabe", scope=PRIVATE, due=TODAY)
        self.os.snooze_loop(loop_snoozed["id"], days=5)
        c_done = self.com("Ich schicke die alten Unterlagen.")
        self.os.commitments.close(c_done["id"], "done")

        ev = self.os.attention_points(now=NOW)
        by = {i["object_id"]: i for i in ev["items"]}

        self.assertEqual(by[c_overdue["id"]]["category"], "action")
        self.assertGreater(by[c_overdue["id"]]["score"], by[c_today["id"]]["score"])
        self.assertGreater(by[c_today["id"]]["score"], by[c_soon["id"]]["score"])
        self.assertEqual(by[c_today["id"]]["category"], "action")
        self.assertEqual(by[c_nodue["id"]]["category"], "clarification")
        self.assertIn("keine Frist hinterlegt", by[c_nodue["id"]]["missing_info"])
        self.assertEqual(by[c_request["id"]]["status"], "mentioned")
        self.assertEqual(by[c_foreign["id"]]["category"], "action")
        self.assertEqual(by[c_lowconf["id"]]["category"], "clarification")
        self.assertTrue(
            any(
                "geringe Erkennungskonfidenz" in m
                for m in by[c_lowconf["id"]]["missing_info"]
            )
        )
        self.assertIn("importance", by[goal["id"]]["factors"])
        self.assertGreater(by[goal["id"]]["score"], 5)
        self.assertIn("blocked", by[c_blocked["id"]]["factors"])
        self.assertEqual(by[loop_routine["id"]]["category"], "observe")
        self.assertNotIn(
            "keine Frist hinterlegt", by[loop_routine["id"]]["missing_info"]
        )
        self.assertIn("stale", by[loop_stale["id"]]["factors"])
        self.assertNotIn(loop_snoozed["id"], by)
        self.assertNotIn(c_done["id"], by)

    def test_goal_not_displaced_by_urgency_in_top3(self):
        goal = self.os.context.add_object(
            type_="goal", title="Langfristziel", scope=PRIVATE
        )
        for i in range(5):
            self.com(f"Ich schicke Unterlage {i}.", due=f"2026-11-1{i}")
        ev = self.os.attention_points(now=NOW, limit=3)
        self.assertEqual(len(ev["items"]), 3)
        scores = [i["score"] for i in ev["items"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        full = self.os.attention_points(now=NOW)
        g = self.item_for(goal["id"], full)
        self.assertIsNotNone(g)
        self.assertIn("importance", g["factors"])

    def test_repeated_snooze_raises_attention(self):
        lp = self.os.add_loop("Wiederholt verschoben", scope=PRIVATE)
        self.os.snooze_loop(lp["id"], days=1)
        self.os.snooze_loop(lp["id"], days=1)
        lp = self.os.store.get_loop(lp["id"])
        self.assertEqual(lp["meta"]["snooze_count"], 2)
        self.os.store.update_loop(lp["id"], {"snooze_until": None})
        ev = self.os.attention_points(now=NOW)
        item = self.item_for(lp["id"], ev)
        self.assertIn("snooze_repeat", item["factors"])
        self.assertIn("wiederholt verschoben", item["reason"])


class TestIntegrityAndInterfaces(ReviewCase):
    def test_eval_growth_bounded(self):
        obj = self.com("Ich schicke die Unterlagen.", due="2026-11-10")
        for _ in range(25):
            self.os.attention_points(now=NOW)
        rows = self.os.store.list_attention_evals(object_id=obj["id"])
        self.assertLessEqual(len(rows), 10)
        self.assertTrue(all(r["evaluated_at"] for r in rows))
        self.assertTrue(all(r["scope"] == PRIVATE for r in rows))

    def test_evaluate_does_not_touch_operational_data(self):
        obj = self.com("Ich schicke die Unterlagen.", due="2026-11-10")
        lp = self.os.add_loop("Loop", scope=PRIVATE, due=TODAY)
        before_obj = self.os.context.get(obj["id"])
        before_loop = self.os.store.get_loop(lp["id"])
        self.os.attention_points(now=NOW)
        self.assertEqual(before_obj, self.os.context.get(obj["id"]))
        self.assertEqual(before_loop, self.os.store.get_loop(lp["id"]))

    def test_empty_db(self):
        ev = self.os.attention_points(now=NOW)
        self.assertEqual(ev["items"], [])
        self.assertIn("Tages-Digest", self.os.digest_text(now=NOW))
        self.assertIn("Wochen-Review", self.os.weekly_text(now=NOW))

    def test_rest_invalid_limit_400_and_external_scope(self):
        os.environ["POS_TOKEN"] = "tok"
        try:
            from starlette.testclient import TestClient

            from personal_os.server import create_app

            self.com("Ich rufe die Krankenkasse an.", scope=PRIVATE, due="2026-11-10")
            self.com("Ich schicke den Bericht.", scope=WORK, due="2026-11-10")
            client = TestClient(create_app(self.os))
            h = {"Authorization": "Bearer tok"}
            self.assertEqual(
                client.get("/attention?limit=abc", headers=h).status_code, 400
            )
            r = client.get("/attention", headers=h).json()
            self.assertTrue(all(i["scope"] == WORK for i in r["items"]))
            self.assertNotIn("Krankenkasse", json.dumps(r))
        finally:
            os.environ.pop("POS_TOKEN")

    def test_digest_caps_at_three_with_12_competing(self):
        for i in range(12):
            self.os.add_loop(
                f"Aufgabe {i}", scope=PRIVATE, due=f"2026-11-{10 + (i % 5):02d}"
            )
        d = self.os.today(now=NOW)
        self.assertLessEqual(len(d["attention"]), self.os.config.adhd.attention_points)
        scores = [a["score"] for a in d["attention"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        text = self.os.digest_text(now=NOW)
        self.assertIn("Aufmerksamkeitspunkte", text)

    def test_mcp_attention_and_scope(self):
        from personal_os.mcp_server import handle_request

        self.com("Ich rufe die Krankenkasse an.", scope=PRIVATE, due="2026-11-10")
        self.com("Ich schicke den Bericht.", scope=WORK, due="2026-11-10")
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
        self.assertTrue(all(i["scope"] == WORK for i in payload["items"]))

    def test_sort_stable_for_equal_scores(self):
        a = self.os.add_loop("Alpha", scope=PRIVATE)
        b = self.os.add_loop("Beta", scope=PRIVATE)
        ev = self.os.attention_points(now=NOW)
        items = [i for i in ev["items"] if i["object_id"] in (a["id"], b["id"])]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["score"], items[1]["score"])
        ev2 = self.os.attention_points(now=NOW)
        self.assertEqual(
            [i["object_id"] for i in ev["items"]],
            [i["object_id"] for i in ev2["items"]],
        )


class TestTwentyScenarios(ReviewCase):
    """20 Szenarien mit unterschiedlichen Kombinationen aus Frist/Verbindlichkeit/
    Wichtigkeit/Unsicherheit/Abhaengigkeiten, komplett durch die Engine bewertet."""

    SCENARIOS = [
        # (text, due, status, confidence, erwartung)
        ("Ich schicke die Unterlagen.", "2026-11-08", "committed", 0.9, "action/p1"),
        ("Ich schicke den Bericht.", TODAY, "committed", 0.9, "action"),
        ("Ich rufe den Kunden an.", "2026-11-16", "committed", 0.9, "action"),
        ("Ich schicke die Akte.", "2026-11-20", "committed", 0.9, "action/p2"),
        ("Ich kümmere mich um die Steuer.", None, "committed", 0.9, "clarification"),
        ("Kannst du mir X schicken?", None, "mentioned", 0.75, "clarification"),
        ("Anna hat zugesagt, zu liefern.", "2026-11-13", "committed", 0.85, "action"),
        (
            "Ich schicke vielleicht die Mappe.",
            "2026-11-25",
            "intent",
            0.4,
            "clarification",
        ),
        ("Ich will das Projekt starten.", None, "intent", 0.6, "clarification"),
        ("Der Termin ist abgesagt.", None, "rejected", 0.85, "EXCLUDED"),
        ("Ich habe die Unterlagen bereits geschickt.", None, "done", 0.9, "EXCLUDED"),
        (
            "Ich schicke die Liste nächste Woche.",
            "2026-11-23",
            "committed",
            0.9,
            "observe",
        ),
        (
            "Ich rufe die Versicherung an.",
            "2026-11-11",
            "committed",
            0.5,
            "action+lowconf",
        ),
        ("Ich schicke den Vertrag.", None, "mentioned", 0.5, "clarification"),
        (
            "Kannst du den Antrag stellen?",
            "2026-11-15",
            "mentioned",
            0.75,
            "clarification",
        ),
        ("Ich schicke die Rechnung.", "2026-11-09", "intent", 0.7, "action-ish"),
        ("Ich schicke die Umzugskartons.", "2026-12-20", "committed", 0.9, "observe"),
        ("Ich will für die Prüfung lernen.", None, "intent", 0.6, "clarification"),
        ("Ich schicke die Fotos.", "2026-11-30", "mentioned", 0.4, "clarification"),
        ("Ich rufe den Arzt an.", TODAY, "committed", 0.3, "action+clarification"),
    ]

    def test_20_scenarios(self):
        ids = []
        for text, due, status, conf, _ in self.SCENARIOS:
            obj = self.com(text, due=due, status=status, confidence=conf)
            ids.append((obj["id"], text, _))
        ev = self.os.attention_points(now=NOW)
        by = {i["object_id"]: i for i in ev["items"]}
        for oid, text, want in ids:
            with self.subTest(text=text):
                if want == "EXCLUDED":
                    self.assertNotIn(oid, by)
                    continue
                self.assertIn(oid, by, f"fehlender Aufmerksamkeitspunkt: {text}")
                item = by[oid]
                cat = want.split("/")[0].split("+")[0]
                if cat in ("action", "clarification", "observe"):
                    self.assertEqual(
                        item["category"],
                        cat,
                        f"{text}: Kategorie {item['category']} != {cat}",
                    )
                self.assertTrue(item["reason"])
                self.assertIn("evaluated_at", item)
        overdue_first = by[ids[0][0]]
        self.assertEqual(overdue_first["priority"], "p1")
        self.assertGreater(overdue_first["score"], 60)


if __name__ == "__main__":
    unittest.main()
