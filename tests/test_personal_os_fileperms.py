"""Regressionstests: Dateiberechtigungen (Echtbetrieb-Gate).

Neue POS_HOME-Verzeichnisse muessen 0700 sein, sensible Dateien
(config.json, store.db, kg.json, Backups) 0600 - auch bei umask 000.
Bestehende Verzeichnisse duerfen NICHT ungefragt veraendert werden;
``permission_report`` meldet Abweichungen nur.
"""

import os
import stat
import tempfile
import unittest
from pathlib import Path

from personal_os.core import PersonalOS
from personal_os.fileperms import (
    DIR_MODE,
    FILE_MODE,
    ensure_private_dir,
    permission_report,
    secure_file,
)

POSIX = os.name == "posix"


def mode_of(path) -> int:
    return stat.S_IMODE(Path(path).stat().st_mode)


@unittest.skipUnless(POSIX, "chmod-Modi nur auf POSIX")
class FilePermsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = str(Path(self.tmp.name) / "pos_home")
        self._old_umask = os.umask(0o000)  # haertester Fall: nichts wird abgezogen
        self.addCleanup(os.umask, self._old_umask)

    def test_new_data_dir_is_0700_even_with_umask_000(self):
        created = ensure_private_dir(self.data_dir)
        self.assertTrue(created)
        self.assertEqual(mode_of(self.data_dir), DIR_MODE)

    def test_existing_dir_is_not_changed(self):
        Path(self.data_dir).mkdir(parents=True)
        os.chmod(self.data_dir, 0o755)
        created = ensure_private_dir(self.data_dir)
        self.assertFalse(created)
        self.assertEqual(mode_of(self.data_dir), 0o755)

    def test_personalos_creates_dir_0700_and_files_0600(self):
        core = PersonalOS(self.data_dir)
        self.addCleanup(core.close)
        self.assertEqual(mode_of(self.data_dir), DIR_MODE)
        self.assertEqual(mode_of(Path(self.data_dir) / "config.json"), FILE_MODE)
        self.assertEqual(mode_of(Path(self.data_dir) / "store.db"), FILE_MODE)
        core.capture("Test-Eintrag für Berechtigungsprüfung", source="test")
        self.assertEqual(mode_of(Path(self.data_dir) / "kg.json"), FILE_MODE)

    def test_backup_file_is_0600(self):
        core = PersonalOS(self.data_dir)
        self.addCleanup(core.close)
        core.capture("Backup-Test", source="test")
        dest = str(Path(self.tmp.name) / "backup" / "store_backup.db")
        core.store.backup(dest)
        self.assertEqual(mode_of(dest), FILE_MODE)

    def test_secure_file_tightens_loose_file(self):
        p = Path(self.tmp.name) / "loose.db"
        p.write_text("x", encoding="utf-8")
        os.chmod(p, 0o644)
        secure_file(p)
        self.assertEqual(mode_of(p), FILE_MODE)

    def test_permission_report_flags_loose_entries_without_changing_them(self):
        core = PersonalOS(self.data_dir)
        self.addCleanup(core.close)
        os.chmod(self.data_dir, 0o755)
        db = Path(self.data_dir) / "store.db"
        os.chmod(db, 0o644)
        report = permission_report(self.data_dir)
        by_path = {e["path"]: e for e in report}
        self.assertFalse(by_path[str(self.data_dir)]["ok"])
        self.assertFalse(by_path[str(db)]["ok"])
        # nicht-mutierend:
        self.assertEqual(mode_of(self.data_dir), 0o755)
        self.assertEqual(mode_of(db), 0o644)
        # nach secure_file + neuem Report ok:
        secure_file(db)
        report2 = permission_report(self.data_dir)
        by_path2 = {e["path"]: e for e in report2}
        self.assertTrue(by_path2[str(db)]["ok"])

    def test_reopen_tightens_managed_files_but_not_existing_dir(self):
        core = PersonalOS(self.data_dir)
        core.close()
        os.chmod(self.data_dir, 0o755)
        os.chmod(Path(self.data_dir) / "config.json", 0o644)
        os.chmod(Path(self.data_dir) / "store.db", 0o644)
        core2 = PersonalOS(self.data_dir)
        self.addCleanup(core2.close)
        self.assertEqual(mode_of(self.data_dir), 0o755)
        self.assertEqual(mode_of(Path(self.data_dir) / "config.json"), FILE_MODE)
        self.assertEqual(mode_of(Path(self.data_dir) / "store.db"), FILE_MODE)

    def test_stats_exposes_file_permissions_report(self):
        core = PersonalOS(self.data_dir)
        self.addCleanup(core.close)
        stats = core.stats()
        self.assertIn("file_permissions", stats)
        kinds = {e["kind"] for e in stats["file_permissions"]}
        self.assertIn("dir", kinds)
        self.assertTrue(all(e["ok"] for e in stats["file_permissions"]))


if __name__ == "__main__":
    unittest.main()
