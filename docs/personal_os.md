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
