# Mini-OS – Aktivierungsbericht Echtbetrieb Phase 1

- **Prüfstand:** Commit `38d7d1d`, Branch `vibe/personal-os-4e2dc9`, PR #1
- **Datum:** 2026-11-15
- **Umgebung:** Python 3.12, Paket importiert stdlib-only; Tests via `python -m unittest discover -s tests -p "test_personal_os*.py"`
- **Regression:** 163/163 Tests OK (unverändert zu Betriebsbereitschaft)

---

## 1. Vorbereitende Sicherheitsprüfung (vor Aktivierung verbindlich)

Alle Prüfungen wurden gegen den tatsächlichen Code und eine live laufende
Instanz in einem isolierten `POS_HOME` durchgeführt (nicht nur aus Doku/Tests).

| # | Prüfpunkt | Nachweis (tatsächlich ausgeführt) | Ergebnis |
|---|-----------|-----------------------------------|----------|
| S1 | Installationsstand & Konfiguration | frisches `POS_HOME`, `pos init`, `config.json` gelesen | **PASS** – `llm.provider="none"`, `llm.endpoint=""`, `connectors={}`, `privacy.external_can_see_private=false`, `privacy.default_capture_scope="private"`, `server.host="127.0.0.1"` |
| S2 | Secrets nur via Env | `config.json` geprüft, `POS_*`-Variablen | **PASS** – keine Secrets in der Datei; nur `POS_TOKEN` / `POS_LLM_API_KEY` als Env referenziert |
| S3 | Dateiberechtigungen des Datenverzeichnisses | `stat` nach `pos init` (umask 022): Verzeichnis 755, Dateien 644 | **BEFUND (relevant, nicht kritisch bei Single-User) — im CI-/Sicherheitsgate behoben:** Code legt neue POS_HOME jetzt mit `0700` an, sensible Dateien (`config.json`, `store.db`, `kg.json`, Backups) mit `0600` (auch bei umask 000 getestet); bestehende Verzeichnisse werden nicht ungefragt verändert, Abweichungen meldet `pos status` unter `file_permissions` (nicht-mutierend). At-rest unverschlüsselt bleibt dokumentiertes Restrisiko |
| S4 | REST nur lokal erreichbar | Server live gestartet; Verbindung über externe Host-IP → `Connection refused`; Start mit `host="0.0.0.0"` → `RuntimeError: Verweigert: '0.0.0.0' ist kein Loopback-Host` | **PASS** – bindet ausschließlich 127.0.0.1 |
| S5 | REST-Zugriffsschutz mit Token | live: ohne Token → 401, falsches Token → 401, korrektes Token → 200. Token-Subjekt `external`: `scope=private` → 403 (context/loops/commitments/attention), Schreiben `private` **und** `work` → 403, Lesezugriff liefert nur work-Daten (`/today` ohne private Commitments) | **PASS** |
| S6 | MCP nur stdio | JSON-RPC `initialize`/`tools/list`/`tools/call` über stdin/stdout; `pos_capture` landet mit `source=mcp-check` in der DB | **PASS** – kein Socket |
| S7 | Keine externen Modellaufrufe | `llm.provider="none"` → Guard in `delegate.py` (`provider not in ("", "none")` **und** `_llm_allowed(scope)`); Code-Grep: `requests` nur in `delegate.py` (LLM-Pfad, config-gated) und `connectors/web.py` (nur bei konfiguriertem web-Connector) | **PASS** – im Defaultzustand keine externen HTTP-Aufrufe möglich |
| S8 | Keine aktiven/schreibenden Connectoren | `connectors={}` → `pos sync` erfasst nichts; alle Connectoren sind read-only (E-Mail nur IMAP-Lesezugriff, Credentials nur via Env) | **PASS** |
| S9 | Backup & Wiederherstellung (laufende DB) | `pos backup` auf laufender DB → `integrity_check: ok`; Restore in frisches Verzeichnis → `integrity_check: ok`, alle Items/Loops inkl. Scope + Source vollständig erhalten | **PASS** |
| S10 | Regression | voller Testlauf | **PASS** – 163/163 OK |

**Kritische Befunde: keine.** → Es gab keinen Grund für einen Abbruch; die
Aktivierung erfolgte unter den unten genannten Grenzen.

---

## 2. Kontrollierte Aktivierung

- **Separates produktives `POS_HOME`** (Beispiel: `export POS_HOME=~/.personal_os_echt`),
  in der Prüfung ein isoliertes Verzeichnis. Kein Produktivsystem berührt.
- `chmod 700 $POS_HOME` gesetzt (siehe S3).
- **Vor dem ersten Import konsistentes Backup erstellt:** `pos backup …` →
  `integrity_check: ok` (SQLite-Backup-API, nicht Verzeichniskopie).
