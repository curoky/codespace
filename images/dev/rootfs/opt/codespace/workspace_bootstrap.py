"""s6 entrypoint for automatic workspace bootstrap."""

import signal

from codespace_agent import CONTROL_DIR, REQUEST_PATH, AgentRequest, WorkspaceBootstrap


def main() -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    WorkspaceBootstrap(AgentRequest.load(REQUEST_PATH)).run()
    signal.pause()


if __name__ == "__main__":
    main()
