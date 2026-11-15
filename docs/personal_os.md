# Personal OS – dein persönliches KI-Operating-System

Ein lokaler Ort, in den **all dein relevantes Wissen hineinfließt**, der dir hilft, die
wichtigen Dinge zu **organisieren**, zu **finden** und ggf. zu **delegieren** – gebaut
auf Semantica (Knowledge Graph + semantische Suche), aber komplett **local-first** und
ohne API-Key sofort nutzbar.

Gedacht für Menschen, die täglich tief in KI-Systemen arbeiten und trotzdem die privaten,
wichtigen Dinge nicht verlieren wollen (z. B. mit ADHS): ein klarer Tages-Digest, offene
Loops mit nächster Aktion, Stale-Erkennung und Delegation an Agenten.

## Schnellstart

```bash
pip install -e .            # installiert u. a. den Befehl `pos`
pos init                    # Datenverzeichnis anlegen (~/.personal_os, sonst $POS_HOME)

pos capture "Projekt Phoenix: Kickoff Juni, Team Berlin, Budget 50k. Maria leitet das Projekt." --tags phoenix
pos capture "Rezept Pancakes: Mehl, Eier, Milch, Salz."
pos ask "Wie hoch ist das Budget von Phoenix?"

pos loop add "Zahnarzt morgen wichtig #gesundheit → Praxis anrufen"
pos loop list
pos digest                  # Tages-Digest: Top-Thema, fällig, überfällig, stale, Delegationen

pos delegate add "Erinnere mich daran, die Versicherung morgen anzurufen #finanzen" --run
pos sync                    # alle konfigurierten Connectors einspeisen
pos status
```

Oder ohne Installation:

```bash
python -m personal_os digest
```

## Konzept

| Baustein | Modul | Zweck |
|---|---|---|
| Inbox / Capture | `personal_os/inbox.py` | Ein Eingang für alles: Text, Datei, URL, Connector |
| Langzeitgedächtnis | `personal_os/memory.py` | Entitäten + Tripletts + Embeddings, hybride Suche (`pos ask`), KG als `kg.json` |
| Open Loops | `personal_os/loops.py` | Aufgaben mit Fälligkeit, Wiederholung, Snooze, nächster Aktion |
| Digest | `personal_os/digest.py` | `pos today` / `pos digest` / `pos weekly` – ADHS-freundlich gekappt |
| Delegation | `personal_os/delegate.py` | Agenten mit Tools (Gedächtnis fragen, capturen, Loops anlegen) |
| Connectors | `personal_os/connectors/` | filesystem, git, E-Mail (IMAP), Web/RSS, externe MCP-Server |
| Anschlüsse | `personal_os/server.py`, `personal_os/mcp_server.py` | REST nur auf `127.0.0.1`, MCP über stdio |
| CLI | `personal_os/cli.py` | `pos …` bzw. `python -m personal_os …` |

## Anschließen: externe Systeme → OS

In `~/.personal_os/config.json` (oder `$POS_HOME/config.json`):

```json
{
  "connectors": {
    "filesystem": {"path": "~/notes"},
    "git": {"path": "/pfad/zum/repo"},
    "web": {"urls": ["https://example.com/briefing"], "rss": ["https://example.com/feed.xml"]},
    "email": {"folder": "INBOX", "max_mails": 20},
    "mcp": {"command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/pfad"], "tool": "read_file", "arguments": {}}
  }
}
```

- **E-Mail**: Zugangsdaten nur über Umgebungsvariablen `POS_EMAIL_HOST`, `POS_EMAIL_USER`,
  `POS_EMAIL_PASSWORD` (niemals in die Config schreiben).
- Danach: `pos sync` oder `POST /sync`.

## Anschließen: OS → externe KI-Tools

- **REST (lokal only)**: `pos serve` startet den Server **ausschließlich auf 127.0.0.1**
  (andere Hosts werden verweigert). Mit `POS_TOKEN` gesetzt braucht jeder Request
  `Authorization: Bearer <token>`. Endpunkte: `/health`, `/capture`, `/ask`, `/today`,
  `/digest?weekly=1`, `/loops`, `/loops/add`, `/loops/{id}/done`, `/delegate`,
  `/delegations`, `/sync`, `/stats`.
