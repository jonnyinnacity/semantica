"""Tests fuer Delegation / AgentRunner des Personal OS."""

import tempfile
import unittest
from pathlib import Path

from personal_os import PersonalOS


class DelegateTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = str(Path(self.tmp.name) / "pos")
        self.os = PersonalOS(self.data_dir)
        self.addCleanup(self.os.close)


class TestDelegation(DelegateTestCase):
    def test_delegate_creates_loop_via_rule_agent(self):
        d = self.os.delegate(
            "Erinnere mich daran, den Zahnarzt morgen anzurufen #gesundheit"
        )
        result = self.os.run_delegation(d["id"])
        self.assertEqual(result["status"], "done")
        self.assertTrue(result["trace"])
        self.assertEqual(result["trace"][0]["tool"], "loop_add")
        loops = self.os.list_loops("open")
        self.assertEqual(len(loops), 1)
        self.assertIn("Zahnarzt", loops[0]["title"])
        self.assertTrue(loops[0]["due"])

    def test_delegate_ask_uses_memory(self):
        self.os.capture(
            "Projekt Phoenix: Budget 50k, Team Berlin, Start Juni.", tags=["phoenix"]
        )
        d = self.os.delegate("Was weiß ich über Projekt Phoenix Budget?")
        result = self.os.run_delegation(d["id"])
        self.assertEqual(result["status"], "done")
        self.assertIn("Phoenix", result["result"])
        self.assertEqual(result["trace"][0]["tool"], "memory_ask")

    def test_run_pending(self):
        d = self.os.delegate("Was weiß ich über Nix?")
        self.assertEqual(self.os.list_delegations(status="pending")[0]["id"], d["id"])
        done = self.os.run_pending_delegations()
        self.assertEqual(done[0]["status"], "done")
        self.assertEqual(self.os.list_delegations(status="pending"), [])

    def test_list_delegations(self):
        self.os.delegate("Aufgabe A")
        self.os.delegate("Aufgabe B")
        self.assertEqual(len(self.os.list_delegations()), 2)

    def test_missing_delegation(self):
        self.assertIsNone(self.os.run_delegation("unbekannt"))


if __name__ == "__main__":
    unittest.main()
