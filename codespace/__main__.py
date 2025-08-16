"""Run the local Codespace control plane."""

import uvicorn

from codespace.app import create_app


def main() -> None:
    """Start the fixed localhost-only single-worker Web application."""
    uvicorn.run(create_app(), host="127.0.0.1", port=8765, workers=1)


if __name__ == "__main__":
    main()