- **MCP (stdio)**: `pos mcp` stellt Tools wie `pos_capture`, `pos_ask`, `pos_today`,
  `pos_add_loop`, `pos_delegate`, `pos_sync` bereit – z. B. in Claude Desktop:

```json
{"mcpServers": {"personal-os": {"command": "pos", "args": ["mcp"]}}}
```

## ADHS-freundliche Workflows

- `pos digest` zeigt **eine** Top-Aufgabe, fällige/überfällige Loops, „lange nicht angefasst“
  (stale) und laufende Delegationen – pro Sektion begrenzt (`adhd.max_items_per_section`).
- Loops aus Freitext: `pos loop add "Müll rausbringen morgen #haushalt"` – erkennt
  `heute/morgen/in N Tagen/Wochentag/dd.mm.jjjj`, `wichtig/dringend`, `täglich/wöchentlich/…`,
  `#tags` und `→ nächste Aktion`.
- Wiederkehrende Loops legen nach `done` automatisch den nächsten an; `snooze` verschiebt.
- `pos weekly` als Wochen-Review.

## Delegation

`pos delegate add "…" --run` – ohne konfiguriertes LLM läuft ein deterministischer
Offline-Agent, der z. B. „Erinnere mich …“ in einen Loop übersetzt oder „Was weiß ich über X?“
aus dem Gedächtnis beantwortet. Mit `llm` in der Config (OpenAI-kompatibles Endpoint, Key nur
via `POS_LLM_API_KEY`) läuft ein Tool-Calling-Agent. Jeder Tool-Call wird im Trace gespeichert.

## Sicherheit

- Server bindet nur an Loopback und verweigert Nicht-Loopback-Hosts.
- Secrets ausschließlich über Umgebungsvariablen (`POS_TOKEN`, `POS_EMAIL_*`, `POS_LLM_API_KEY`).
- Alles liegt lokal in `$POS_HOME` (Default `~/.personal_os`): `config.json`, `store.db`, `kg.json`.

## Entwicklung

```bash
python -m unittest tests.test_personal_os_core tests.test_personal_os_loops_digest \
  tests.test_personal_os_delegate tests.test_personal_os_connectors_api
```

 siehe auch `examples/personal_os_example.py`.

## WP1: Kontextmodell, Scopes, Provenienz, Berechtigungen

Ab Version 0.2.0 (Mini-OS WP1):

- **Scopes**: Jeder Capture und jeder Loop traegt `scope` (`private` | `work`, Default `private`).
  `pos ask "..." --scope work` liefert **niemals** private Daten; ohne Scope sieht nur der Owner alles.
  Gleicher Mechanismus in REST (`?scope=`) und MCP (`scope`-Argument).
- **Kontextmodell** (`personal_os/context_model.py`): typtisierte Objekte
  (`person|area|project|task|commitment|decision|routine|goal|event`) mit Status-Lebenszyklus
  `mentioned → intent → committed → done` (+ `rejected`), Provenienz (`source`, `source_item_id`,
  `created_by`), `confidence`, `valid_from/valid_until` und `history`. Widersprueche werden als
  `conflicts_with`-Link markiert, nie stillschweigend ueberschrieben; `resolve_conflict` setzt
  `superseded_by` (Nachweis bleibt erhalten). CLI: `pos context add|list|transition`.
- **Berechtigungen** (`personal_os/permissions.py`): Subjekte `owner` / `agent` / `external`.
  Default: externe Modellaufrufe nur fuer Scope `work` (und dort redacted); `private` ist fuer
  externe Subjekte immer verweigert. Ausnahmen nur per explizitem `grant` + Config-Flag
  `privacy.external_can_see_private`. REST-Clients mit `POS_TOKEN` gelten als `external`
  (lesen/schreiben nur `work`, explizite private-Anfrage → 403).
