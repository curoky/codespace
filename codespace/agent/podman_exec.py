"""Low-level podman exec helpers for the codespace agent.

Podman may return Docker-compatible multiplexed attach frames instead of plain
command output. Each frame has an 8-byte header: stream id, three NUL bytes,
then a big-endian payload length. Decoding stdout separately lets the caller
resolve values such as ``$HOME`` without conmon debug logs on stderr corrupting
the result.
"""

from podman.domain.containers import Container


def exec_checked(container: Container, cmd: list[str], *, user: str | None = None) -> None:
    """Run a command in the container and raise on non-zero exit."""
    exit_code, output = container.exec_run(cmd, user=user)
    if exit_code not in (0, None):
        detail = exec_output_text(output)
        raise RuntimeError(f"exec {cmd!r} failed ({exit_code}): {detail}")


def exec_output_text(output: object, *, stdout_only: bool = False) -> str:
    """Decode podman exec output, handling multiplexed stdout/stderr frames.

    Decode only stdout when resolving values such as ``$HOME`` so conmon debug
    logs on stderr cannot corrupt the result.
    """
    if not isinstance(output, bytes):
        return str(output)
    stdout, stderr, framed = _split_exec_streams(output)
    raw = (stdout if framed else output) if stdout_only else stdout + stderr if framed else output
    return raw.decode("utf-8", "replace")


def _split_exec_streams(output: bytes) -> tuple[bytes, bytes, bool]:
    """Split Docker/Podman multiplexed exec output into stdout and stderr."""
    pos = 0
    stdout = bytearray()
    stderr = bytearray()
    while pos + 8 <= len(output):
        stream = output[pos]
        if stream not in (0, 1, 2) or output[pos + 1 : pos + 4] != b"\x00\x00\x00":
            return output, b"", False
        size = int.from_bytes(output[pos + 4 : pos + 8], "big")
        start = pos + 8
        end = start + size
        if end > len(output):
            return output, b"", False
        payload = output[start:end]
        if stream in (0, 1):
            stdout.extend(payload)
        else:
            stderr.extend(payload)
        pos = end
    if pos != len(output):
        return output, b"", False
    return bytes(stdout), bytes(stderr), True
