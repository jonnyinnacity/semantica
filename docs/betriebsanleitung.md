# Mini-OS – Betriebsanleitung (kontrollierter Echtbetrieb)

Basis: PR #1, Branch `vibe/personal-os-4e2dc9`. Gilt für lokalen Single-User-Betrieb.
**Echtbetrieb wird nicht automatisch aktiviert** — die endgültige Betriebsabnahme
erfolgt nach 14 tatsächlichen Nutzungstagen (siehe Messplan unten).

## 1. Installation (reproduzierbar)

```bash
git clone <repo> && cd semantica
git checkout vibe/personal-os-4e2dc9
pip install -e .          # installiert u. a. den Befehl `pos`
export POS_HOME=~/.personal_os   # Datenverzeichnis (Default: ~/.personal_os)
pos init                  # config.json anlegen
```

Voraussetzungen: Python ≥ 3.10, lokal. Optionale Zusatzpakete (requests, starlette,
uvicorn, bs4) nur für Web-Connector/REST; Kern (CLI, Store, Memory, Loops, Commitments,
Attention, MCP-stdio) läuft mit der Stdlib allein.

## 2. Start, Neustart, Konfiguration

- Start CLI: `pos status` | `pos day` | `pos digest` | `pos attention`
- REST lokal: `pos serve` (bindet **nur 127.0.0.1**, verweigert andere Hosts;
  mit `POS_TOKEN` in der Umgebung braucht jeder Request `Authorization: Bearer …`)
- MCP (stdio, für lokale KI-Tools): `pos mcp`
- Neustart: beliebig oft möglich; Migration ist additiv/idempotent, Daten bleiben erhalten
- Config: `$POS_HOME/config.json` (Profil, `adhd`, `privacy`, `server`, `llm`, `connectors`)
- Fehlerbehebung: `pos status` (Zähler), `python -m unittest discover -s tests -p "test_personal_os*.py"`
  (155 Tests), Logs liegen nicht extern; bei DB-Fehlern: Backup wiederherstellen (s. u.)

## 3. Datensicherheit (A2)

- **Datenverzeichnis**: `$POS_HOME` enthält `config.json`, `store.db`, `kg.json`.
  **Wird ab jetzt vom Code abgesichert:** neue POS_HOME-Verzeichnisse werden mit
  `0700` angelegt, sensible Dateien (`config.json`, `store.db`, `kg.json`, Backups)
  werden auf `0600` gesetzt (POSIX; bei bestehendem Verzeichnis bleiben dessen Rechte
  unangetastet, verwaltete Dateien werden beim Öffnen auf `0600` gehoben).
  Prüfung ohne Änderung: `pos status` → Schlüssel `file_permissions`
  (nicht-mutierender Report, Regressionstests in `tests/test_personal_os_fileperms.py`).
  **at rest unverschlüsselt** (bekanntes Restrisiko, WP6-Option).
- **REST**: Loopback-only (andere Hosts werden mit RuntimeError verweigert), optionaler Bearer-Token (`POS_TOKEN`). Ohne Token ist jeder lokale Prozess auf 127.0.0.1 owner — Restrisiko, lokal begrenzt.
- **MCP**: ausschließlich stdio (kein Netzwerk), gilt als Owner-Kanal.
- **Externe Datenübertragungen**: im Default-Betrieb **keine** — getestet
  (`test_default_operations_make_no_network_calls`: socket/requests gepatcht, alle
  Standardflüsse laufen lokal). Netzwerk gibt es nur bei explizit konfiguriertem
  Web-Connector oder LLM-Provider; private Scopes werden dabei nie an externe
  Modelle gesendet (WP1-Guards: `permissions.can_external_model_call`, Redaction).
- **Scopes**: `private`/`work` überall strikt getrennt (Store, Memory, Loops,
  Context, CLI, REST, MCP); externe Subjekte sehen nur `work`.

