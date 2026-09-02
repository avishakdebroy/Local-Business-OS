"""Application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from lbos import __version__
from lbos.api.routers import api, capture, pages, review
from lbos.api.templating import templates
from lbos.db.bootstrap import prepare
from lbos.ops.scheduler import Jobs
from lbos.settings import Settings, get_settings

log = logging.getLogger("lbos")


def _configure_logging(settings: Settings) -> None:
    settings.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(settings.logs_dir / "lbos.log", encoding="utf-8"),
        ],
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    _configure_logging(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        applied = prepare(resolved)
        if applied:
            log.info("applied migrations: %s", [m.version for m in applied])

        jobs = Jobs(resolved)
        jobs.start()
        app.state.jobs = jobs
        try:
            yield
        finally:
            jobs.stop()

    app = FastAPI(
        title="Local Business OS",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.settings = resolved

    app.include_router(pages.router)
    app.include_router(capture.router)
    app.include_router(review.router)
    app.include_router(api.router)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        """Show a page a shop owner can act on, not a JSON blob."""
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "request": request,
                "page": "",
                "pending_count": 0,
                "msg": None,
                "kind": "error",
                "detail": exc.detail,
            },
            status_code=exc.status_code,
        )

    return app


app = create_app()
