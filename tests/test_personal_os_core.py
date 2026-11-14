"""Tests fuer Kern, Config, Store, Memory und Inbox des Personal OS."""

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from personal_os import PersonalOS
from personal_os.config import OSConfig
from personal_os.extract import (
    extract_entities,
    extract_triplets,
    next_due,
    parse_due,
    parse_loop,
)


class PersonalOSTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = str(Path(self.tmp.name) / "pos")
        self.os = PersonalOS(self.data_dir)
        self.addCleanup(self.os.close)


class TestConfig(PersonalOSTestCase):
    def test_default_config_created(self):
        cfg_path = Path(self.data_dir) / "config.json"
        self.assertTrue(cfg_path.exists())
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.assertEqual(data["server"]["host"], "127.0.0.1")
        self.assertEqual(data["adhd"]["max_items_per_section"], 5)

    def test_env_pos_home(self):
        with tempfile.TemporaryDirectory() as other:
            os.environ["POS_HOME"] = other
            try:
                self.assertEqual(OSConfig.resolve_data_dir(), other)
            finally:
                del os.environ["POS_HOME"]

    def test_roundtrip(self):
        self.os.config.profile_name = "Jonny"
        self.os.config.save()
        reloaded = OSConfig.load(self.data_dir)
        self.assertEqual(reloaded.profile_name, "Jonny")


class TestExtract(unittest.TestCase):
    def test_entities_german_nouns_and_tags(self):
        ents = extract_entities(
            "Projekt Phoenix mit Maria in Berlin #wichtig @jonny https://example.com/x"
        )
        ids = {e["id"] for e in ents}
        self.assertIn("#wichtig", ids)
        self.assertIn("@jonny", ids)
        self.assertIn("https://example.com/x", ids)
        self.assertTrue(any("Phoenix" in i for i in ids))

    def test_triplets(self):
        trips = extract_triplets("Maria leitet das Projekt Phoenix bei Acme.")
        self.assertTrue(
            any(t["predicate"] == "leitet" and t["subject"] == "Maria" for t in trips)
        )

    def test_parse_due_relative(self):
        now = datetime(2025, 5, 12, 9, 0)  # Montag
        self.assertEqual(parse_due(" mach X morgen", now), "2025-05-13")
        self.assertEqual(parse_due("heute", now), "2025-05-12")
        self.assertEqual(parse_due("in 3 tagen", now), "2025-05-15")
        self.assertEqual(parse_due("Freitag", now), "2025-05-16")
        self.assertEqual(parse_due("15.06.2025", now), "2025-06-15")

    def test_parse_loop_full(self):
        now = datetime(2025, 5, 12, 9, 0)
        parsed = parse_loop(
            "Zahnarzttermin morgen wichtig #gesundheit → Anruf in der Praxis", now
        )
        self.assertEqual(parsed["due"], "2025-05-13")
        self.assertEqual(parsed["priority"], 2)
        self.assertIn("gesundheit", parsed["tags"])
        self.assertIn("Anruf in der Praxis", parsed["next_action"])

    def test_next_due_repeat(self):
        self.assertEqual(
            next_due("2025-05-10", "daily", datetime(2025, 5, 12)), "2025-05-12"
        )
        self.assertEqual(
            next_due("2025-05-10", "weekly", datetime(2025, 5, 12)), "2025-05-17"
        )


class TestMemoryAndInbox(PersonalOSTestCase):
    def test_capture_and_dedup(self):
        item = self.os.capture(
            "Projekt Phoenix startet im Juni mit Team Berlin.",
            kind="note",
            tags=["phoenix"],
        )
        self.assertFalse(item["duplicate"])
        again = self.os.capture("Projekt Phoenix startet im Juni mit Team Berlin.")
        self.assertTrue(again["duplicate"])
        self.assertEqual(self.os.store.count_items(), 1)

    def test_capture_empty_rejected(self):
        with self.assertRaises(ValueError):
            self.os.capture("   ")

    def test_entities_and_triplets_stored(self):
        item = self.os.capture("Maria leitet Projekt Phoenix bei Acme in Berlin.")
        stored = self.os.store.get_item(item["id"])
        self.assertTrue(stored["entities"])
        self.assertTrue(any(t["predicate"] == "leitet" for t in stored["triplets"]))
        self.assertTrue(stored["embedding"])

    def test_semantic_search_finds_relevant(self):
        self.os.capture("Projekt Phoenix: Kickoff im Juni, Team Berlin, Budget 50k.")
        self.os.capture("Rezept fuer Pancakes: Mehl, Eier, Milch, Prise Salz.")
        self.os.capture("Meeting-Notiz: Urlaubsplanung im August mit der Familie.")
        result = self.os.ask(
            "Wann ist das Kickoff von Phoenix und welches Budget?", limit=3
        )
        self.assertTrue(result["results"])
        self.assertIn("Phoenix", result["results"][0]["content"])

    def test_ask_returns_related_entities(self):
        self.os.capture(
            "Maria leitet das Projekt Phoenix. Phoenix hat ein Budget von 50k."
        )
        result = self.os.ask("Projekt Phoenix")
        self.assertIsInstance(result["related_entities"], list)

    def test_capture_file(self):
        p = Path(self.tmp.name) / "notiz.md"
        p.write_text("Wichtig: Steuererklaerung bis 31.07. #steuer", encoding="utf-8")
        item = self.os.capture_file(str(p))
        self.assertEqual(item["kind"], "file")
        self.assertEqual(item["source"], str(p))

    def test_persistence_across_reopen(self):
        self.os.capture("Dauerhaftes Wissen ueber KI-Systeme.", tags=["ki"])
        self.os.close()
        reopened = PersonalOS(self.data_dir)
        self.addCleanup(reopened.close)
        result = reopened.ask("KI-Systeme")
        self.assertTrue(any("KI-Systeme" in r["content"] for r in result["results"]))

    def test_kg_json_written(self):
        self.os.capture("Berlin ist die Hauptstadt von Deutschland.")
        kg = json.loads((Path(self.data_dir) / "kg.json").read_text(encoding="utf-8"))
        self.assertTrue(kg["entities"])


if __name__ == "__main__":
    unittest.main()
