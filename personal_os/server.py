"""Lokaler REST-API-Server fuer das Personal OS (immer Loopback-only).

Bindet standardmaessig nur an 127.0.0.1. Wenn ``POS_TOKEN`` gesetzt ist,
braucht jeder Request einen ``Authorization: Bearer <token>``-Header; solche
Clients gelten als Subjekt ``external`` und sehen/duerfen nur den Scope
``work`` (WP1: private Daten sind fuer externe Subjekte gesperrt, sofern nicht
ausdruecklich per Permission freigegeben). Ohne Token gilt man als ``owner``.
"""

from __future__ import annotations

import os
from typing import Optional

from .core import PersonalOS
from .scopes import PRIVATE, WORK

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def create_app(core: PersonalOS):
    """Starlette-App mit JSON-Endpunkten (Import von starlette erst hier)."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    token = os.environ.get(core.config.server.token_env, "")

    def subject(request: Request) -> str:
        return "external" if token else "owner"

    def unauthorized() -> JSONResponse:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    async def check_auth(request: Request):
        if token and request.headers.get("authorization") != f"Bearer {token}":
            return unauthorized()
        return None

    def resolve_read_scope(request: Request, requested: Optional[str]):
        """Lese-Scope. External sieht nie private; explizit private -> 403."""
        subj = subject(request)
        if subj == "owner":
            return requested, None
        if requested == PRIVATE:
            return None, JSONResponse(
                {"error": "Scope 'private' ist fuer externe Clients gesperrt"},
                status_code=403,
            )
        return WORK, None

    def check_write(request: Request, scope: str):
        """Schreibzugriff; External darf nur freigegebene Scopes schreiben."""
        subj = subject(request)
        if subj == "owner":
            return None
        if not core.permissions.check(subj, "write", scope):
            return JSONResponse(
                {"error": f"Subjekt '{subj}' darf Scope '{scope}' nicht schreiben"},
                status_code=403,
            )
        return None

    async def health(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        return JSONResponse(
            {"status": "ok", "os": "personal_os", "profile": core.config.profile_name}
        )

    async def capture_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        body = await request.json()
        scope = body.get("scope") or None
        denied_write = check_write(
            request, scope or core.config.privacy.default_capture_scope
        )
        if denied_write:
            return denied_write
        try:
            item = core.capture(
                body.get("content", ""),
                kind=body.get("kind", "note"),
                source=body.get("source", "api"),
                tags=body.get("tags", []),
                scope=scope,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(item)

    async def ask_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        if request.method == "POST":
            body = await request.json()
            query, limit = body.get("query", ""), int(body.get("limit", 5))
            requested = body.get("scope") or None
        else:
            query = request.query_params.get("query", "")
            limit = int(request.query_params.get("limit", 5))
            requested = request.query_params.get("scope") or None
        if not query:
            return JSONResponse({"error": "query fehlt"}, status_code=400)
        scope, err = resolve_read_scope(request, requested)
        if err:
            return err
        return JSONResponse(core.ask(query, limit=limit, scope=scope))

    async def context_list_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        requested = request.query_params.get("scope") or None
        scope, err = resolve_read_scope(request, requested)
        if err:
            return err
        objects = core.context.list(
            type_=request.query_params.get("type") or None,
            scope=scope,
            status=request.query_params.get("status") or None,
        )
        if subject(request) == "external":
            objects = core.redact_for_external(objects)
        return JSONResponse(objects)

    async def context_add_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        body = await request.json()
        scope = body.get("scope") or core.config.privacy.default_capture_scope
        denied_write = check_write(request, scope)
        if denied_write:
            return denied_write
        try:
            obj = core.context.add_object(
                type_=body.get("type", ""),
                title=body.get("title", ""),
                scope=scope,
                status=body.get("status", "mentioned"),
                confidence=float(body.get("confidence", 1.0)),
                valid_from=body.get("valid_from"),
                valid_until=body.get("valid_until"),
                source=body.get("source", "api"),
                source_item_id=body.get("source_item_id"),
                meta=body.get("meta", {}),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(obj)

    async def context_transition_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        body = await request.json()
        obj = core.context.get(request.path_params["obj_id"])
        if not obj:
            return JSONResponse({"error": "nicht gefunden"}, status_code=404)
        denied_write = check_write(request, obj.get("scope", PRIVATE))
        if denied_write:
            return denied_write
        try:
            obj = core.context.transition(
                request.path_params["obj_id"],
                body.get("status", ""),
                by=subject(request),
            )
        except (ValueError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(obj)

    async def today_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        return JSONResponse(core.today())

    async def digest_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        weekly = request.query_params.get("weekly") in ("1", "true", "yes")
        text = core.weekly_text() if weekly else core.digest_text()
        return JSONResponse({"text": text, "weekly": weekly})

    async def loops_list_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        status = request.query_params.get("status", "open")
        requested = request.query_params.get("scope") or None
        scope, err = resolve_read_scope(request, requested)
        if err:
            return err
        return JSONResponse(core.list_loops(status=status, scope=scope))

    async def loop_add_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        body = await request.json()
        text = body.get("text", "")
        if not text:
            return JSONResponse({"error": "text fehlt"}, status_code=400)
        scope = body.get("scope") or core.config.privacy.default_capture_scope
        denied_write = check_write(request, scope)
        if denied_write:
            return denied_write
        return JSONResponse(core.add_loop_from_text(text, scope=scope))

    async def loop_done_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        loop = core.complete_loop(request.path_params["loop_id"])
        if not loop:
            return JSONResponse({"error": "nicht gefunden"}, status_code=404)
        return JSONResponse(loop)

    async def delegate_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        body = await request.json()
        run = body.get("run", False)
        scope = body.get("scope") or core.config.privacy.default_capture_scope
        denied_write = check_write(request, scope)
        if denied_write:
            return denied_write
        d = core.delegate(
            body.get("instruction", ""),
            agent=body.get("agent", "default"),
            scope=scope,
        )
        if run:
            d = core.run_delegation(d["id"])
        return JSONResponse(d)

    async def delegations_list_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        status = request.query_params.get("status") or None
        return JSONResponse(core.list_delegations(status=status))

    async def sync_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        return JSONResponse(core.sync())

    async def stats_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        return JSONResponse(core.stats())

    routes = [
        Route("/health", health),
        Route("/capture", capture_ep, methods=["POST"]),
        Route("/ask", ask_ep, methods=["GET", "POST"]),
        Route("/context", context_list_ep),
        Route("/context/add", context_add_ep, methods=["POST"]),
        Route("/context/{obj_id}/transition", context_transition_ep, methods=["POST"]),
        Route("/today", today_ep),
        Route("/digest", digest_ep),
        Route("/loops", loops_list_ep),
        Route("/loops/add", loop_add_ep, methods=["POST"]),
        Route("/loops/{loop_id}/done", loop_done_ep, methods=["POST"]),
        Route("/delegate", delegate_ep, methods=["POST"]),
        Route("/delegations", delegations_list_ep),
        Route("/sync", sync_ep, methods=["POST"]),
        Route("/stats", stats_ep),
    ]
    return Starlette(routes=routes)


def main(data_dir: str = None, host: str = None, port: int = None) -> None:
    """Startet den API-Server - ausschliesslich auf Loopback."""
    import uvicorn

    core = PersonalOS(data_dir)
    cfg_host = host or core.config.server.host
    if cfg_host not in LOOPBACK_HOSTS:
        raise RuntimeError(
            f"Verweigert: {cfg_host!r} ist kein Loopback-Host. "
            "Das Personal OS ist nur lokal erreichbar."
        )
    app = create_app(core)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(port or core.config.server.port),
        log_level="warning",
    )
