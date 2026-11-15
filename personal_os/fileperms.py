"""Dateiberechtigungen des Datenverzeichnisses (local-first).

Neue POS_HOME-Verzeichnisse werden mit 0700 angelegt; sensible Dateien
(config.json, store.db, kg.json, Backups) werden auf 0600 gesetzt. Auf
Nicht-POSIX-Systemen sind die chmod-Aufrufe no-ops.

Bestehende Installationen werden grundsaetzlich NICHT veraendert:
``permission_report`` meldet Abweichungen nur (nicht-mutierend).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Dict, List, Union

DIR_MODE = 0o700
FILE_MODE = 0o600
SENSITIVE_FILES = ("config.json", "store.db", "kg.json")


def ensure_private_dir(data_dir: Union[str, Path]) -> bool:
    """Legt das Datenverzeichnis mit 0700 an, falls es fehlt.

    Ein bereits bestehendes Verzeichnis wird nicht angefasst. Liefert True,
    wenn das Verzeichnis neu angelegt wurde.
    """
    path = Path(data_dir)
    if path.exists():
        return False
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(path, DIR_MODE)
    return True


def secure_file(path: Union[str, Path]) -> None:
    """Setzt eine sensible Datei auf 0600 (nur POSIX, sonst no-op)."""
    if os.name == "posix":
        os.chmod(path, FILE_MODE)


def permission_report(data_dir: Union[str, Path]) -> List[Dict[str, Any]]:
    """Nicht-mutierende Pruefung: meldet Gruppe/other-Zugriff auf Dir und Dateien.

    Veraendert keine Berechtigungen; liefert pro Eintrag ``ok`` (kein
    group/other-Zugriff) plus Ist-/Soll-Mode.
    """
    base = Path(data_dir)
    report: List[Dict[str, Any]] = []
    if not base.exists():
        return report
    dir_mode = stat.S_IMODE(base.stat().st_mode)
    report.append(
        {
            "path": str(base),
            "kind": "dir",
            "mode": oct(dir_mode),
            "expected": oct(DIR_MODE),
            "ok": dir_mode & 0o077 == 0,
        }
    )
    for name in SENSITIVE_FILES:
        p = base / name
        if not p.exists():
            continue
        mode = stat.S_IMODE(p.stat().st_mode)
        report.append(
            {
                "path": str(p),
                "kind": "file",
                "mode": oct(mode),
                "expected": oct(FILE_MODE),
                "ok": mode & 0o077 == 0,
            }
        )
    return report
