# Mini-OS – Entwicklungsplan (Analyse & Architektur, Stand: Draft-PR #1)

Dieses Dokument ist die Bestandsaufnahme und der Plan gemaess Entwicklungsauftrag
"Mini-OS". Es enthaelt **keine Implementierung**, sondern:

1. Bestandsaufnahme des bestehenden Systems (PR #1) vs. Anforderungen
2. Architekturentscheidung zur Erweiterung
3. Priorisierten Implementierungsplan mit Arbeitspaketen
4. Aufwands- und Kostenschaetzung
5. Vorschlag fuer den ersten vollstaendig testbaren End-to-End-Fall

Basis: Branch `vibe/personal-os-4e2dc9` (PR #1, 1 Commit, 28 Dateien, +3472 Zeilen,
46 Unit-Tests, pre-commit clean; CI meldet keine Checks fuer Draft-PRs).

---

## 1. Bestandsaufnahme

Legende: ✅ bereits implementiert · 🟡 teilweise vorhanden · ❌ fehlt

| Anforderung (Auftrag) | Status | Vorhanden in PR #1 | Luecke |
|---|---|---|---|
| §2.3 SQLite + KG, Suche, Capture, Loops, Digest, Delegation, Connectors, REST/MCP | ✅ | `store.py`, `memory.py` + `kg.json`, `inbox.py`, `loops.py`, `digest.py`, `delegate.py`, `connectors/`, `server.py`, `mcp_server.py` | wird als Basis erhalten und erweitert, nicht ersetzt |
| §2.1 Modellunabhaengigkeit (Provider wechseln, aufgabenabhaengige Auswahl) | 🟡 | `config.llm` (ein Provider, OpenAI-kompatibel, Key via Env); deterministischer Offline-Agent | kein Provider-Router, keine Tiers (lokal/guenstig/stark), kein Fallback bei Ausfall, kein Kosten-Log |
| §2.2 Local First, Datensouveraenitaet | 🟡 | alles lokal in `$POS_HOME`; REST nur 127.0.0.1; Secrets nur via Env | keine Trennung privat/beruflich (Scopes), keine Berechtigungsmatrix, keine Datenminimierung bei externen Modellen |
| §3 Kontextmodell: Personen, Bereiche, Projekte, Zusagen, Entscheidungen, Routinen, Ziele – mit Quelle, Gueltigkeit, Vertrauen, Status | 🟡 | Items mit `source`, `created_at`, KG-Entitaeten/Relationen; Loops | keine Typlosung (Person/Project/Commitment/Decision/…), kein Status-Lebenszyklus (erwaehnt → Absicht → Zusage → erledigt), kein Vertrauen/Gueltigkeit, keine Widerspruchserkennung (KG appendet stillschweigend) |
| §4 Aufmerksamkeitsmanagement (Dringlichkeit ≠ Relevanz, Dimensionen, Unterbrechungsregeln, Arbeitskontext) | 🟡 | `digest.py`: overdue/due/stale/top-thing, Section-Cap | keine mehrdimensionale Relevanzbewertung, keine Unterscheidung privat vs. beruflich, keine konfigurierbaren Unterbrechungsregeln, kein Bezug zum aktuellen Arbeitskontext, keine Begruendungen |
| §5 Proaktive Erkennung von Verpflichtungen aus Quellen (Anfrage vs. Zusage) | ❌ | `extract.parse_loop` nur fuer expliziten User-Text | keine Extraktion aus E-Mail/Chat ("bis Donnerstag?" → offener Vorgang mit erwartendem, Frist, Uebernahme-Status) |
| §6 Drei Autonomiestuufen (beobachten/vorschlagen, vorbereiten, kontrolliert ausfuehren) + Freigaben + Nachweis + Eskalation | 🟡 | `delegate.py`: Agent mit Tools, Trace, Status pending/running/done/failed | keine Stufen L1–L3, keine Permission-Gates (Agent darf sofort capturen/loops), keine Freigabe-Warteschlange, kein Ausfuehrungsnachweis, keine Eskalation; "Agent lief" ≠ erledigt |
| §7 Connectoren read+write, Dedup ueber Quellen hinweg | 🟡 | 5 read-Connectors; Dedup per Content-Hash | keine schreibenden Aktionen (Kalender/Tasks/E-Mail-Entwurf), kein semantisches Merging ueber Quellen, keine Kalender-/Task-Systeme angebunden |
| §8 Interaktion: Morgen-Ueberblick (max. 3 Punkte), situative Intervention, Abend-Abschluss, NL-Bedienung | 🟡 | `pos digest`/`today`/`weekly`, CLI | Digest zeigt mehr als 3 Punkte ohne Begruendung; keine Abend-Routine; keine NL-/Chat-Schnittstelle (nur CLI/MCP) |
| §9 Lernfaehigkeit aus Korrekturen, nachweisbare Praeferenzen | ❌ | – | kein Praeferenz-Speicher, keine Korrektur-Propagation, keine Trennung Fakt vs. Annahme |
| §10 Inkrementell auf bestehendem Repo | ✅ | – | – |

### Akzeptanzkriterien → aktueller Stand

1. Verpflichtung aus eingehender Info erkennen + Quelle speichern → 🟡 (Quelle ja, Erkennung ❌)
2. Unverbindliche Anfrage nicht als Zusage behandeln → ❌
3. Private Angelegenheit trotz vieler beruflicher Aufgaben priorisiert → 🟡 (Prio nur manuell)
4. Erledigte Aufgabe nicht erneut offen melden → ✅ (Status done; Wiederholung legt neuen Loop an)
5. Delegierte Aufgabe bleibt bis Nachweis in Systemverantwortung → 🟡 (Status ja, Nachweis/Freigabe ❌)
6. Agent bereitet vor ohne unerlaubte externe Aktion → ❌ (keine Gates)
7. Morgen-Ueberblick max. 3 begruendete Punkte → 🟡 (Cap pro Sektion, aber keine 3-Punkte-Regel mit Begruendung)
8. Ausfall eines Modellanbieters ohne Datenverlust → 🟡 (lokal gespeichert, aber kein Provider-Fallback; Offline-Agent existiert als Default)
9. Private Daten nicht ohne Freigabe an externe Modelle → 🟡 (keine externen Calls ohne Config, aber keine Scopes/Redaction)
10. Fehlpriorisierung korrigierbar mit nachvollziehbarer Wirkung → ❌

---

## 2. Architekturentscheidung

**Entscheidung: In-Place-Erweiterung von `personal_os` (PR #1), keine Ersetzung.**

Begruendung: Alle in §2.3 genannten Komponenten existieren und sind getestet. Die neuen
Anforderungen sind ueberwiegend **neue Schichten ueber dem bestehenden Speicher**, nicht
neue Speicher. SQLite bleibt Source of Truth; `kg.json` bleibt abgeleitete Sicht.

Erweiterung um sechs neue Module (jeweils eigene Datei, bestehende API bleibt abwaertskompatibel):

```
personal_os/
  context_model.py   # Typlosung + Status-Lebenszyklus + Provenienz + Widersprueche
  scopes.py          # privat/beruflich: Scopes, Berechtigungen, Redaction fuer externe Calls
  providers.py       # Modell-Router: Tiers (lokal/guenstig/stark), Fallback, Kosten-Log
  attention.py       # Attention Engine: Relevanz-Scoring, Unterbrechungsregeln, Digest <=3 Punkte
  commitments.py     # Erkennung von Anfragen/Zusagen aus eingehenden Texten
  autonomy.py        # Autonomiestuufen L1-L3, Freigabe-Queue, Ausfuehrungsnachweis, Eskalation
  preferences.py     # gelernte, korrigierbare Praeferenzen mit Quellen
```

Datenmodell-Erweiterung (Schema-Migration in `store.py`, additive Spalten/Tabellen):
- Tabelle `context_objects`: id, type (person|area|project|task|commitment|decision|routine|goal|event), title, scope (private|work), status (mentioned|intent|committed|done|rejected), confidence, valid_from, valid_until, source_item_id, superseded_by
- Tabelle `links`: object_id → object_id, relation, provenance
- Tabelle `approvals`: delegation_id, action, autonomy_level, status (pending|approved|rejected), decided_by, decided_at, reason
- Tabelle `receipts`: delegation_id, action, tool, args_hash, result_hash, executed_at, executed_by
- Tabelle `preferences`: key, value, confidence, source, created_at, updated_at, superseded
- Tabelle `provider_usage`: provider, model, task, tokens_in/out, cost, ts, ok

Grundsätze:
- **Bestehende Tabellen/Dateien bleiben**; Migration ist additiv und idempotent.
- **Externe Modelle bekommen nur gefilterte Scopes** (Redaction), nie Roh-Store.
- **Jede autonome Handlung landet in `approvals` + `receipts`** (Nachweis) – das ist die Basis für AK 5/6/10.
- **Widersprueche** werden als `superseded_by`/Konflikt markiert, nie stillschweigend ueberschrieben (§3).
- **Provider-Router** kapselt alle Modell-Calls; Default = lokal/deterministisch, sodass Ausfall eines Anbieters nichts kaputt macht (AK 8).

Interaktions-Schnittstellen bleiben: CLI (`pos`), REST (127.0.0.1), MCP (stdio). NL-Chat kommt als `pos chat` auf Basis derselben Engine.

---

## WP1-Status: IMPLEMENTIERT (Branch vibe/personal-os-4e2dc9)

WP1 (Kontextmodell, Scopes, Provenienz, Berechtigungen) ist umgesetzt:

- Additive Migration in `store.py` (`scope`-Spalten, Tabellen `context_objects`,
  `object_links`, `permissions`); Alt-Daten getestet erhalten.
- `context_model.py`: Objekttypen, Status-Lebenszyklus mit History, Provenienz,
  Widerspruchserkennung (`conflicts_with` + `resolve_conflict`, kein Ueberschreiben).
- `scopes.py`: `private`/`work`; Scope-Filter in Memory/Store/Loops/REST/MCP;
  `redact_for_external` fuer externe Modellaufrufe.
- `permissions.py`: Subjekte owner/agent/external; Default deny fuer external auf private;
  Config-Flag `privacy.external_can_see_private`; REST mit POS_TOKEN = external (nur work).
- Delegation mit Scope; externe LLM-Calls nur bei Freigabe, sonst Offline-Fallback.
- 19 neue Tests (`tests/test_personal_os_wp1.py`), alle 65 Tests OK, pre-commit clean.

Nächste Reihenfolge laut Plan: WP3 (Commitment-Erkennung) vor WP2 (Attention Engine) —
bereit, sobald freigegeben.

## WP3-Status: IMPLEMENTIERT (Branch vibe/personal-os-4e2dc9)

Commitment-Erkennung in `personal_os/commitments.py` (deterministisch, offline):
mentioned/intent/committed/done/rejected inkl. fremder Anfragen (erst nach
Bestaetigung verbindlich), Dedup, WP1-Konfliktlogik, keine Wiedereroeffnung
erledigter, Provenienz + Konfidenz, Scope-Uebernahme ohne Hochstufung,
Capture-Hook + CLI/REST/MCP. 15 neue Tests; 98 gesamt OK; pre-commit clean.

Naechster Schritt: WP2 (Attention Engine) — wartet auf Freigabe.

## WP2-Status: IMPLEMENTIERT (Branch vibe/personal-os-4e2dc9)

Attention Engine in `personal_os/attention.py` (deterministisch, read-only,
erklaerbar): explizite Gewichtung, Kategorien action/clarification/observe,
Dedup pro Thema, Ausschluss erledigter/abgelaufener Objekte, Evaluierungen in
`attention_evals` protokolliert. Integration in Daily Digest (max 3 Punkte mit
Begruendung) + Weekly Review; CLI `pos attention`, REST `/attention`, MCP
`pos_attention`; WP1-Scope-Regeln uebernommen. 13 neue Tests; **124 gesamt OK**;
pre-commit clean. Abnahme steht noch aus (gesonderte technische Pruefung).

## 3. Priorisierter Implementierungsplan (Arbeitspakete)

Jedes WP ist einzeln testbar und merged-faehig. Reihenfolge nach Nutzen/Aufwand.

| WP | Inhalt | Liefert (AK) | Abhaengigkeiten |
|---|---|---|---|
| WP0 | PR #1 reviewen/mergen; Branch als Basis sichern | – | – |
| WP1 | `context_model.py`: Objekte, Status-Lebenszyklus, Provenienz, Widerspruchsflags; Migration; Loops werden zu `task`-Objekten migriert (alte API bleibt) | 1 (teilw.), 4 | WP0 |
| WP2 | `attention.py` v1: Relevanz-Score (Dringlichkeit, Bedeutung, Konsequenz, Abhaengigkeiten, Delaegierbarkeit, letzte Bearbeitung, Arbeitskontext) + Digest mit **max. 3 begruendeten Punkten** + Unterbrechungsregeln in Config | 3, 7 | WP1 |
| WP3 | `commitments.py`: Extraktion aus eingehenden Texten (E-Mail/Chat): Wer erwartet was bis wann; Klassifikation Anfrage/Absicht/Zusage; **Anfrage default = nicht uebernommen** | 1, 2 | WP1 |
| WP4 | `autonomy.py`: Stufen L1/L2/L3, Permission-Matrix, Freigabe-Queue (`approvals`), Receipts, Eskalation; L3 nur fuer ausdruecklich freigegebene Aktionen | 5, 6 | WP1 |
| WP5 | `providers.py`: Tiers lokal/guenstig/stark, zentrale Auswahl in Config, Fallback-Kette, Kosten/Usage-Log, Outage-tolerant | 8 | WP0 |
| WP6 | `scopes.py`: privat/beruflich, Redaction vor externen Modell-Calls, Berechtigungen pro Connector/Tool | 9 | WP1, WP5 |
| WP7 | Schreibende Connectors hinter L3: Kalender-Termin, Task anlegen, E-Mail-Entwurf (nie Versand ohne Freigabe) | 6 (teilw.) | WP4, WP6 |
| WP8 | Interaktion: Abend-Abschluss (`pos close`), Morgen-Ueberblick via Attention Engine, `pos chat` (NL) | 7 | WP2 |
| WP9 | `preferences.py`: aus Korrekturen lernen, versioniert, loeschbar, mit Quelle; Korrektur propagiert in kuenftige Bewertungen | 10 | WP2, WP4 |
| WP10 | E2E-Testsuite: alle 10 AK als automatisierte Szenarien (siehe §5) | alle | alle |

**Reihenfolge-Empfehlung:** WP1 → WP2 → WP3 → WP4 → WP5 → WP6 → WP7 → WP8 → WP9, WP10 begleitend.

---

## 4. Aufwandsschaetzung & Kosten

Annahme: Solo-Entwicklung, Python, bestehende Test-/Hook-Infrastruktur.

| WP | Aufwand (Personentage) |davon Tests |
|---|---|---|
| WP1 Kontextmodell + Migration | 3–4 | ~40 % |
| WP2 Attention Engine v1 | 2–3 | ~40 % |
| WP3 Commitment-Erkennung | 3 | ~50 % |
| WP4 Autonomie/Freigaben/Receipts | 3–4 | ~40 % |
| WP5 Provider-Router | 2 | ~40 % |
| WP6 Scopes/Redaction | 2 | ~40 % |
| WP7 Schreibende Connectors | 3 | ~40 % |
| WP8 Interaktion (close/chat) | 1–2 | ~30 % |
| WP9 Praeferenzen/Lernen | 3 | ~40 % |
| **Summe MVP bis WP6** | **~15–19 PT** | |
| **Summe vollstaendig (bis WP9)** | **~22–28 PT** | |

Modell- und Betriebskosten (bei taeglicher Nutzung):
- **Lokal (Ollama o.ae.)**: Klassifikation, Extraktion, Hintergrund — **0 EUR**, laeuft offline, AK 8 erfuellt.
- **Guenstige Cloud-Tier** fuer Zusammenfassungen/Routine: typisch **$0,10–0,50/Tag** (wenige k Tokens/Aufruf) → **~3–15 EUR/Monat**.
- **Starkes Modell** nur fuer Planung/Reflexion/schwierige Entscheidungen, manuell oder nach Freigabe: wenige Cent pro Session → **~1–5 EUR/Monat**.
- **Gesamt realistisch: 0 EUR (rein lokal) bis ~20 EUR/Monat** mit Cloud-Tiers; Provider-Router ermoeglicht jederzeit Wechsel/Abschalten.
- Betrieb: keine Infrastruktur, SQLite lokal, REST optional auf 127.0.0.1 — **0 EUR Serverkosten**.

---

## 5. Erster vollstaendig testbarer End-to-End-Anwendungsfall

**Szenario: "E-Mail-Bitte wird zur nachvollziehbaren, delegierbaren Verpflichtung – ohne dass etwas aus dem Blick geraet."**

Ablauf (alles lokal testbar mit Fake-Connector, keine echten externen Calls):

1. **Inbound**: simulierte E-Mail: *"Kannst du mir die Unterlagen bis Donnerstag schicken?"* → `commitments.py` erzeugt Objekt `commitment` mit Status **`anfrage`** (nicht `zugesagt`), Quelle = E-Mail-ID, Frist = Donnerstag, erwartende Person extrahiert. (AK 1, 2)
2. **Abend-Abschluss** (`pos close`): Mini-OS listet die offene Anfrage als Entscheidungsfrage („uebernehmen? ja/nein/spaeter“). User sagt „ja“ → Status **`zugesagt`**, Loop mit naechster Aktion entsteht. (AK 2)
3. **Morgen-Ueberblick** (`pos digest`): Attention Engine bewertet: berufliche Routine-Loops vs. private Zusage → Digest zeigt **max. 3 Punkte, jeder mit Begruendung** („Zusage an <Person> bis Do, Konsequenz: …“). (AK 3, 7)
4. **Delegation L2**: `pos delegate "Entwurf fuer die Unterlagen vorbereiten"` → Agent recherchiert im Gedächtnis, erstellt Entwurf, legt ihn zur **Freigabe** vor (`approvals`), fuehrt **keine** externe Aktion aus. (AK 6)
5. **Freigabe + Nachweis**: User gibt frei → `receipts` protokolliert Aktion; Status bleibt `offen` bis Nachweis der Erledigung (z. B. als done markiert) – vorher wird die Aufgabe **weiterhin** im Digest gefuehrt. (AK 4, 5)
6. **Korrektur**: User weist den Digest-Punkt einmal zurueck → `preferences.py` speichert korrigierbare Praeferenz mit Quelle; kuenftige Bewertungen beruecksichtigen sie nachweisbar. (AK 10)

Test: eine Datei `tests/test_mini_os_e2e.py` mit 6–10 Assertions, die exakt diese Kette gegen ein temporäres `POS_HOME` durchspielt (kein Netzwerk, kein echter Provider – deterministischer Offline-Agent bzw. Fake-Provider).

---

## Offene Fragen an den Auftraggeber (zur Feinabstimmung vor WP1)

1. Welche Systeme sollen **zuerst** angebunden werden (E-Mail + Kalender als Klasse 1)?
2. Soll es von Anfang an **lokale Modelle** geben (Ollama), oder erst rein deterministisch starten?
3. Welche Handlungen duerfen jemals **Stufe L3** (kontrolliert ausfuehren) – z. B. nie Versand von E-Mails ohne Klick?

---

## WP1-Abnahmebericht (unabhaengige Pruefung)

Pruefstand: Branch `vibe/personal-os-4e2dc9`, Review-Commit siehe git log
(«review(personal-os): WP1 acceptance fixes …»). Tests: 83 gesamt OK
(65 bestehende + 18 neue Negativtests in `tests/test_personal_os_wp1_review.py`),
pre-commit clean, CLI-/REST-/MCP-Smoke durchgefuehrt.

### Befunde und Korrekturen (alle WP1-intern, jeweils mit Regressionstest)

1. **A2 – KG-Leck in `ask(scope=...)` (relevant, behoben):** `related_entities`
   griff auf den globalen KG zu; private Entitaeten konnten ueber Work-Treffer
   durchsickern (`memory.py`). Fix: bei gesetztem Scope werden nur Entitaeten
   geliefert, die auch in Items desselben Scopes vorkommen. Test:
   `test_related_entities_do_not_leak_private_via_kg`.
2. **A2/A3 – REST-Lecks fuer Token-Clients (relevant, behoben):** `/today`,
   `/digest`, `/delegations` lieferten alle Scopes; `/loops/{id}/done` pruefte
   keine Schreibberechtigung am Loop-Scope (`server.py`). Fix: externe Subjekte
   bekommen Scope `work`; Loop-Abschluss und Delegationsliste gefiltert.
   Tests: `test_rest_token_cannot_escalate`, `test_today_scope_filter`.
3. **A4 – Redaction-Luecke bei meta-Scopes (relevant, behoben):**
   `redact_for_external` erkannte Delegationen (`meta.scope`) nicht und liess
   `instruction` durch (`scopes.py`). Fix: effektiver Scope auch aus `meta`;
   private Dicts werden auf Stub `{id, scope, redacted}` reduziert.
   Tests: `test_redact_delegation_payload_with_meta_scope`, `test_redact_nested_mixed_payload`.
4. **A5 – `valid_until` wurde gespeichert, aber nie gefiltert (nachgelagert, behoben):**
   `ContextModel.list()` filtert abgelaufene Objekte jetzt default (`include_expired=True` zum Einblenden).

### Verbleibende, dokumentierte Grenzen (nachgelagert)

- **Strukturelle vs. inhaltliche Isolation:** Redaction arbeitet an Scope-Feldern, nicht
  am Textinhalt. Ein als `work` markierter Eintrag mit privatem Inhalt wird nicht
  zurueckgehalten (Test `test_structural_boundary_work_object_with_private_text_passes`
  dokumentiert das). Inhaltliche Klassifikation ist Aufgabe von WP3/WP5; konservativer
  Default-Scope `private` begrenzt das Risiko.
- **Ohne `POS_TOKEN` ist jeder Loopback-Client `owner`** (127.0.0.1 only). MCP-stdio
  gilt als Owner-Kanal (lokaler stdio); REST mit Token als `external`.
- **Dedup per Content-Hash ist scope-uebergreifend** (gleiches Duplikat in beiden Scopes
  wird als Duplikat erkannt, bestehender Eintrag bleibt erhalten).
- **SQLite at rest unverschluesselt** (WP6+ optionale Erweiterung).

### Entscheidung

**WP1 ist abnahmefaehig.** Alle 83 Tests bestehen, keine offenen Blocker,
Scope-Isolation auf Store/Memory/Loops/Kontext/CLI/REST/MCP nachgewiesen,
Migration idempotent und bestandserhaltend, Provenienz/Statushistorie/Konflikte
nachvollziehbar. WP3 (Commitment-Erkennung) kann auf dieser Grundlage sicher
implementiert werden (eigene Schicht `commitments.py` auf `context_model`).

---

## WP3-Abnahmebericht (unabhaengige Pruefung, Basis f8344cd)

Pruefstand: Review-Commit siehe git log. Tests: **111 gesamt OK**
(98 bisherige + 13 neue in `tests/test_personal_os_wp3_review.py`, inkl. frischem
23-Satz-Korpus A5), pre-commit clean.

### Befunde & Korrekturen (alle WP3-intern, mit Regressionstests)

1. **Unbegruendete Verbindlichkeit bei hypothetischen Aussagen (kritisch, behoben):**
   "Ich schicke es vielleicht nächste Woche." / "Ich glaube, ich schicke es..." /
   "Ich nehme mir vor, ..." wurden als `committed` erkannt. Fix in `commitments.py`:
   HYPOTHETICAL_RE stuft auf `intent` (0.5) herab; INTENT_RE vor OWN_RE;
   "ich nehme mir vor"/"ich entscheide mich" -> intent.
2. **Fremde Zusagen nicht erkannt (relevant, behoben):** "Anna hat zugesagt, ..."
   -> NONE. Fix: FOREIGN_RE -> `foreign_commitment`/`committed` (party=other, person).
3. **Explizite Versprechen nicht erkannt (relevant, behoben):** "Ich verspreche, ..."
   (Komma nach Verb) -> NONE. Fix: optionales Komma in OWN_RE + "verspreche".
4. **Rhetorische/negative Anfragen falsch als request (relevant, behoben):**
   "Kannst du mir sagen, wann du kommst?" / "Kannst du das nicht machen?" -> NONE
   (QUESTION_RE + Negations-Guard).
5. **Mehrere Verpflichtungen in einer Nachricht (relevant, behoben):** nur die erste
   wurde erkannt. Fix: `_segments()` zerlegt auf Satzgrenzen + "und"/"sowie".
6. **Dubletten bei abweichenden Formulierungen (relevant, behoben):** "Ich schicke
   dir die Unterlagen..." vs. "Ich schicke die Unterlagen..." ergaben 2 Objekte.
   Fix: `_norm_title()` streicht fuehrende Pronomen/Artikel beim Dedup.
7. **"muss ich"-Obligationen (nachgelagert, behoben):** "Morgen muss ich zum Arzt."
   -> `mentioned` (obligation, 0.55), nie committed.

### Bekannte False Negatives (dokumentiert, akzeptiert)

"Vielleicht schicke ich es nächste Woche." (invertierte Wortstellung) -> kein
Commitment; "Erinnerst du dich, dass ich dir das Buch leihe?" -> NONE. Beides
lieber FN als unbegruendete Verbindlichkeit; LLM-Provider (WP5) kann spaeter
nachschaerfen.

### Entscheidung

**WP3 ist abnahmefaehig.** Keine kritischen Fehlklassifikationen mit unbegruendeter
Verbindlichkeit mehr; Lebenszyklus/Provenienz/Scope-Isolation korrekt; wiederholte
Verarbeitung erzeugt keine Dubletten. **WP2 (Attention Engine) ist technisch
freigegeben** (Bewertung kann direkt auf commitment-Objekten mit Status/Frist/
Konfidenz/Scope aufsetzen).
