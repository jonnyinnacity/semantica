"""Beispiel: Personal OS als Bibliothek nutzen.

Start:  python examples/personal_os_example.py
Setzt ein eigenes Datenverzeichnis unter /tmp, damit nichts echte Daten beruehrt.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("POS_HOME", tempfile.mkdtemp(prefix="pos_example_"))

from personal_os import PersonalOS  # noqa: E402

with PersonalOS() as pos:
    pos.capture(
        "Projekt Phoenix: Kickoff im Juni, Team Berlin, Budget 50k. "
        "Maria leitet das Projekt bei Acme.",
        tags=["phoenix"],
    )
    pos.capture(
        "Geburtstag Lisa: 3. August. Geschenk: Buch ueber Graphen.", tags=["privat"]
    )

    print("== Frage ans Gedaechtnis ==")
    for hit in pos.ask("Budget und Leitung von Phoenix?", limit=2)["results"]:
        print(f"  [{hit['score']:.3f}] {hit['content'][:80]}")

    print("== Loops ==")
    loop = pos.add_loop_from_text(
        "Geburtstagsgeschenk Lisa kaufen bis 01.08. wichtig #privat"
    )
    print(
        f"  angelegt: {loop['title']} (faellig {loop['due']}, Prio {loop['priority']})"
    )

    print("== Delegation ==")
    d = pos.delegate("Was weiß ich über Lisas Geburtstag?")
    result = pos.run_delegation(d["id"])
    print(f"  [{result['status']}] {result['result'][:200]}")

    print("== Tages-Digest ==")
    print(pos.digest_text())

    print("== Stats ==", pos.stats())
