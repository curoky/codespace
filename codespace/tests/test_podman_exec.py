"""Tests for the podman exec framing helpers."""

from codespace.agent.podman_exec import exec_output_text


def _exec_frame(stream: int, payload: bytes) -> bytes:
    return bytes([stream, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


def test_exec_output_text_returns_str_for_non_bytes() -> None:
    assert exec_output_text("plain") == "plain"


def test_exec_output_text_decodes_unframed_bytes() -> None:
    assert exec_output_text(b"hello") == "hello"


def test_exec_output_text_stdout_only_drops_stderr_frames() -> None:
    output = _exec_frame(1, b"/home/x") + _exec_frame(2, b"conmon debug noise")
    assert exec_output_text(output, stdout_only=True) == "/home/x"


def test_exec_output_text_merges_streams_when_not_stdout_only() -> None:
    output = _exec_frame(1, b"out") + _exec_frame(2, b"err")
    assert exec_output_text(output) == "outerr"


def test_exec_output_text_treats_unframed_multiplex_lookalike_as_plain() -> None:
    # Not a valid frame header -> fall back to decoding the raw bytes.
    assert exec_output_text(b"\x09\x00\x00\x00short") == "\x09\x00\x00\x00short"
