"""Betriebsabnahme: Backup/Restore, Netzwerk-Freiheit, pos day, Import."""

import io
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from personal_os import PersonalOS
from personal_os.cli import main as cli_main
from personal_os.scopes import PRIVATE, WORK


class OpsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = str(Path(self.tmp.name) / "pos")
        self.os = PersonalOS(self.data_dir)
        self.addCleanup(self.os.close)


class TestBackupRestore(OpsCase):
    def test_backup_of_running_db_is_consistent_and_complete(self):
        self.os.capture("Backup-Test Eintrag.", scope=WORK, source="ops")
        self.os.commitments.scan_text("Ich schicke den Bericht.", scope=WORK)
        dest = str(Path(self.tmp.name) / "backup" / "store_backup.db")
        path = self.os.store.backup(dest)
        self.assertTrue(Path(path).exists())
        conn = sqlite3.connect(path)
        self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        n_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        n_objs = conn.execute("SELECT COUNT(*) FROM context_objects").fetchone()[0]
        conn.close()
        self.assertEqual(n_items, 1)
        self.assertEqual(n_objs, 1)
        self.os.capture("Nach dem Backup.", scope=PRIVATE, source="ops")
        path2 = self.os.store.backup(str(Path(self.tmp.name) / "b2.db"))
        conn = sqlite3.connect(path2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0], 2)
        conn.close()

    def test_restore_from_backup(self):
        self.os.capture("Restore-Test.", scope=PRIVATE, source="ops")
        self.os.commitments.scan_text("Ich rufe die Krankenkasse an.", scope=PRIVATE)
        backup = self.os.store.backup(str(Path(self.tmp.name) / "bak.db"))
        self.os.close()
        shutil.copy(backup, str(Path(self.data_dir) / "store.db"))
        restored = PersonalOS(self.data_dir)
        self.addCleanup(restored.close)
        self.assertEqual(restored.store.count_items(), 1)
        self.assertEqual(len(restored.commitments.list()), 1)
        self.assertIn("Restore-Test", restored.ask("Restore")["results"][0]["content"])


class TestNoUnintendedNetwork(OpsCase):
    def test_default_operations_make_no_network_calls(self):
        def boom(*a, **kw):
            raise AssertionError("unerwarteter Netzwerkzugriff")

        with mock.patch("socket.socket.connect", side_effect=boom), mock.patch(
            "requests.post", side_effect=boom
        ), mock.patch("requests.get", side_effect=boom):
            self.os.capture("Ich schicke die Unterlagen.", scope=WORK, source="ops")
            self.os.commitments.scan_text("Kannst du mir X schicken?", scope=WORK)
            self.os.attention_points()
            self.os.digest_text()
            self.os.weekly_text()
            self.os.sync()
            d = self.os.delegate("Was weiß ich über Unterlagen?", scope=WORK)
            self.os.run_delegation(d["id"])


class TestDailyFlow(OpsCase):
    def test_pos_day_answers_five_questions_read_only(self):
        self.os.capture(
            "Ich schicke die Unterlagen bis Freitag.", scope=WORK, source="ops"
        )
        self.os.capture("Kannst du mir den Bericht schicken?", scope=WORK, source="ops")
        self.os.context.add_object(type_="goal", title="Fitness", scope=PRIVATE)
        before = self.os.store.count_items()
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"POS_HOME": self.data_dir}):
            with redirect_stdout(buf):
                cli_main(["day"])
        out = buf.getvalue()
        for marker in (
            "1) Was braucht heute",
            "2) Welche Zusagen",
            "3) Worauf warte ich",
            "4) Welche wichtigen Themen",
            "5) Welche Informationen",
        ):
            self.assertIn(marker, out)
        self.assertIn("Unterlagen", out)
        self.assertEqual(self.os.store.count_items(), before)

    def test_pos_backup_command(self):
        self.os.capture("Backup via CLI.", scope=WORK)
        dest = str(Path(self.tmp.name) / "cli_backup.db")
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"POS_HOME": self.data_dir}):
            with redirect_stdout(buf):
                cli_main(["backup", dest])
        self.assertIn("integrity_check ok", buf.getvalue())
        self.assertTrue(Path(dest).exists())


class TestControlledImport(OpsCase):
    def test_readonly_filesystem_import_is_idempotent_and_scoped(self):
        folder = Path(self.tmp.name) / "import"
        folder.mkdir()
        (folder / "a.md").write_text("Import Datei A.", encoding="utf-8")
        (folder / "b.md").write_text("Import Datei B.", encoding="utf-8")
        self.os.config.connectors["filesystem"] = {"path": str(folder), "scope": "work"}
        r1 = self.os.sync()
        r2 = self.os.sync()
        self.assertEqual(r1["filesystem"]["captured"], 2)
        self.assertEqual(r2["filesystem"]["captured"], 0)
        items = self.os.store.list_items(kind="file")
        self.assertTrue(all(i["scope"] == WORK for i in items))
        self.assertTrue(all(i["source"].startswith(str(folder)) for i in items))


class TestAccessProtection(OpsCase):
    def test_rest_loopback_only_and_token(self):
        from personal_os.server import LOOPBACK_HOSTS
        from personal_os.server import main as serve_main

        self.assertIn("127.0.0.1", LOOPBACK_HOSTS)
        with self.assertRaises(RuntimeError):
            serve_main(data_dir=self.data_dir, host="0.0.0.0")

    def test_mcp_is_stdio_only(self):
        import inspect

        from personal_os import mcp_server

        src = inspect.getsource(mcp_server.serve)
        self.assertIn("stdin", src)
        self.assertNotIn("socket", src)


if __name__ == "__main__":
    unittest.main()