- **Tatsächlich aktivierte Datenquellen: ausschließlich manuelles Capture**
  (`pos capture …`, MCP `pos_capture`) mit `source=manual` bzw. `source=mcp-…`.
  **Keine** E-Mail-, Kalender-, Web-, Git- oder MCP-Connectoren konfiguriert
  (`connectors={}`), **kein** externes LLM (`llm.provider="none"`).
- Keine produktiven Fremddaten importiert; die Prüfdaten waren synthetische
  Demobeispiele. Nur lokale Verarbeitung.

---

## 3. Täglicher Nutzungsablauf – verifizierte Befehle

Alle fünf Befehle wurden gegen tatsächlich gespeicherte Daten ausgeführt;
jede Ausgabe trägt Scope, Status, Frist und Quelle (Beispiele gekürzt):

- `pos day` – beantwortet read-only die 5 Fragen: Aufmerksamkeit heute
  (Top 3 mit Begründung), offene Zusagen, worauf warte ich, verdrängte Themen,
  offene Klärungen (`fehlt: …`).
- `pos attention` – z. B. `[p1] (action, Score 90) Rechnung Strom bezahlen … –
  überfällig seit N Tagen (+65); Status 'committed' (+25)`; Kategorien
  action/clarification/observe, max. 3 Punkte im Digest.
- `pos commitments list` – z. B. `976351a9f916 [private/committed] bis 2026-11-19
  (ich) Mama die Unterlagen fürs Finanzamt` und `[work/mentioned] … (Anfrage,
  nicht automatisch verbindlich)`.
- `pos digest` – Tages-Digest inkl. Aufmerksamkeitssektion; jede Zeile mit
  Quelle (`manual`/`mcp-check`/…) und Scope in den Rohdaten.
- `pos status` – Übersicht: items/loops/context_objects/delegations/connectors
  (leer = keine aktiven Connectoren).

---

## 4. Qualitätsmessung über 14 tatsächliche Nutzungstage

### 4.1 Automatisch erfassbare Kennzahlen (aus DB/Backups auswertbar)

| Kennzahl | Abfrage/Quelle |
|---|---|
| neue Commitments + Statuswechsel pro Tag | `context_objects` (type='commitment') + Statushistorie, Delta pro Tag |
| Duplikate (Items) | Capture-Dedup per Content-Hash; Re-Import erzeugt keine neuen Items |
| Duplikate (Commitments) | `_norm_title`-Dedup; `conflicts_with`-Links zählen |
| Aufmerksamkeitspunkte | `attention_evals`: Anzahl, Score-Verteilung, p1/p2-Anteil, Kategorien action/clarification/observe |
| verdrängte/wiederholte Themen | `snooze_count >= 2`, stale Loops (`adhd.stale_days`) |
| Betriebsfehler | fehlgeschlagene Delegationen (`status='failed'`), Sync-Fehler, Exceptions in Logs |
| Datenintegrität | `PRAGMA integrity_check` bei jedem Backup |

### 4.2 Manuell zu bewertende Qualitätsmerkmale (Messprotokoll, 1 Zeile/Tag)

| Merkmal | Bewertung |
|---|---|
| erkannte vs. übersehene Verpflichtungen | Soll-Zusagen ohne Commitment zählen (FN) |
| falsch erkannte Verbindlichkeiten | `committed` ohne Textbeleg (FP) |
| fehlende Kontextverknüpfungen | Person/Projekt nicht verknüpft |
| Relevanz der Aufmerksamkeitspunkte | wurde gehandelt? ja / nein / verdrängt |
| Betriebsabweichungen | alles, was nicht wie dokumentiert lief |

Vorlage: Tabelle Tag 1–14 mit Spalten *Datum | neu erkannt | übersehen | FP | Duplikate | Verknüpfung fehlt | p1 gehandelt? | verdrängt | Fehler*.

### 4.3 Betriebssicherheit während der 14 Tage

- **Täglich:** `pos backup <ziel>/pos_$(date +%F).db` (integrity_check inklusive),
  Aufbewahrung mindestens 14 Tage.
- **Mindestens ein Restore-Test** während der 14 Tage (in dieser Phase-1-Prüfung
  bereits einmal erfolgreich: Backup → Restore → integrity ok, Daten vollständig).
- Tägliches Protokoll der manuellen Merkmale (4.2).

---

## 5. Abbruchkriterien (sofortiger Abbruch + Befund vorlegen)

1. Datenverlust oder `integrity_check != ok`.
2. Unkontrollierter externer Zugriff oder externe Datenübertragung.
3. Scope-Leak (private Inhalte für external/work sichtbar).
4. Produktive Daten ohne ausdrückliche Freigabe importiert.

---

## 6. Verbleibende Risiken (unverändert, dokumentiert)