- **Redaction**: `redact_for_external()` / MCP-Tool `pos_redact` entfernen private Inhalte
  (nur ID/Scope bleiben als Nachweis) aus jeder Payload fuer externe Modelle.
- **Migration**: additiv und idempotent (`ALTER TABLE ... ADD COLUMN scope`, neue Tabellen
  `context_objects`, `object_links`, `permissions`). Bestehende Datenbanken und Daten bleiben
  vollstaendig erhalten (getestet gegen Alt-Schema).
- **Delegation**: Delegationen haben einen Scope; externe LLM-Calls werden nur ausgefuehrt,
  wenn der Scope dafuer freigegeben ist, sonst Fallback auf den deterministischen Offline-Agenten
  mit Hinweis im Ergebnis.

## WP3: Commitment-Erkennung (`commitments.py`)

Deterministischer, offline arbeitender Detector auf dem WP1-Kontextmodell.

- **Unterscheidung:** Erwähnung (`mentioned`, Konfidenz 0.4) vs. Absicht (`intent`, 0.6)
  vs. eigene verbindliche Zusage (`committed`, 0.9) vs. fremde Anfrage (`request_to_me`
  → `mentioned`, 0.75, erst nach `confirm` → `committed`) vs. Erledigung (`done`) /
  Absage (`rejected`). Unklare Fälle werden nie stillschweigend verbindlich.
- **Extraktion:** Frist via `parse_due`, Person via `@mention`/Präposition,
  Scope 1:1 vom Quell-Item (keine automatische Hochstufung private→work).
- **Dedup & Konflikte:** identische Verpflichtung (Titel+Scope+Frist) → Duplikat;
  abweichende Frist → WP1-Konfliktlogik (`conflicts_with`); erledigte/verorfene
  werden durch erneute Erwähnung **nicht** wieder geöffnet.
- **Provenienz:** `source`, `source_item_id`, `created_by`, Konfidenz, Status-History.
- **Integration:** Capture-Hook in `inbox.capture` (fehlergesichert, nicht-destruktiv);
  CLI `pos commitments list|scan|confirm|close`; REST `/commitments`,
  `/commitments/scan`, `/commitments/{id}/transition` (externe Subjekte nur `work`,
  Schreiben geprüft); MCP `pos_commitments_list|scan|transition`.

## WP2: Attention Engine (`attention.py`)

Deterministische, erklaerbare Bewertungsschicht (read-only: keine Statusaenderungen,
kein LLM, keine Planung). Bewertet Kontextobjekte + offene Loops.

- **Gewichtung (explizit in `WEIGHTS`):** Dringlichkeit (ueberfaellig 30+5/Tag max 7d,
  heute 30, <=3d 18, <=7d 10) · Verbindlichkeit (committed 25 / intent 10 /
  mentioned 5) · Kontext nur ueber vorhandene Links (blocks/depends_on +15,
  goal_of/part_of/works_on +10) · stale +10. Niedrige Konfidenz mindert den Score
  NICHT, sondern erzeugt Klaerungsbedarf (`missing_info`).
- **Erklaerbarkeit (A2):** jedes Item enthaelt Objekt, Scope, Score, Priority
  (p1>=60/p2>=35/p3), Kategorie (action/clarification/observe), Faktoren, Grund-Text,
  Quellen, `evaluated_at`, `missing_info`; Evaluierungen werden in der additiven
  Tabelle `attention_evals` protokolliert.
- **Attention statt Aufgabenflut (A3):** Dedup ueber normierten Titel+Scope;
  done/rejected/abgelaufene/snoozed Objekte ausgeschlossen.
- **Integration:** Daily Digest um "Aufmerksamkeitspunkte" (max `adhd.attention_points`=3)
  erweitert, Weekly Review um Kategorie-Summen; bestehende Digest-Funktionen bleiben.
- **Schnittstellen (lesend):** CLI `pos attention [--scope] [--limit]`,
  REST `GET /attention`, MCP `pos_attention`; WP1-Scope-Regeln greifen (external nur work).
