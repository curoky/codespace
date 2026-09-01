"""s6 entrypoint for the container-side workspace agent."""

import os

from codespace_agent import (
    CONTROL_DIR,
    SOCKET_PATH,
    AgentConfig,
    WorkspaceAgent,
    build_server,
)


def main() -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    agent = WorkspaceAgent(AgentConfig.load(os.environ))
    server, server_socket = build_server(agent)
    try:
        server.run(sockets=[server_socket])
    finally:
        server_socket.close()
        SOCKET_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
