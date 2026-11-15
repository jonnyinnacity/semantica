"""Pilotlauf: 7 simulierte Tage mit anonymisierten Beispielereignissen.

Start:  python examples/personal_os_pilot.py
Druckt Qualitätsmetriken, tägliche Aufmerksamkeitspunkte, den Tages-Digest
von D7 und den Weekly Review. Arbeitet in einem isolierten Temp-Verzeichnis.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_personal_os_pilot import run_pilot  # noqa: E402


def main():
    data_dir = str(Path(tempfile.mkdtemp(prefix="pos_pilot_")) / "pilot")
    m = run_pilot(data_dir, verbose=True)
    print("\n== Qualitätsmetriken ==")
    print("Ereignisse:", m["events"], "| Duplikat-Captures:", m["duplicate_captures"])
    print(
        "Commitments:",
        m["commitments_created"],
        "neu,",
        m["commitments_duplicate"],
        "Duplikate,",
        m["conflicts"],
        "Konflikte,",
        "gesamt",
        m["commitments_total"],
    )
    print("Items:", m["items_total"], "| Objekte:", m["objects_total"])
    print("Personen-Link:", m["person_linked"], "| Snooze:", m["snooze_count"])
    print(
        "Ziel sichtbar:",
        m["goal_visible"],
        "| Work-Scope sauber:",
        m["work_scope_clean"],
    )
    print("\n== Daily Digest D7 ==")
    print(m["digest_d7"])
    print("\n== Weekly Review D7 ==")
    print(m["weekly_d7"])


if __name__ == "__main__":
    main()