## 4. Backup & Wiederherstellung (A2, laufende DB)

```bash
pos backup /pfad/store_$(date +%F).db     # konsistentes Backup der LAUFENDEN DB
```

- Implementation: SQLite-Backup-API (`store.backup()`), inklusive `PRAGMA integrity_check` — **kein** einfaches Verzeichniskopieren.
- Restore: OS stoppen, `store.db` durch Backup ersetzen, `pos status` prüfen.
- Nachweis: `tests/test_personal_os_ops.py` (Backup bei offener Verbindung, Vollständigkeit, Restore, Idempotenz).
- Empfohlen: tägliches Backup + Aufbewahrung 7 Tage.

## 5. Kontrollierter Datenimport (A3, read-only)

- Nur lesende Connectors konfigurieren (`filesystem`, `git`, `email`, `web`, `mcp`),
  z. B. `"connectors": {"filesystem": {"path": "~/notes", "scope": "private"}}`.
- Import: `pos sync` — Duplikate werden per Content-Hash erkannt (erneuter Import
  erzeugt **keine** neuen Einträge; getestet), Scope/Provenienz kommen aus der
  Connector-Konfiguration bzw. dem Item.
- Keine produktiven persönlichen Daten ohne gesonderte Freigabe; keine schreibenden
  Connectors aktivieren.

## 6. Täglicher Ablauf (A5) — `pos day`

Read-only, beantwortet auf Basis vorhandener Daten (Unsicherheit via Konfidenz/`fehlt:`):

1. Was braucht heute meine Aufmerksamkeit? → `pos attention` (Top 3 mit Begründung)
2. Welche Zusagen sind offen? → Commitments mit Status committed/intent
3. Worauf warte ich? → Anfragen/fremde Zusagen (mentioned, party=other/request)
4. Welche wichtigen Themen geraten aus dem Blick? → stale Loops + goals/projects
5. Was muss ich noch klären? → Attention-Kategorie `clarification` mit `missing_info`

Abend: `pos digest` / `pos weekly`. Alle Antworten sind Ableitungen aus vorhandenen
Daten; Unsicherheit ist über `missing_info`/Konfidenz kenntlich.

## 7. Messplan für die ersten 14 Nutzungstage (A4)

Täglich (manuell oder per `pos status`/`pos attention` + DB-Abfragen) erfassen:

| Kennzahl | Quelle |
|---|---|
| erkannte Verpflichtungen | `SELECT COUNT(*) FROM context_objects WHERE type='commitment'` (Delta) |
| übersehene Verpflichtungen | manuell: Soll-Zusagen vs. erkannte (Review) |
| unbegründete Verpflichtungen | manuell: committed ohne Textbeleg (WP3-Review) |
| Duplikate/falsch verknüpfte Objekte | `conflicts_with`-Links + Titel-Dubletten prüfen |
| Relevanz der Aufmerksamkeitspunkte | p1/p2-Anteil, ob gehandelt wurde |
| wiederholt verdrängte Themen | `snooze_count >= 2`, stale-Loops |
| Fehler/Ausfälle | `pos status`, Exception-Logs, fehlgeschlagene Delegationen (`status=failed`) |

Formeln und Beispielabfragen siehe `docs/mini_os.md`; Auswertung nach 14 Tagen
→ Betriebsabnahme (nicht durch Simulation allein).

## 8. Verbleibende Sicherheitsrisiken

1. SQLite at rest unverschlüsselt (Dateisystemschutz genügt lokal, WP6-Option).
2. Ohne `POS_TOKEN` ist jeder Loopback-Client owner (127.0.0.1 only mindert das).
3. MCP-stdio gilt als vertrauenswürdiger lokaler Kanal.
4. Scope-Fehlklassifikation möglich (konservativer Default `private`); inhaltliche
   Prüfung ist WP5-Thema.
5. Deterministische Erkennung: konservative False Negatives (dokumentiert).
