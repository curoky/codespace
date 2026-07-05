# Agent image for the codespace scheme. Runs the FastAPI service that talks to
# the host podman service over the mounted /run/podman/podman.sock (PoP). The
# image needs NO podman CLI -- podman-py speaks the socket directly.
#
# Build from the repo root so pyproject.toml/uv.lock are in the context:
#   podman build -t codespace/agent:latest -f codespace/images/agent/Dockerfile .

FROM docker.io/python:3.13-slim

# Pull in the uv binary for reproducible, lockfile-driven installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
  UV_LINK_MODE=copy \
  UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install exactly the locked runtime dependencies (no dev group, and without
# building this project itself -- it has no build backend, so we run it from
# source on PYTHONPATH below). uv.lock keeps the image reproducible and in sync
# with the rest of the toolchain.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy the codespace package and run it from the synced virtualenv.
COPY codespace /app/codespace
ENV PATH="/app/.venv/bin:$PATH"

# The agent is stateless; all flags are provided at runtime (see run.sh).
ENTRYPOINT ["python", "-m", "codespace.agent"]
