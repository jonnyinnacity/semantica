# Mini-OS – Übergabebericht (Abschlussgate, kontrollierter Betrieb)

- **Referenz:** PR [#1](https://github.com/jonnyinnacity/semantica/pull/1) (Draft, **nicht gemergt**), Branch `vibe/personal-os-4e2dc9`
- **Datum:** 2026-11-15
- **Keine automatische Aktivierung des Echtbetriebs; keine produktiven Daten importiert.**

## 1. Verbindliche Baseline

| Baustein | Stand | Nachweis |
|---|---|---|
| **Code-Baseline** | Commit **`f634e0405f86d3cf6fff4a6c57703ab607926b86`** = PR-Head | `git log`, `gh pr view` (state OPEN, isDraft true, headRefOid = f634e04…) |
| **CI-Baseline** | Mini-OS CI auf `f634e04`: Run **43776488507** (pull_request) + **43776481280** (push), beide **success**; 171/171 Tests auf Python 3.11 + 3.12, Paket-Installation (`semantica-0.6.5`), `pos --help`, pre-commit alle Hooks Passed | [Run 43776488507](https://github.com/jonnyinnacity/semantica/actions/runs/43776488507), `docs/ci_nachweis.md` |
| **Lokale Regression** | `python -m unittest discover -s tests -p "test_personal_os*.py"` → **171/171 OK**; pre-commit clean | Commit-Hooks bei jedem Commit |
| **Bisherige Abnahmen/Freigaben** | WP1 (Review 888b5f4) → WP3 (5b87a19) → WP2 (a15a251) → Integrationsabnahme (689e146) → Pilot (7f19dc4) → Betriebsbereitschaft (38d7d1d) → Echtbetrieb Phase 1 Aktivierungsbericht (444c05f) → CI-/Sicherheitsgate (2b26659) → CI-Nachweis BESTANDEN (1c361c2, 221a15a, 7a054dd, f634e04) | `docs/mini_os.md` (alle Berichte), `docs/echtbetrieb_phase1.md`, `docs/ci_nachweis.md` |

## 2. Repository-Abgrenzung

Der offene Befund **„Verify Action Pins“** (Run 43776178871, failure) betrifft
ausschließlich **fremde, nicht von PR #1 berührte Workflows** (Upstream-Tag-Drift:
`setup-node` v7, `deploy-pages` v5, `action-gh-release` v3, `gh-action-pypi-publish`,
`upload-artifact` v7, altes `setup-python` in ci.yml/security.yml/security-scan.yml/
docs.yml/release.yml). Er ist **ausdrücklich außerhalb des Mini-OS-Umfangs**;
PR #1 ändert keine fremden Workflows, und `personal-os.yml` selbst besteht die
Pin-Prüfung. Ebenfalls außerhalb: `actions/permissions`/Branch-Protection sind mit
dem verwendeten Token nicht lesbar (403) — dokumentiert, nicht verändert.

## 3. Sicherheits- und Backup-Status (live verifiziert auf f634e04)

- **Dateiberechtigungen:** neues POS_HOME automatisch `0700`, `config.json`/
  `store.db`/`kg.json`/Backups `0600` (auch bei umask 000 getestet); bestehende
  Verzeichnisse unangetastet, verwaltete Dateien beim Öffnen auf `0600` gehoben;
  nicht-mutierender Report via `pos status` → `file_permissions`. Live: 700/600.
- **REST:** loopback-only (externe IP → refused, `0.0.0.0` → verweigert), ohne/falsches
  `POS_TOKEN` → 401, Token-Subjekt `external` → 403 auf `private` (lesen+schreiben) und
  Schreibzugriff `work`; work-Lesezugriff ohne private Inhalte.
- **MCP:** ausschließlich stdio (Handshake + `pos_capture` getestet).
- **Keine externen Modellaufrufe** (`llm.provider="none"` + Guards), **keine aktiven
  Connectoren** (`connectors={}`, alle read-only), Secrets nur via Env.
- **Backup/Restore:** `pos backup` auf laufender DB mit `integrity_check ok`
  (Datei `0600`); Restore in frisches Verzeichnis getestet — Daten vollständig.
- **Betriebsbasis-Prüfung (Datenerhalt):** bestehende Installation vor/nach Öffnen
  mit f634e04 (zweimal, Migration idempotent): items 6→6, loops 2→2,
  context_objects 2→2, delegations 0→0, Inhaltslänge 386→386, `integrity ok`.
  Frischer Start auf f634e04 reproduzierbar (init → capture → loop → backup →
  day/status → restore: 1 item, 1 loop, 1 commitment korrekt wiederhergestellt).

## 4. Tatsächlich aktivierte Funktionen (Phase 1)

- **Nur manuelles Capture** (CLI `pos capture`, MCP `pos_capture`) mit Scope/Provenienz.
- Lokal aktiv: Inbox/Memory+KG, Loops, Digest/Weekly, WP1-Kontextmodell/Scopes/
  Berechtigungen, WP3-Commitment-Erkennung (Capture-Hook), WP2-Attention-Engine,
  Delegation (deterministisch, offline; LLM-Pfad inaktiv).
- Tägliche read-only Befehle: `pos day`, `pos attention`, `pos commitments list`,
  `pos digest`, `pos status`. Backup: `pos backup`.
- **Nicht aktiv:** REST-Server und MCP-Server laufen nicht als Dienst (manuell
  startbar, loopback/stdio), keine Connectoren, kein externes LLM, keine autonomen
  externen Aktionen.

## 5. Offene Risiken (dokumentiert, akzeptiert)

1. SQLite at-rest unverschlüsselt (Dateisystemschutz 700/600 lokal; WP6-Option).
2. Ohne `POS_TOKEN` ist jeder Loopback-Client owner (127.0.0.1-only mindert das).
3. MCP-stdio gilt als vertrauenswürdiger Owner-Kanal.
4. Scope-Fehlklassifikation möglich (konservativer Default `private`; inhaltliche
   Prüfung = WP5).
5. Deterministische Commitment-Erkennung: konservative False Negatives (gewollt,
   keine unbegründete Verbindlichkeit).
6. Transiente SQLite-Journaldateien erben die umask.
7. Repo-weiter Action-Pin-Befund (Abschnitt 2) — außerhalb Mini-OS-Umfang.
8. CI: Mini-OS-Workflow läuft auf Branch/PR; Repo-CI auf main führt keine
   Python-Tests aus; Actions-Permissions via Token nicht lesbar.

## 6. Voraussetzungen für den Start der 14-tägigen Messphase

1. **Ausdrückliche Bestätigung des Nutzers** (die Messphase startet nicht automatisch).
2. Produktives `POS_HOME` (z. B. `~/.personal_os_echt`) auf Baseline f634e04,
   `chmod 700`, `pos init`, `POS_TOKEN` gesetzt falls REST genutzt wird.
3. Erstes konsistentes Backup **vor** dem ersten Import (`pos backup …`).
4. Nur manuelle Captures; `connectors={}`, `llm.provider="none"` bleibt.
5. Tägliche Backup-Routine eingerichtet (siehe `docs/echtbetrieb_startpaket.md` §3).
6. Messprotokoll bereit (Startpaket §4); ein Restore-Test während der 14 Tage.
7. Abbruchkriterien bekannt (Startpaket §5).

**Übergabe:** Entwicklungsstand ist als reproduzierbare Betriebsbasis festgehalten
(Baseline f634e04 + CI-Nachweis). Der kontrollierte Echtbetrieb Phase 1 ist
vorbereitet, aber **nicht aktiviert**. PR #1 bleibt Draft; Merge nur mit gesonderter
Freigabe.
