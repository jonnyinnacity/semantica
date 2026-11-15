"""Pilotfreigabe: 7-Tage-Realitaetspruefung + Start/Backup/Restore."""

import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from personal_os import PersonalOS
from personal_os.scopes import PRIVATE, WORK


class PilotTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = str(Path(self.tmp.name) / "pilot")


class TestFreshStart(PilotTestCase):
    def test_fresh_dir_init_config_db_interfaces(self):
        os_ = PersonalOS(self.data_dir)
        self.assertTrue((Path(self.data_dir) / "config.json").exists())
        self.assertTrue((Path(self.data_dir) / "store.db").exists())
        item = os_.capture("Frischer Start funktioniert.", scope="work", source="pilot")
        self.assertFalse(item["duplicate"])
        self.assertTrue(os_.ask("Frischer Start", scope="work")["results"])
        self.assertIn("items", os_.attention_points())
        from personal_os.server import create_app

        app = create_app(os_)
        self.assertIsNotNone(app)
        from personal_os.mcp_server import handle_request

        r = handle_request(os_, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
        self.assertEqual(r["result"], {})
        os_.close()
        reopened = PersonalOS(self.data_dir)
        self.assertEqual(reopened.store.count_items(), 1)
        reopened.close()


class TestSevenDayPilot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data_dir = str(Path(cls.tmp.name) / "pilot")
        cls.m = run_pilot(cls.data_dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_at_least_30_events(self):
        self.assertGreaterEqual(self.m["events"], 30)

    def test_commitments_detected_without_unfounded_duplicates(self):
        self.assertGreaterEqual(self.m["commitments_created"], 6)
        self.assertEqual(self.m["commitments_duplicate"], 0)
        self.assertGreaterEqual(self.m["conflicts"], 1)

    def test_no_important_item_lost(self):
        att = self.m["final_attention"]
        titles = " ".join(i["title"] for i in att["items"])
        for needle in ("Steuererklärung", "Vertrag"):
            self.assertIn(needle, titles)
        os_ = PersonalOS(self.data_dir)
        try:
            closed = [
                o["id"]
                for o in os_.commitments.list()
                if o["status"] in ("done", "rejected")
            ]
            att_ids = {i["object_id"] for i in att["items"]}
            self.assertFalse(set(closed) & att_ids)
        finally:
            os_.close()

    def test_daily_attention_over_seven_days(self):
        self.assertEqual(len(self.m["daily_attention"]), 7)
        for d, v in self.m["daily_attention"].items():
            self.assertGreaterEqual(v["n"], 1)

    def test_continuity_person_link_and_snooze(self):
        self.assertTrue(self.m["person_linked"])
        self.assertEqual(self.m["snooze_count"], 2)
        self.assertTrue(self.m["goal_visible"])

    def test_scope_isolation_work_clean(self):
        self.assertTrue(self.m["work_scope_clean"])

    def test_digest_and_weekly_actionable(self):
        d, w = self.m["digest_d7"], self.m["weekly_d7"]
        self.assertIn("Tages-Digest", d)
        self.assertIn("Aufmerksamkeitspunkte", d)
        self.assertTrue(
            any(i.get("missing_info") for i in self.m["final_attention"]["items"])
        )
        self.assertIn("Wochen-Review", w)
        self.assertIn("Aufmerksamkeit", w)

    def test_backup_restore_restart(self):
        out = backup_restore_check(self.data_dir)
        self.assertEqual(out["items"], self.m["items_total"])
        self.assertEqual(out["commitments"], self.m["commitments_total"])
        self.assertEqual(out["objects"], self.m["objects_total"])


D1 = datetime(2026, 11, 9, 8, 0)  # Montag


def day(i: int) -> datetime:
    return D1 + timedelta(days=i)


def run_pilot(data_dir: str, verbose: bool = False) -> Dict[str, Any]:
    """Fuehrt die 7-Tage-Simulation durch; liefert Metriken + Texte."""
    os_ = PersonalOS(data_dir)
    m: Dict[str, Any] = {
        "events": 0,
        "duplicate_captures": 0,
        "commitments_created": 0,
        "commitments_duplicate": 0,
        "conflicts": 0,
        "daily_attention": {},
        "digest_d7": "",
        "weekly_d7": "",
        "notes": [],
    }

    def ev(text, scope=PRIVATE, source="pilot"):
        m["events"] += 1
        item = os_.capture(text, scope=scope, source=source)
        if item.get("duplicate"):
            m["duplicate_captures"] += 1
        for c in item.get("commitments", []):
            if c.get("duplicate"):
                m["commitments_duplicate"] += 1
            else:
                m["commitments_created"] += 1
                if c["object"].get("conflict_with"):
                    m["conflicts"] += 1
        return item

    def attention(i):
        res = os_.attention_points(now=day(i))
        m["daily_attention"][f"D{i+1}"] = {
            "n": len(res["items"]),
            "counts": res["counts"],
            "top": [
                {
                    "title": x["title"],
                    "priority": x["priority"],
                    "category": x["category"],
                    "score": x["score"],
                }
                for x in res["items"][:3]
            ],
        }
        return res

    person_anna = os_.context.add_object(
        type_="person", title="Anna", scope=PRIVATE, source="pilot"
    )
    os_.context.add_object(type_="goal", title="Gesundheit langfristig", scope=PRIVATE)

    # D1 (Mo): Eingang + eigene Zusagen +Dokumente
    ev(
        "Kannst du mir den Monatsbericht bis Mittwoch schicken?",
        scope=WORK,
        source="email:1",
    )
    ev("Ich schicke den Releaseplan bis Freitag.", scope=WORK, source="chat:1")
    ev(
        "Projekt Phoenix: Kickoff war produktiv, Team ist motiviert.",
        scope=WORK,
        source="notes:1",
    )
    ev(
        "Meeting-Notiz: Architektur-Review Phoenix am Donnerstag.",
        scope=WORK,
        source="notes:2",
    )
    ev("Brainstorming: neue Features für Q1 aufnehmen.", scope=WORK, source="notes:3")
    ev("Ich rufe die Krankenkasse morgen an.", scope=PRIVATE, source="note:1")
    ev(
        "Geburtstag Lisa: 3. August, Geschenk überlegen.",
        scope=PRIVATE,
        source="note:4",
    )
    ev("Versicherung: Beitragserhöhung prüfen.", scope=PRIVATE, source="note:5")
    os_.add_loop("Wäsche waschen", repeat="weekly", scope=PRIVATE)
    attention(0)

    # D2 (Di): Monatsbericht-Anfrage bleibt unbeantwortet; neue private Anfrage
    ev("Kannst du mir das Kuchenrezept schicken?", scope=PRIVATE, source="chat:2")
    ev("Ich rufe den Kunden wegen der Rechnung an.", scope=WORK, source="email:2")
    ev("Standup-Notiz: Blocker im CI besprechen.", scope=WORK, source="notes:6")
    ev("Artikel gelesen: neue RAG-Ansätze für 2027.", scope=WORK, source="web:1")
    ev("Einkaufsliste: Milch, Brot, Eier.", scope=PRIVATE, source="note:6")
    attention(1)

    # D3 (Mi): Friständerung (Konflikt), Absage, Zahnarzt-Loop
    ev("Ich schicke den Releaseplan bis Montag.", scope=WORK, source="chat:3")
    ev("Der Sprint-Review ist abgesagt.", scope=WORK, source="cal:1")
    ev("Kannst du das Ticket bis Freitag reviewen?", scope=WORK, source="chat:5")
    ev("Notiz: Steuer-ID sicher verwahren.", scope=PRIVATE, source="note:7")
    os_.add_loop("Zahnarzttermin", due=day(4).date().isoformat(), scope=PRIVATE)
    attention(2)

    # D4 (Do): Monatsbericht erledigt, Steuererklärung langfristig, Loop snooze x2
    ev("Ich habe den Monatsbericht bereits geschickt.", scope=WORK, source="email:3")
    ev(
        "Ich kümmere mich um die Steuererklärung bis 31.01.2027.",
        scope=PRIVATE,
        source="note:2",
    )
    ev("Buch Rückgabe Bibliothek bis Samstag.", scope=PRIVATE, source="note:8")
    ev("Docs aktualisiert: Onboarding für neue Devs.", scope=WORK, source="git:1")
    loop = os_.add_loop(
        "Umzugskartons packen", scope=PRIVATE, due=day(4).date().isoformat()
    )
    os_.snooze_loop(loop["id"], days=1)
    os_.snooze_loop(loop["id"], days=1)
    attention(3)

    # D5 (Fr): Releaseplan fällig; Absage privat; Anna-Zusage (fremd)
    ev("Der Impftermin ist abgesagt.", scope=PRIVATE, source="cal:2")
    ev(
        "Anna hat zugesagt, bis Samstag die Unterlagen zu liefern.",
        scope=PRIVATE,
        source="email:4",
    )
    ev("Releaseplan Phoenix ist auf dem Weg.", scope=WORK, source="chat:4")
    ev("Ich schicke die Wochenzusammenfassung.", scope=WORK, source="chat:6")
    ev("Eltern anrufen wegen Wochenende.", scope=PRIVATE, source="note:9")
    attention(4)

    # D6 (Sa): Anna-Link, Vertrag, Krankenkasse überfällig (seit D2 nicht erledigt)
    ev("Ich rufe Anna wegen des Vertrags an.", scope=PRIVATE, source="email:5")
    ev("Kannst du den Vertrag bis Dienstag prüfen?", scope=WORK, source="email:6")
    ev("Wochenend-Planung: Kino am Samstag.", scope=PRIVATE, source="note:10")
    ev("CI-Pipeline fix deployed.", scope=WORK, source="git:2")
    attention(5)

    # D7 (So): Erledigung + Wochenabschluss
    ev("Ich habe die Unterlagen von Anna bekommen.", scope=PRIVATE, source="email:7")
    ev(
        "Reflexion: Woche war intensiv, mehr Pausen einplanen.",
        scope=PRIVATE,
        source="note:11",
    )
    ev("Nächste Woche: Demo vorbereiten.", scope=WORK, source="notes:7")
    c = [o for o in os_.commitments.list(scope=PRIVATE) if "Krankenkasse" in o["title"]]
    if c:
        os_.commitments.close(c[0]["id"], "done")
    attention(6)

    m["digest_d7"] = os_.digest_text(now=day(6))
    m["weekly_d7"] = os_.weekly_text(now=day(6))
    m["commitments_total"] = len(os_.commitments.list())
    m["items_total"] = os_.store.count_items()
    m["objects_total"] = len(os_.context.list())
    m["person_linked"] = any(
        lnk["target_id"] == person_anna["id"]
        for o in os_.commitments.list(scope=PRIVATE)
        for lnk in os_.context.links(o["id"])
    )
    m["snooze_count"] = (os_.store.get_loop(loop["id"])["meta"] or {}).get(
        "snooze_count", 0
    )
    m["goal_visible"] = any(
        i["object_type"] == "goal" for i in os_.attention_points(now=day(6))["items"]
    )
    m["final_attention"] = os_.attention_points(now=day(6))
    work_att = os_.attention_points(now=day(6), scope=WORK)
    m["work_scope_clean"] = all(
        i["scope"] == WORK for i in work_att["items"]
    ) and not any(
        "Krankenkasse" in i["title"] or "Anna" in i["title"] or "Steuer" in i["title"]
        for i in work_att["items"]
    )
    if verbose:
        for k, v in m["daily_attention"].items():
            print(k, v["n"], v["counts"], [t["title"] for t in v["top"]])
    os_.close()
    return m


def backup_restore_check(data_dir: str) -> Dict[str, Any]:
    """Backup ( Kopie des Datenverzeichnisses) + Restore in neuem Verzeichnis."""
    backup = str(Path(data_dir).parent / (Path(data_dir).name + "_backup"))
    shutil.copytree(data_dir, backup)
    restored = PersonalOS(backup)
    out = {
        "items": restored.store.count_items(),
        "commitments": len(restored.commitments.list()),
        "objects": len(restored.context.list()),
    }
    restored.close()
    return out


if __name__ == "__main__":
    unittest.main()
