"""Run the local Codespace Web GUI.

The client no longer exposes create/list/delete commands; those flows live in
the Web GUI. This module remains only as a convenient ``python -m`` launcher.
"""

import os

import uvicorn

from codespace.client import web as web_module

DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8765


def main() -> None:
    """Start the local Web GUI using optional environment overrides."""
    host = os.environ.get("CODESPACE_WEB_HOST", DEFAULT_WEB_HOST)
    port = int(os.environ.get("CODESPACE_WEB_PORT", str(DEFAULT_WEB_PORT)))
    if host not in {"127.0.0.1", "localhost"}:
        print(
            "warning: Web GUI can access local git tokens, SSH keys and ~/.ssh/config; "
            "do not expose it to untrusted networks."
        )
    uvicorn.run(web_module.create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
