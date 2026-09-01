"""s6 entrypoint for the container-side workspace agent."""

from codespace_agent import (
    CONTROL_DIR,
    REQUEST_PATH,
    SOCKET_PATH,
    AgentRequest,
    WorkspaceAgent,
    build_server,
)


def main() -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    agent = WorkspaceAgent(AgentRequest.load(REQUEST_PATH))
    server, server_socket = build_server(agent)
    agent.start()
    try:
        server.run(sockets=[server_socket])
    finally:
        server_socket.close()
        SOCKET_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
