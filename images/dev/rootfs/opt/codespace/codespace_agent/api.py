"""FastAPI routes and Uvicorn UDS server for the workspace agent."""

from __future__ import annotations

import socket
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .models import AgentStatus, GitState, ProviderReadyRequest
from .service import SOCKET_PATH, APIError, WorkspaceAgent


def create_app(agent: WorkspaceAgent) -> FastAPI:
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.router.redirect_slashes = False

    @app.exception_handler(APIError)
    async def handle_api_error(
        request: Request,
        exc: APIError,
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc)})

    @app.get("/status")
    def status() -> AgentStatus:
        return agent.status()

    @app.post("/provider-ready")
    def provider_ready(request: ProviderReadyRequest) -> AgentStatus:
        return agent.provider_ready(request.generation)

    @app.get("/git-state")
    def git_state() -> GitState:
        return agent.git_state()

    return app


def build_server(
    agent: WorkspaceAgent,
    socket_path: Path = SOCKET_PATH,
) -> tuple[uvicorn.Server, socket.socket]:
    socket_path.unlink(missing_ok=True)
    config = uvicorn.Config(
        create_app(agent),
        uds=str(socket_path),
        access_log=False,
        log_config=None,
        server_header=False,
        date_header=False,
    )
    return uvicorn.Server(config), config.bind_socket()
