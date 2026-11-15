"""WP3-Abnahme: unabhaengige Negativtests + frischer Satzkorpus (A5) gegen f8344cd."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from personal_os import PersonalOS
from personal_os.commitments import classify
from personal_os.scopes import PRIVATE, WORK


class ReviewCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = str(Path(self.tmp.name) / "pos")
        self.os = PersonalOS(self.data_dir)
        self.addCleanup(self.os.close)


class TestA1Corpus(ReviewCase):
    """Frischer Korpus; Erwartungen dokumentieren FP/FN-Fehlklassifikationen."""

    CASES = [
        (
            "Ich schicke dir die Unterlagen bis Donnerstag.",
            "committed",
            "own_commitment",
        ),
        ("Ich verspreche, dass ich morgen anrufe.", "committed", "own_commitment"),
        ("Das schaffe ich bestimmt bis Montag.", "committed", "own_commitment"),
        ("Ich kümmere mich drum.", "committed", "own_commitment"),
        (
            "Kannst du mir den Bericht bis morgen schicken?",
            "mentioned",
            "request_to_me",
        ),
        (
            "Anna hat zugesagt, bis Freitag zu liefern.",
            "committed",
            "foreign_commitment",
        ),
        ("Ich will das Projekt starten.", "intent", "intent"),
        ("Wir sollten mal das Büro aufräumen.", "intent", "intent"),
        ("Ich nehme mir vor, öfter Sport zu machen.", "intent", "intent"),
        ("Ich entscheide mich nächste Woche.", "intent", "intent"),
        (
            "Ich schicke die Unterlagen vielleicht nächste Woche.",
            "intent",
            "hypothetical",
        ),
        ("Ich glaube, ich schicke es nächste Woche.", "intent", "hypothetical"),
        ("Morgen muss ich zum Arzt.", "mentioned", "obligation"),
        ("Der Termin ist abgesagt.", "rejected", "rejected"),
        ("Ich habe die Unterlagen bereits geschickt.", "done", "done"),
        ("Die Unterlagen sind unterwegs.", "done", "done"),
        ("Kannst du mir sagen, wann du kommst?", None, None),
        ("Kannst du das nicht machen?", None, None),
        ("Kannst du nicht einfach aufhören?", None, None),
        ("Bis wann brauchst du die Unterlagen?", None, None),
        ("Projekt Phoenix startet im Juni mit Team Berlin.", None, None),
        ("Rezept: Mehl, Eier, Milch, Salz.", None, None),
    ]

    def test_corpus_classification(self):
        for text, want_status, want_kind in self.CASES:
            with self.subTest(text=text):
                r = classify(text)
                if want_status is None:
                    self.assertIsNone(r)
                else:
                    self.assertIsNotNone(r)
                    self.assertEqual(r["status"], want_status)
                    self.assertEqual(r["kind"], want_kind)

    def test_no_unbegruendete_verbindlichkeit(self):
        for text, _, _ in self.CASES:
            r = classify(text)
            if r and r["status"] == "committed":
                with self.subTest(text=text):
                    self.assertNotIn("vielleicht", text.lower())
                    self.assertNotIn("glaube", text.lower())

    def test_multiple_commitments_in_one_message(self):
        found = self.os.commitments.scan_text(
            "Ich schicke dir die Unterlagen und rufe dich morgen an."
        )
        self.assertEqual(len(found), 2)
        self.assertTrue(all(f["object"]["status"] == "committed" for f in found))
        self.assertEqual(len(self.os.commitments.list()), 2)


class TestA2LifecycleIntegrity(ReviewCase):
    def test_variant_wording_dedup(self):
        self.os.commitments.scan_text("Ich schicke dir die Unterlagen bis Donnerstag.")
        again = self.os.commitments.scan_text(
            "Ich schicke die Unterlagen bis Donnerstag."
        )
        self.assertTrue(again[0]["duplicate"])
        self.assertEqual(len(self.os.commitments.list()), 1)

    def test_changed_due_is_conflict_not_overwrite(self):
        a = self.os.commitments.scan_text("Ich schicke die Unterlagen bis Donnerstag.")[
            0
        ]["object"]
        b = self.os.commitments.scan_text("Ich schicke die Unterlagen bis Freitag.")[0]
        self.assertFalse(b["duplicate"])
        self.assertEqual(b["object"].get("conflict_with"), a["id"])
        self.assertEqual(self.os.context.get(a["id"])["status"], "committed")

    def test_full_transition_matrix_on_commitment(self):
        obj = self.os.commitments.scan_text("Kannst du mir X schicken?")[0]["object"]
        self.assertEqual(obj["status"], "mentioned")
        obj = self.os.commitments.confirm(obj["id"])
        self.assertEqual(obj["status"], "committed")
        obj = self.os.commitments.close(obj["id"], "done")
        self.assertEqual(obj["status"], "done")
        self.assertEqual(len(obj["history"]), 3)
        with self.assertRaises(ValueError):
            self.os.context.transition(obj["id"], "mentioned")
        with self.assertRaises(ValueError):
            self.os.context.transition(obj["id"], "intent")

    def test_provenance_and_history_preserved(self):
        item = self.os.capture(
            "Ich schicke dir die Unterlagen bis Donnerstag.", source="email:42"
        )
        obj = item["commitments"][0]["object"]
        self.assertEqual(obj["source"], "email:42")
        self.assertEqual(obj["source_item_id"], item["id"])
        self.assertEqual(obj["history"][0]["by"], "capture")
        self.assertTrue(obj["created_at"])


class TestA3CaptureIntegration(ReviewCase):
    def test_capture_survives_detector_error(self):
        with mock.patch.object(
            self.os.commitments, "scan_item", side_effect=RuntimeError("boom")
        ):
            item = self.os.capture("Ich schicke dir X.", source="test")
        self.assertFalse(item["duplicate"])
        self.assertEqual(item["commitments"], [])
        self.assertIsNotNone(self.os.store.get_item(item["id"]))

    def test_repeated_capture_no_object_proliferation(self):
        text = "Ich schicke dir die Unterlagen bis Donnerstag."
        self.os.capture(text, source="email")
        self.os.capture(text, source="email")
        self.os.capture(text, source="email")
        self.assertEqual(len(self.os.commitments.list()), 1)
        self.assertEqual(self.os.store.count_items(), 1)

    def test_item_link_stable(self):
        item = self.os.capture("Kannst du mir den Bericht schicken?", scope=WORK)
        obj = item["commitments"][0]["object"]
        self.assertEqual(obj["scope"], WORK)
        self.assertEqual(
            self.os.commitments.get(obj["id"])["source_item_id"], item["id"]
        )


class TestA4Privacy(ReviewCase):
    def test_private_commitment_invisible_in_work(self):
        self.os.commitments.scan_text("Ich rufe die Krankenkasse an.", scope=PRIVATE)
        self.os.commitments.scan_text("Ich schicke den Bericht.", scope=WORK)
        work = self.os.commitments.list(scope=WORK)
        self.assertEqual(len(work), 1)
        self.assertNotIn("Krankenkasse", json.dumps(work))

    def test_rest_external_blocked_on_private_transition(self):
        os.environ["POS_TOKEN"] = "tok"
        try:
            from starlette.testclient import TestClient

            from personal_os.server import create_app

            priv = self.os.commitments.scan_text(
                "Ich rufe die Krankenkasse an.", scope=PRIVATE
            )[0]["object"]
            before = self.os.commitments.get(priv["id"])["status"]
            client = TestClient(create_app(self.os))
            h = {"Authorization": "Bearer tok"}
            r = client.get("/commitments", headers=h)
            self.assertEqual(r.json(), [])
            r = client.post(
                f"/commitments/{priv['id']}/transition",
                json={"status": "done"},
                headers=h,
            )
            self.assertEqual(r.status_code, 403)
            self.assertEqual(self.os.commitments.get(priv["id"])["status"], before)
        finally:
            os.environ.pop("POS_TOKEN")

    def test_cli_scope_filter(self):
        from personal_os.cli import main

        self.os.commitments.scan_text("Ich rufe die Krankenkasse an.", scope=PRIVATE)
        self.os.commitments.scan_text("Ich schicke den Bericht.", scope=WORK)
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"POS_HOME": self.data_dir}):
            with redirect_stdout(buf):
                main(["commitments", "list", "--scope", "work"])
        self.assertIn("Bericht", buf.getvalue())
        self.assertNotIn("Krankenkasse", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
