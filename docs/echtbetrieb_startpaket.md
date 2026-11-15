# Mini-OS – Startpaket für den kontrollierten Echtbetrieb (Phase 1)

Gilt ab Baseline-Commit `f634e04` (PR #1, Branch `vibe/personal-os-4e2dc9`).
Nichts in diesem Paket aktiviert sich automatisch — der Start der 14-tägigen
Messphase bedarf der ausdrücklichen Bestätigung durch den Nutzer.

## 1. Voraussetzungen vor dem ersten Produktiv-Einsatz

1. Geprüften Stand auschecken: Branch `vibe/personal-os-4e2dc9`, Commit `f634e04`
   (CI-Nachweis: Runs 43776488507/43776481280, success — siehe `docs/ci_nachweis.md`).
2. Paket installieren: `pip install --no-deps -e .` (personal_os ist stdlib-only;
   optionale REST-Test-Deps nur für Tests: `starlette httpx requests uvicorn`).
3. Separates produktives Datenverzeichnis, z. B.:
   ```bash
   export POS_HOME=~/.personal_os_echt
   chmod 700 "$POS_HOME" 2>/dev/null || true   # neues Verzeichnis wird ohnehin 0700 angelegt
   pos init
   ```
4. Optional, empfohlen wenn REST genutzt wird: `export POS_TOKEN=<zufaelliger-wert>`
   (Token-Clients gelten als `external` und sehen nur `work`).
5. **Vor dem ersten Import konsistentes Backup:** `pos backup ~/pos_backups/pos_vor_import.db`
   (SQLite-Backup-API + `integrity_check`, Datei wird `0600`).
6. Nur manuelle Captures: `pos capture "…" --source manual [--scope private|work]`
   bzw. MCP `pos_capture`. **Keine** E-Mail/Kalender/Web/Git-Connectoren in
   `config.json` eintragen (`connectors` bleibt `{}`), `llm.provider` bleibt `"none"`.

## 2. Täglicher Ablauf (alle read-only, Antworten aus gespeicherten Daten mit Quelle)

```bash
pos day                # 5 Fragen: Aufmerksamkeit, offene Zusagen, Warte-auf, Verdrängtes, Klärungen
pos attention          # Top 3 Aufmerksamkeitspunkte mit Score + Begründung
pos commitments list   # Verpflichtungen mit Status/Scope/Frist/Partei
pos digest             # Tages-Digest (Abend: pos weekly)
pos status             # Übersicht inkl. file_permissions-Report (700/600-Prüfung, nicht-mutierend)
```

## 3. Backup-Routine (täglich)

```bash
mkdir -p ~/pos_backups
pos backup ~/pos_backups/pos_$(date +%F).db     # konsistent auch bei laufender DB, integrity_check inklusive
# Aufbewahrung: mindestens 14 Tage. Beispiel cron (täglich 21:00):
# 0 21 * * * POS_HOME=$HOME/.personal_os_echt pos backup $HOME/pos_backups/pos_$(date +\%F).db
```

Restore: OS stoppen, `store.db` durch Backup ersetzen, `pos status` prüfen
(`PRAGMA integrity_check` läuft u. a. bei jedem Backup). **Mindestens ein
Restore-Test während der 14 Tage** durchführen und protokollieren.

## 4. 14-Tage-Messprotokoll

Automatisch (aus DB/Backups auswertbar): Commitments/Statuswechsel pro Tag,
Hash-/Titel-Dedup, `attention_evals` (Score-, Kategorie-, p1/p2-Verteilung),
`snooze_count >= 2`/stale, failed Delegationen, `integrity_check` jedes Backups.

Manuell (eine Zeile pro Tag), Vorlage:

| Tag | Datum | neu erkannt | übersehen (FN) | falsch verbindlich (FP) | Duplikate | Verknüpfung fehlt | p1 gehandelt? (ja/nein/verdrängt) | Betriebsfehler | Bemerkung |
|-----|-------|-------------|----------------|------------------------|-----------|-------------------|----------------------------------|----------------|-----------|
| 1 | | | | | | | | | |
| … | | | | | | | | | |
| 14 | | | | | | | | | |

Auswertung nach Tag 14 → Betriebsabnahme (nicht durch Simulation allein).

## 5. Abbruchkriterien (sofortiger Abbruch + Befund vorlegen)

Datenverlust oder `integrity_check != ok`; unkontrollierter externer Zugriff/
Datenübertragung; Scope-Leak private→external/work; produktive Daten ohne
Freigabe importiert.

## 6. Grenzen (unverändert)

Keine WP4/WP5/WP7, keine eigenständigen externen Aktionen, keine zusätzlichen
Datenquellen ohne Freigabe, keine automatische Änderung bestehender
Verpflichtungen, kein Mehrbenutzerbetrieb, kein Merge von PR #1 ohne Freigabe.