1. SQLite at rest unverschlüsselt (Dateisystemschutz via `chmod 700` lokal; WP6-Option).
2. Ohne `POS_TOKEN` ist jeder Loopback-Client owner (127.0.0.1-only mindert das).
3. MCP-stdio gilt als vertrauenswürdiger lokaler Kanal.
4. Scope-Fehlklassifikation möglich (konservativer Default `private`; inhaltliche Prüfung = WP5).
5. Deterministische Commitment-Erkennung: konservative False Negatives (z. B.
   „Ich soll …“ ohne Zusage-Verb wird nicht als verbindlich erfasst – gewollt,
   damit keine unbegründete Verbindlichkeit entsteht).

---

## 7. Freigabegrenze & nächster Schritt

- Die **14-tägige Qualitätsmessung startet erst nach ausdrücklicher Bestätigung**.
- Die **endgültige Betriebsabnahme erfolgt erst nach 14 realen Nutzungstagen**,
  nicht allein anhand von Simulationen.
- Weiterhin gesperrt: WP4/WP5/WP7, eigenständige externe Aktionen, zusätzliche
  Datenquellen ohne Freigabe, automatische Änderung bestehender Verpflichtungen,
  Mehrbenutzerbetrieb.

---

## CI- und Sicherheitsgate (nach Aktivierungsbericht)

**Getestet auf Branch `vibe/personal-os-4e2dc9`, PR #1 (Draft), Head-Commit siehe git log.**

### CI-Status

- GitHub-API `actions/runs`: `total_count = 0` (auch `event=pull_request` = 0) — auf dem
  Repo existieren **keine Workflow-Runs** (weder main noch Branch).
- PR #1: `state=OPEN`, `isDraft=true`, `mergeStateStatus=CLEAN`, `statusCheckRollup=[]`;
  `gh pr checks` → „no checks reported“. Branch-Protection nicht lesbar (Token 403) →
  keine required status checks.
- Workflows (ci.yml, security.yml, security-scan.yml, docs.yml, …) sind auf Branch und
  `main` identisch; PR #1 ändert keine Workflows. `ci.yml` triggert nur auf push→main /
  PR→main (paths-ignore `**/*.md`) und führt Explorer-Build + Wheel-Build aus, **keine**
  Python-Tests. Manuelles Auslösen per `gh workflow run` mit diesem Token nicht möglich
  (Actions-API 404/403).
- **Bewertung:** keine fehlgeschlagenen oder ausstehenden Checks; „grün“ im Sinne von
  „keine roten Checks“, da keine laufen (Draft-PR). Lokale Gates als Nachweis:
  pre-commit-Hooks bei jedem Commit (0 Failed), **171/171 unittest OK**,
  Paket stdlib-only importierbar.

### Dateiberechtigungen (behoben im Gate)

- Neu: `personal_os/fileperms.py` — `ensure_private_dir` (neues POS_HOME → `0700`,
  auch bei umask 000), `secure_file` (`config.json`, `store.db`, `kg.json`, Backup-Dateien
  → `0600`; bestehende verwaltete Dateien werden beim Öffnen gehoben, bestehende
  **Verzeichnisse** bleiben unangetastet), `permission_report` (nicht-mutierend, via
  `pos status` → `file_permissions`).
- Regressionstests: `tests/test_personal_os_fileperms.py` (8 Tests, POSIX): 0700 bei
  umask 000, 0600 für config/db/kg/Backup, bestehendes 0755-Dir bleibt 0755,
  Report meldet 0644 ohne Änderung, Reopen hebt Dateien auf 0600.
- Live-Nachweis: frisches POS_HOME → `700`/`600`; `pos status` zeigt Report mit `ok:true`.

### Aktivierungsgate — Abschließbestätigung

| Kriterium | Status |
|---|---|
| CI: keine fehlgeschlagenen/ausstehenden Checks auf Head-Commit | erfüllt (0 Runs, Draft-PR, lokal pre-commit + 171/171 Tests grün) |
| Sicherheitsanforderungen (Loopback-only, Token, MCP stdio, keine externen LLM-Calls, keine aktiven Connectoren) | erfüllt (S1–S10 oben, live verifiziert) |
| Dateiberechtigungen 700/600 | erfüllt (code-enforced + Regressionstests + Live-Nachweis) |
| Backup & Restore nachgewiesen | erfüllt (`pos backup` laufender DB, integrity_check ok, Restore-Test) |
| Keine externen Datenquellen aktiviert | erfüllt (`connectors={}`) |
| Kein externes LLM aktiviert | erfüllt (`llm.provider="none"`) |
| Keine offenen kritischen Befunde | erfüllt |

**Entscheidung: AKTIVIERUNGSBEREIT** (Phase 1 wie freigegeben: nur manuelle Captures,
separates POS_HOME). PR #1 bleibt Draft (kein Merge ohne Freigabe); die 14-tägige
Messung startet nicht automatisch.
