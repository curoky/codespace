"""Local-only FastAPI application for Codespace."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from controller.api import router
from controller.config import CONFIG_PATH, Config, load_config
from controller.service import CodespaceService, describe_error

STATIC_DIR = Path(__file__).parent / "static"


def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    error = cast("StarletteHTTPException", exc)
    return JSONResponse(status_code=error.status_code, content={"error": str(error.detail)})


def _not_found(_request: Request, exc: Exception) -> JSONResponse:
    """A service ``KeyError`` names an unknown workspace, host or deployment."""
    return JSONResponse(status_code=404, content={"error": str(exc.args[0]) if exc.args else ""})


def _conflict(_request: Request, exc: Exception) -> JSONResponse:
    """A service ``RuntimeError`` reports a state conflict the caller can resolve."""
    return JSONResponse(status_code=409, content={"error": str(exc)})


def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    error = cast("RequestValidationError", exc)
    errors = [
        f"{'.'.join(str(item) for item in item['loc'])}: {item['msg']}" for item in error.errors()
    ]
    return JSONResponse(status_code=422, content={"error": "; ".join(errors)})


def _unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": describe_error(exc)})


def _index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def create_app(
    config: Config | None = None,
    *,
    service: CodespaceService | None = None,
) -> FastAPI:
    """Build the single-process local application."""
    resolved_config = config or load_config(CONFIG_PATH)
    resolved_service = service or CodespaceService(resolved_config)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            resolved_service.close()

    app = FastAPI(
        title="codespace",
        lifespan=_lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.service = resolved_service
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(KeyError, _not_found)
    app.add_exception_handler(RuntimeError, _conflict)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected_error)
    app.add_api_route("/", _index, methods=["GET"])
    app.include_router(router)
    return app
