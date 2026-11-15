"""Integrationsabnahme WP1+WP3+WP2: >=10 realistische End-to-End-Verlaeufe
(Capture -> Kontextobjekt -> Commitment -> Attention -> Daily Digest)."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from personal_os import PersonalOS
from personal_os.scopes import PRIVATE, WORK

T0 = datetime(2026, 11, 14, 8, 0)  # Samstag
TODAY = T0.date().isoformat()


class IntegrationCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = str(Path(self.tmp.name) / "pos")
        self.os = PersonalOS(self.data_dir)
        self.addCleanup(self.os.close)

    def flow(self, text, scope=PRIVATE, source="email:1", now=T0):
        item = self.os.capture(text, scope=scope, source=source)
        att = self.os.attention_points(now=now)
        return item, att

    def digest(self, now=T0, scope=None):
        return self.os.digest_text(now=now, scope=scope)


class TestTenEndToEndFlows(IntegrationCase):
    def test_flow_1_email_request_becomes_clarification_then_committed(self):
        item, att = self.flow(
            "Kannst du mir die Unterlagen bis Donnerstag schicken?",
            scope=WORK,
            source="email:req1",
        )
        com = item["commitments"][0]["object"]
        self.assertEqual(com["status"], "mentioned")
        self.assertEqual(com["scope"], WORK)
        a = next(i for i in att["items"] if i["object_id"] == com["id"])
        self.assertEqual(a["category"], "clarification")
        self.os.commitments.confirm(com["id"])
        att2 = self.os.attention_points(now=T0)
        a2 = next(i for i in att2["items"] if i["object_id"] == com["id"])
        self.assertEqual(a2["status"], "committed")
        self.assertIn("Aufmerksamkeitspunkte", self.digest())

    def test_flow_2_own_promise_overdue_escalates_over_time(self):
        item, _ = self.flow(
            "Ich schicke dir die Unterlagen bis Montag.", source="chat:1"
        )
        com = item["commitments"][0]["object"]
        att_t0 = self.os.attention_points(now=T0)
        score_t0 = next(i for i in att_t0["items"] if i["object_id"] == com["id"])[
            "score"
        ]
        later = T0 + timedelta(days=8)
        att_later = self.os.attention_points(now=later)
        item_later = next(i for i in att_later["items"] if i["object_id"] == com["id"])
        self.assertGreater(item_later["score"], score_t0)
        self.assertIn("überfällig", item_later["reason"])
        self.assertEqual(item_later["category"], "action")
        self.assertEqual(item_later["priority"], "p1")
        self.assertIn("überfällig", self.digest(now=later))

    def test_flow_3_multi_message_same_commitment_dedup_and_due_change_conflict(self):
        self.flow("Ich schicke dir die Unterlagen bis Montag.", source="email:a")
        item2, _ = self.flow(
            "Ich schicke dir die Unterlagen bis Dienstag.", source="email:b"
        )
        objs = [o for o in self.os.commitments.list() if "Unterlagen" in o["title"]]
        self.assertEqual(len(objs), 2)
        self.assertTrue(any(o.get("conflict_with") for o in objs))
        first = [o for o in objs if not o.get("conflict_with")][0]
        self.assertEqual(self.os.context.conflicts(first["id"])[0]["id"], objs[1]["id"])

    def test_flow_4_person_continuity_across_messages(self):
        self.os.context.add_object(
            type_="person", title="Anna", scope=PRIVATE, source="manual"
        )
        item, _ = self.flow(
            "Ich rufe Anna wegen des Vertrags morgen an.", source="email:1"
        )
        com = item["commitments"][0]["object"]
        person = self.os.context.list(type_="person")[0]
        links = self.os.context.links(com["id"])
        self.assertTrue(any(lnk["target_id"] == person["id"] for lnk in links))

    def test_flow_5_project_blocking_chain(self):
        proj = self.os.context.add_object(type_="project", title="Phoenix", scope=WORK)
        item, _ = self.flow(
            "Ich schicke den Phoenix-Releaseplan.", scope=WORK, source="email:p"
        )
        com = item["commitments"][0]["object"]
        self.os.context.link(com["id"], proj["id"], "blocks", provenance="integration")
        att = self.os.attention_points(now=T0, scope=WORK)
        a = next(i for i in att["items"] if i["object_id"] == com["id"])
        self.assertIn("blocked", a["factors"])
        self.assertIn("Phoenix", a["reason"])

    def test_flow_6_private_vs_work_mixed_day(self):
        self.flow("Ich rufe die Krankenkasse an.", scope=PRIVATE, source="note:1")
        self.flow("Ich schicke den Sprint-Bericht.", scope=WORK, source="email:9")
        priv = self.os.attention_points(now=T0, scope=PRIVATE)
        work = self.os.attention_points(now=T0, scope=WORK)
        self.assertTrue(all(i["scope"] == PRIVATE for i in priv["items"]))
        self.assertTrue(all(i["scope"] == WORK for i in work["items"]))
        self.assertFalse(any("Krankenkasse" in i["title"] for i in work["items"]))
        d_work = self.digest(scope=WORK)
        self.assertNotIn("Krankenkasse", d_work)
        self.assertIn("Sprint-Bericht", d_work)

    def test_flow_7_done_commitment_leaves_attention(self):
        item, att = self.flow("Ich schicke dir die Unterlagen.", source="email:d")
        com = item["commitments"][0]["object"]
        self.os.commitments.close(com["id"], "done")
        att2 = self.os.attention_points(now=T0)
        self.assertFalse(any(i["object_id"] == com["id"] for i in att2["items"]))
        d = self.digest()
        if "Aufmerksamkeitspunkte" in d:
            section = d.split("Aufmerksamkeitspunkte", 1)[1]
            self.assertNotIn("Unterlagen", section.split("##")[0])

    def test_flow_8_goal_visible_alongside_urgent(self):
        self.os.context.add_object(type_="goal", title="Fitness 2027", scope=PRIVATE)
        self.flow("Ich schicke die Unterlagen.", source="email:g")
        d = self.os.today(now=T0)
        full = self.os.attention_points(now=T0)
        goal_item = next(i for i in full["items"] if i["object_type"] == "goal")
        self.assertIn("importance", goal_item["factors"])
        self.assertLessEqual(len(d["attention"]), 3)

    def test_flow_9_clarification_for_low_confidence_request(self):
        item, att = self.flow(
            "Kannst du mir vielleicht den Bericht schicken?", scope=WORK
        )
        com = item["commitments"][0]["object"]
        self.assertEqual(com["status"], "mentioned")
        a = next(i for i in att["items"] if i["object_id"] == com["id"])
        self.assertEqual(a["category"], "clarification")

    def test_flow_10_external_rest_sees_only_work_end_to_end(self):
        os.environ["POS_TOKEN"] = "tok"
        try:
            from starlette.testclient import TestClient

            from personal_os.server import create_app

            self.flow("Ich rufe die Krankenkasse an.", scope=PRIVATE, source="n:1")
            self.flow("Ich schicke den Bericht.", scope=WORK, source="e:1")
            client = TestClient(create_app(self.os))
            h = {"Authorization": "Bearer tok"}
            att = client.get("/attention", headers=h).json()
            self.assertTrue(all(i["scope"] == WORK for i in att["items"]))
            self.assertNotIn("Krankenkasse", json.dumps(att))
            dg = client.get("/digest", headers=h).json()["text"]
            self.assertNotIn("Krankenkasse", dg)
            coms = client.get("/commitments", headers=h).json()
            self.assertTrue(all(c["scope"] == WORK for c in coms))
        finally:
            os.environ.pop("POS_TOKEN")


class TestUsabilityReport(IntegrationCase):
    def test_full_digest_and_weekly_rendered(self):
        self.os.context.add_object(type_="goal", title="Gesundheit", scope=PRIVATE)
        self.flow("Ich schicke dir die Unterlagen bis Montag.", source="email:1")
        self.flow("Kannst du mir den Bericht schicken?", scope=WORK, source="email:2")
        self.os.add_loop("Zahnarzt morgen wichtig #gesundheit", scope=PRIVATE)
        d = self.digest()
        w = self.os.weekly_text(now=T0)
        for needle in (
            "Tages-Digest",
            "Aufmerksamkeitspunkte",
            "Zahnarzt",
            "Unterlagen",
        ):
            self.assertIn(needle, d)
        for needle in ("Wochen-Review", "Aufmerksamkeit", "Wissensspeicher"):
            self.assertIn(needle, w)
        self.assertLessEqual(d.count("\n- "), 40)


if __name__ == "__main__":
    unittest.main()
