"""LobeHub packages its application and database as one persistent Service."""

import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yaml

from codespace.config import Config

_ROOT = Path(__file__).resolve().parents[1]
_SERVICE = _ROOT / "platform/container/services/lobehub"
_S6 = _SERVICE / "rootfs/etc/s6/s6-rc.d"


def test_lobehub_image_pins_upstream_and_initializes_database_at_runtime() -> None:
    dockerfile = (_SERVICE / "Dockerfile").read_text()
    database = (_SERVICE / "rootfs/opt/lobehub/database.sh").read_text()

    assert "lobehub/lobehub:2.2.17" in dockerfile
    assert "paradedb/paradedb:0.25.9-pg17" in dockerfile
    assert "node:24.21.0-bookworm-slim" in dockerfile
    assert "initdb" in database
    assert "shared_preload_libraries=pg_search" in database
    assert not (_SERVICE / "rootfs/var/lib/postgresql").exists()


def test_lobehub_waits_for_local_postgres_and_persists_runtime_identity() -> None:
    assert (_S6 / "postgres/type").read_text().strip() == "longrun"
    assert (_S6 / "postgres/notification-fd").read_text().strip() == "3"
    assert (_S6 / "lobehub/type").read_text().strip() == "longrun"
    assert (_S6 / "lobehub/dependencies.d/postgres").is_file()
    assert (_S6 / "auth-proxy/type").read_text().strip() == "longrun"
    assert (_S6 / "auth-proxy/dependencies.d/lobehub").is_file()
    assert (_S6 / "default/contents.d/auth-proxy").is_file()

    serve = (_SERVICE / "rootfs/opt/lobehub/serve.sh").read_text()
    database = (_SERVICE / "rootfs/opt/lobehub/database.sh").read_text()
    proxy = (_SERVICE / "rootfs/opt/lobehub/auth-proxy.js").read_text()
    assert "LOBEHUB_DATA_DIR" not in serve
    assert "LOBEHUB_DATA_DIR" not in database
    assert "PGDATA" not in database
    assert "readonly config_dir=/var/lib/codespace/lobehub/config" in serve
    assert "LOBEHUB_INTERNAL_PORT" not in serve
    assert "LOBEHUB_PROXY_PORT" not in proxy
    assert "LOBEHUB_HOST" not in proxy
    assert "const backendPort = 8081;" in proxy
    assert "const listenHost = '0.0.0.0';" in proxy
    assert "const listenPort = 8080;" in proxy
    assert "const externalUrl = process.env.APP_URL;" in proxy
    assert "http://localhost:3210" not in proxy
    assert 'export APP_URL="http://localhost:3210"' not in serve
    assert "APP_URL is required" in serve
    assert "openssl rand -base64 36" in serve
    assert 'export AUTH_ALLOWED_EMAILS="${auto_auth_email}"' in serve
    assert "postgresql://postgres@127.0.0.1:5432/lobehub" in serve
    assert "export HOSTNAME=127.0.0.1" in serve
    assert "s6-setuidgid nextjs" in serve


def test_lobehub_auth_proxy_bootstraps_and_injects_one_session() -> None:
    events: list[tuple[str, str | None, bytes]] = []
    request_hosts: list[str | None] = []

    class BackendHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            size = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(size)
            events.append((self.path, self.headers.get("cookie"), body))
            request_hosts.append(self.headers.get("host"))
            if self.path == "/api/auth/sign-in/email" and len(events) == 1:
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"message":"user not found"}')
                return

            self.send_response(200)
            self.send_header(
                "set-cookie",
                "codespace-lobehub.session_token=shared-session; Path=/; HttpOnly; SameSite=Lax",
            )
            self.send_header(
                "set-cookie",
                "codespace-lobehub.session_data=shared-data; Path=/; HttpOnly; SameSite=Lax",
            )
            self.end_headers()
            self.wfile.write(b"{}")

        def do_GET(self) -> None:
            events.append((self.path, self.headers.get("cookie"), b""))
            request_hosts.append(self.headers.get("host"))
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"proxied")

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 8081), BackendHandler)
    backend_thread = threading.Thread(target=backend.serve_forever)
    backend_thread.start()

    proxy = subprocess.Popen(  # noqa: S603
        ["/usr/bin/env", "node", str(_SERVICE / "rootfs/opt/lobehub/auth-proxy.js")],
        env={
            **os.environ,
            "AUTH_COOKIE_PREFIX": "codespace-lobehub",
            "APP_URL": "http://localhost:4321",
            "LOBEHUB_AUTO_AUTH_EMAIL": "codespace@codespace.invalid",
            "LOBEHUB_AUTO_AUTH_PASSWORD": "test-password",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                request = Request(
                    "http://127.0.0.1:8080/chat",
                    headers={
                        "Cookie": ("theme=dark; codespace-lobehub.session_token=untrusted-session")
                    },
                )
                with urlopen(request, timeout=1) as response:  # noqa: S310
                    assert response.read() == b"proxied"
                    set_cookies = response.headers.get_all("set-cookie")
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

        assert [event[0] for event in events] == [
            "/api/auth/sign-in/email",
            "/api/auth/sign-up/email",
            "/trpc/lambda/user.updateOnboarding?batch=1",
            "/chat",
        ]
        assert events[-2][1] == (
            "codespace-lobehub.session_token=shared-session; "
            "codespace-lobehub.session_data=shared-data"
        )
        onboarding = json.loads(events[-2][2])
        assert onboarding["0"]["json"]["currentStep"] == 4
        assert onboarding["0"]["json"]["version"] == 2
        assert onboarding["0"]["json"]["finishedAt"]
        assert events[-1][1] == (
            "theme=dark; codespace-lobehub.session_token=shared-session; "
            "codespace-lobehub.session_data=shared-data"
        )
        assert set(request_hosts) == {"localhost:4321"}
        assert set_cookies == [
            "codespace-lobehub.session_token=shared-session; Path=/; HttpOnly; SameSite=Lax",
            "codespace-lobehub.session_data=shared-data; Path=/; HttpOnly; SameSite=Lax",
        ]

        try:
            urlopen(
                Request(
                    "http://127.0.0.1:8080/api/auth/sign-out",
                    data=b"{}",
                    method="POST",
                ),
                timeout=1,
            )
        except HTTPError as error:
            assert error.code == 403
        else:
            raise AssertionError("authentication mutation unexpectedly reached the backend")

        assert len(events) == 4
    finally:
        proxy.terminate()
        proxy.wait(timeout=5)
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=5)


def test_lobehub_example_uses_gateway_and_targets_sglang() -> None:
    config = Config.model_validate(yaml.safe_load((_ROOT / "config.example.yaml").read_text()))
    container = config.resolved_service_container("lobehub", "gpu-host")

    assert [port.model_dump() for port in container.ports] == [
        {
            "target": 8080,
            "published": 3210,
            "host_ip": "10.88.0.1",
            "protocol": "tcp",
        }
    ]
    assert container.environment["OPENAI_PROXY_URL"] == "http://10.88.0.1:8003/v1"
    assert "LOBEHUB_HOST" not in container.environment
    assert container.environment["APP_URL"] == "http://localhost:3210"
    assert "/var/lib/codespace/lobehub" in [volume.target for volume in container.volumes]
    assert config.service_tunnel_ports("lobehub", "gpu-host") == [3210]
