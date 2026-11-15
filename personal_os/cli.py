"""Kommandozeile fuers Personal OS: ``python -m personal_os ...`` bzw. ``pos ...``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .core import PersonalOS


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pos",
        description=(
            "Dein persoenliches KI-Operating-System: Wissen sammeln, "
            "finden, Loops am Laufen halten, delegieren."
        ),
    )
    p.add_argument(
        "--data-dir",
        default=None,
        help="Datenverzeichnis (sonst POS_HOME oder ~/.personal_os)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Datenverzeichnis und Default-Konfiguration anlegen")

    c = sub.add_parser("capture", help="Text ins Wissensgedaechtnis schreiben")
    c.add_argument("text")
    c.add_argument("--kind", default="note")
    c.add_argument("--source", default="cli")
    c.add_argument("--tags", default="", help="kommagetrennt")
    c.add_argument("--scope", default=None, choices=["private", "work"])

    c = sub.add_parser("file", help="Datei ins Wissensgedaechtnis laden")
    c.add_argument("path")
    c.add_argument("--scope", default=None, choices=["private", "work"])

    c = sub.add_parser("url", help="Webseite ins Wissensgedaechtnis laden")
    c.add_argument("url")
    c.add_argument("--scope", default=None, choices=["private", "work"])

    c = sub.add_parser("ask", help="Frage gegen das Wissensgedaechtnis")
    c.add_argument("query")
    c.add_argument("--limit", type=int, default=5)
    c.add_argument(
        "--scope",
        default=None,
        choices=["private", "work"],
        help="nur dieser Scope (work sieht niemals private Daten)",
    )

    c = sub.add_parser("context", help="Kontext-Objekte verwalten (WP1)")
    ctx_sub = c.add_subparsers(dest="context_command", required=True)
    a = ctx_sub.add_parser("add", help="Objekt anlegen")
    a.add_argument(
        "type", help="person|area|project|task|commitment|decision|routine|goal|event"
    )
    a.add_argument("title")
    a.add_argument("--scope", default="private", choices=["private", "work"])
    a.add_argument("--status", default="mentioned")
    a.add_argument("--source", default="cli")
    ll = ctx_sub.add_parser("list", help="Objekte listen")
    ll.add_argument("--type", default=None)
    ll.add_argument("--scope", default=None, choices=["private", "work"])
    ll.add_argument("--status", default=None)
    t = ctx_sub.add_parser("transition", help="Status wechseln")
    t.add_argument("id")
    t.add_argument("status")

    sub.add_parser("today", help="Tages-Digest anzeigen")
    sub.add_parser("digest", help="Tages-Digest als Text")
    sub.add_parser("weekly", help="Wochen-Review als Text")

    c = sub.add_parser("loop", help="Loops verwalten")
    loop_sub = c.add_subparsers(dest="loop_command", required=True)
    a = loop_sub.add_parser(
        "add",
        help="Loop aus Freitext anlegen (z. B. 'Muell rausbringen morgen #haushalt')",
    )
    a.add_argument("text")
    ll = loop_sub.add_parser("list", help="Loops listen")
    ll.add_argument("--status", default="open")
    ll.add_argument("--scope", default=None, choices=["private", "work"])
    d = loop_sub.add_parser("done", help="Loop abschliessen")
    d.add_argument("id")
    s = loop_sub.add_parser("snooze", help="Loop verschieben")
    s.add_argument("id")
    s.add_argument("--days", type=int, default=1)

    c = sub.add_parser("delegate", help="Aufgabe delegieren")
    dsub = c.add_subparsers(dest="delegate_command", required=True)
    a = dsub.add_parser("add", help="Delegation anlegen")
    a.add_argument("instruction")
    a.add_argument("--agent", default="default")
    a.add_argument("--run", action="store_true", help="sofort ausfuehren")
    r = dsub.add_parser("run", help="Delegation ausfuehren")
    r.add_argument("id")
    dl = dsub.add_parser("list", help="Delegationen listen")
    dl.add_argument("--status", default=None)

    c = sub.add_parser("sync", help="Alle Connectors synchronisieren")
    c.add_argument("--connector", default=None)

    c = sub.add_parser("commitments", help="WP3: Verpflichtungen erkennen/verwalten")
    csub = c.add_subparsers(dest="commitments_command", required=True)
    cl = csub.add_parser("list", help="Commitments listen")
    cl.add_argument("--scope", default=None, choices=["private", "work"])
    cl.add_argument("--status", default=None)
    cs = csub.add_parser("scan", help="Text auf Commitments scannen")
    cs.add_argument("text")
    cs.add_argument("--scope", default="private", choices=["private", "work"])
    cs.add_argument("--source", default="cli")
    cf = csub.add_parser("confirm", help="Anfrage/Absicht als verbindlich bestaetigen")
    cf.add_argument("id")
    cd = csub.add_parser("close", help="Commitment abschliessen (done/rejected)")
    cd.add_argument("id")
    cd.add_argument("--status", default="done", choices=["done", "rejected"])

    c = sub.add_parser("attention", help="WP2: Aufmerksamkeitspunkte mit Begruendung")
    c.add_argument("--scope", default=None, choices=["private", "work"])
    c.add_argument("--limit", type=int, default=None)

    sub.add_parser("status", help="Uebersicht ueber das OS")

    c = sub.add_parser("serve", help="lokalen API-Server starten (nur 127.0.0.1)")
    c.add_argument("--port", type=int, default=None)

    sub.add_parser(
        "mcp", help="MCP-Server ueber stdio starten ( fuer externe KI-Tools )"
    )

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    core = PersonalOS(args.data_dir)

    if args.command == "init":
        core.config.save()
        print(f"Personal OS initialisiert in {core.config.data_dir}")
        print("Config: config.json | Speicher: store.db | KG: kg.json")
    elif args.command == "capture":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        item = core.capture(
            args.text, kind=args.kind, source=args.source, tags=tags, scope=args.scope
        )
        scope = item.get("scope", "private")
        print(
            "Duplikat – bereits gespeichert."
            if item.get("duplicate")
            else f"Gespeichert als {item['id']} ({item['kind']}, scope={scope})."
        )
    elif args.command == "file":
        item = core.capture_file(args.path, scope=args.scope)
        print(
            "Duplikat – bereits gespeichert."
            if item.get("duplicate")
            else f"Datei gespeichert als {item['id']} (scope={item.get('scope')})."
        )
    elif args.command == "url":
        item = core.capture_url(args.url, scope=args.scope)
        print(
            "Duplikat – bereits gespeichert."
            if item.get("duplicate")
            else f"URL gespeichert als {item['id']} (scope={item.get('scope')})."
        )
    elif args.command == "ask":
        result = core.ask(args.query, limit=args.limit, scope=args.scope)
        if not result["results"]:
            print("Keine Treffer.")
        for r in result["results"]:
            snippet = r["content"].replace("\n", " ")[:140]
            print(
                f"[{r['score']:.3f}] ({r['kind']}, {r.get('source') or '-'}) {snippet}"
            )
        if result["related_entities"]:
            ents = ", ".join(str(e.get("id")) for e in result["related_entities"][:8])
            print(f"Verknuepfte Entitaeten: {ents}")
    elif args.command == "context":
        if args.context_command == "add":
            obj = core.context.add_object(
                type_=args.type,
                title=args.title,
                scope=args.scope,
                status=args.status,
                source=args.source,
            )
            note = (
                f" (Konflikt mit {obj['conflict_with']})"
                if obj.get("conflict_with")
                else ""
            )
            print(
                f"Objekt angelegt: {obj['id']} "
                f"[{obj['type']}/{obj['scope']}/{obj['status']}]{note}"
            )
        elif args.context_command == "list":
            objs = core.context.list(
                type_=args.type, scope=args.scope, status=args.status
            )
            for o in objs:
                print(
                    f"{o['id']}  [{o['type']}/{o['scope']}/{o['status']}] {o['title']}"
                )
            if not objs:
                print("Keine Objekte.")
        elif args.context_command == "transition":
            obj = core.context.transition(args.id, args.status)
            print(f"{obj['id']}: {obj['status']}")
    elif args.command == "today":
        _print_json(core.today())
    elif args.command == "digest":
        print(core.digest_text())
    elif args.command == "weekly":
        print(core.weekly_text())
    elif args.command == "loop":
        if args.loop_command == "add":
            loop = core.add_loop_from_text(args.text)
            due = f", faellig {loop['due']}" if loop.get("due") else ""
            prio = loop["priority"]
            print(f"Loop angelegt: {loop['id']} – {loop['title']}{due} (P{prio})")
        elif args.loop_command == "list":
            loops = core.list_loops(status=args.status, scope=args.scope)
            if not loops:
                print("Keine Loops.")
            for lp in loops:
                due = lp.get("due") or "-"
                prio = lp.get("priority", 1)
                line = (
                    f"{lp['id']} [{lp['status']}] P{prio} faellig {due} {lp['title']}"
                )
                print(line)
        elif args.loop_command == "done":
            loop = core.complete_loop(args.id)
            print("Erledigt." if loop else f"Loop {args.id} nicht gefunden.")
        elif args.loop_command == "snooze":
            loop = core.snooze_loop(args.id, days=args.days)
            print(
                f"Verschoben bis {loop['snooze_until']}."
                if loop
                else f"Loop {args.id} nicht gefunden."
            )
    elif args.command == "delegate":
        if args.delegate_command == "add":
            d = core.delegate(args.instruction, agent=args.agent)
            if args.run:
                d = core.run_delegation(d["id"])
            print(f"Delegation {d['id']} [{d['status']}] an {d['agent']}")
            if d.get("result"):
                print(d["result"])
        elif args.delegate_command == "run":
            d = core.run_delegation(args.id)
            if not d:
                print(f"Delegation {args.id} nicht gefunden.")
            else:
                print(f"[{d['status']}] {d['result']}")
        elif args.delegate_command == "list":
            for d in core.list_delegations(status=args.status):
                instr = d["instruction"][:70]
                print(f"{d['id']}  [{d['status']}] {d['agent']}: {instr}")
    elif args.command == "sync":
        _print_json(core.sync(connector=args.connector))
    elif args.command == "commitments":
        if args.commitments_command == "list":
            objs = core.commitments.list(scope=args.scope, status=args.status)
            for o in objs:
                due = (o.get("meta") or {}).get("due") or "-"
                resp = (o.get("meta") or {}).get("responsible") or "-"
                print(
                    f"{o['id']}  [{o['scope']}/{o['status']}] bis {due}  "
                    f"({resp}) {o['title']}"
                )
            if not objs:
                print("Keine Commitments.")
        elif args.commitments_command == "scan":
            found = core.commitments.scan_text(
                args.text, source=args.source, scope=args.scope
            )
            if not found:
                print("Kein Commitment erkannt.")
            for f in found:
                o = f["object"]
                dup = " (Duplikat)" if f.get("duplicate") else ""
                print(
                    f"erkannt{dup}: {o['id']} [{o['status']}] Konfidenz "
                    f"{o['confidence']} – {o['title']}"
                )
        elif args.commitments_command == "confirm":
            o = core.commitments.confirm(args.id)
            print(f"{o['id']}: {o['status']}")
        elif args.commitments_command == "close":
            o = core.commitments.close(args.id, status=args.status)
            print(f"{o['id']}: {o['status']}")
    elif args.command == "attention":
        result = core.attention_points(scope=args.scope, limit=args.limit)
        if not result["items"]:
            print("Keine Aufmerksamkeitspunkte.")
        for a in result["items"]:
            print(
                f"[{a['priority']}] ({a['category']}, Score {a['score']}) "
                f"{a['title']} – {a['reason']}"
            )
            if a.get("missing_info"):
                print(f"    fehlt: {', '.join(a['missing_info'])}")
    elif args.command == "status":
        _print_json(core.stats())
    elif args.command == "serve":
        from .server import main as serve_main

        serve_main(data_dir=args.data_dir, port=args.port)
    elif args.command == "mcp":
        from .mcp_server import main as mcp_main

        mcp_main(data_dir=args.data_dir)
    core.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
