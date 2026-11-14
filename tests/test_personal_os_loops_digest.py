"""Tests fuer Loops, Digest und Wochen-Review des Personal OS."""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from personal_os import PersonalOS
from personal_os.digest import build_digest, build_weekly, render_digest, render_weekly

NOW = datetime(2025, 5, 12, 8, 30)  # Montag


class LoopsDigestTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = str(Path(self.tmp.name) / "pos")
        self.os = PersonalOS(self.data_dir)
        self.addCleanup(self.os.close)


class TestLoops(LoopsDigestTestCase):
    def test_add_from_text(self):
        loop = self.os.add_loop_from_text("Zahnarzt morgen wichtig #gesundheit")
        expected_due = (datetime.now() + timedelta(days=1)).date().isoformat()
        self.assertEqual(loop["due"], expected_due)
        self.assertEqual(loop["priority"], 2)
        self.assertEqual(loop["status"], "open")

    def test_complete(self):
        loop = self.os.add_loop_from_text("Einkaufen heute")
        done = self.os.complete_loop(loop["id"])
        self.assertEqual(done["status"], "done")
        self.assertTrue(done["done_at"])
        self.assertEqual(self.os.list_loops("open"), [])

    def test_complete_recurring_creates_next(self):
        today = datetime.now().date()
        loop = self.os.add_loop(
            "Woechentliches Review", due=today.isoformat(), repeat="weekly"
        )
        self.os.complete_loop(loop["id"])
        open_loops = self.os.list_loops("open")
        self.assertEqual(len(open_loops), 1)
        self.assertEqual(open_loops[0]["due"], (today + timedelta(days=7)).isoformat())

    def test_snooze(self):
        loop = self.os.add_loop_from_text("Steuererklaerung")
        snoozed = self.os.snooze_loop(loop["id"], days=2)
        expected = (datetime.now() + timedelta(days=2)).date().isoformat()
        self.assertEqual(snoozed["snooze_until"], expected)

    def test_overdue_and_stale(self):
        old = self.os.add_loop("Alte Sache ohne Datum")
        self.os.store.update_loop(
            old["id"], {"updated_at": "2025-04-01T00:00:00+00:00"}
        )
        self.os.add_loop("Ueberfaellig", due="2025-05-10")
        overdue = self.os.loops.overdue(NOW)
        self.assertEqual([lp["title"] for lp in overdue], ["Ueberfaellig"])
        stale = self.os.loops.stale(NOW)
        self.assertEqual([lp["title"] for lp in stale], ["Alte Sache ohne Datum"])

    def test_top_thing_priority(self):
        self.os.add_loop("Niedrige Prio", priority=1)
        top = self.os.add_loop("Wichtige Prio", priority=3, due="2025-05-12")
        self.assertEqual(self.os.loops.top_thing(NOW)["id"], top["id"])


class TestDigest(LoopsDigestTestCase):
    def test_digest_sections(self):
        self.os.add_loop("Ueberfaellig dringend", due="2025-05-10", priority=3)
        self.os.add_loop("Heute faellig", due="2025-05-12")
        self.os.add_loop("Bald faellig", due="2025-05-14")
        old = self.os.add_loop("Stale Ding")
        self.os.store.update_loop(
            old["id"], {"updated_at": "2025-04-01T00:00:00+00:00"}
        )
        self.os.capture("Neuer Eintrag zum Thema KI-Agenten.", kind="note")
        d = build_digest(self.os, NOW)
        self.assertEqual(d["date"], "2025-05-12")
        self.assertEqual(len(d["overdue"]), 1)
        self.assertEqual(len(d["due_today"]), 1)
        self.assertEqual(len(d["due_soon"]), 1)
        self.assertEqual(len(d["stale"]), 1)
        self.assertIsNotNone(d["top_thing"])
        self.assertGreaterEqual(d["counts"]["recent_items_24h"], 1)

    def test_digest_caps_sections(self):
        for i in range(10):
            self.os.add_loop(f"Ueberfaellig {i}", due="2025-05-01")
        d = build_digest(self.os, NOW)
        self.assertEqual(len(d["overdue"]), self.os.config.adhd.max_items_per_section)

    def test_render_digest_german(self):
        self.os.add_loop("Zahnarzt morgen #gesundheit")
        self.os.capture("Neues Wissen.")
        text = render_digest(build_digest(self.os, NOW), "Jonny")
        self.assertIn("Tages-Digest", text)
        self.assertIn("Jonny", text)
        self.assertIn("Zahnarzt", text)

    def test_weekly(self):
        loop = self.os.add_loop("Erledigt diese Woche", due="2025-05-12")
        self.os.complete_loop(loop["id"])
        w = build_weekly(self.os, NOW)
        self.assertEqual(len(w["done_loops_week"]), 1)
        text = render_weekly(w, "Jonny")
        self.assertIn("Wochen-Review", text)

    def test_os_digest_text_methods(self):
        self.os.add_loop("Test Loop heute", due="2025-05-12")
        self.assertIn("Tages-Digest", self.os.digest_text(now=NOW))
        self.assertIn("Wochen-Review", self.os.weekly_text(now=NOW))


if __name__ == "__main__":
    unittest.main()
