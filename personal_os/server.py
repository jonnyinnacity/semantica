"""Lokaler REST-API-Server fuer das Personal OS (immer Loopback-only).

Bindet standardmaessig nur an 127.0.0.1. Wenn ``POS_TOKEN`` gesetzt ist,
braucht jeder Request einen ``Authorization: Bearer <token>``-Header.
"""

from __future__ import annotations

import os

from .core import PersonalOS

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def create_app(core: PersonalOS):
    """Starlette-App mit JSON-Endpunkten (Import von starlette erst hier)."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    token = os.environ.get(core.config.server.token_env, "")

    def unauthorized() -> JSONResponse:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    async def check_auth(request: Request):
        if token and request.headers.get("authorization") != f"Bearer {token}":
            return unauthorized()
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
        try:
            item = core.capture(
                body.get("content", ""),
                kind=body.get("kind", "note"),
                source=body.get("source", "api"),
                tags=body.get("tags", []),
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
        else:
            query = request.query_params.get("query", "")
            limit = int(request.query_params.get("limit", 5))
        if not query:
            return JSONResponse({"error": "query fehlt"}, status_code=400)
        return JSONResponse(core.ask(query, limit=limit))

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
        return JSONResponse(core.list_loops(status=status))

    async def loop_add_ep(request: Request):
        denied = await check_auth(request)
        if denied:
            return denied
        body = await request.json()
        text = body.get("text", "")
        if not text:
            return JSONResponse({"error": "text fehlt"}, status_code=400)
        return JSONResponse(core.add_loop_from_text(text))

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
        d = core.delegate(
            body.get("instruction", ""), agent=body.get("agent", "default")
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
