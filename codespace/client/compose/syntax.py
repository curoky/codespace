"""Normalize supported Compose short syntaxes before Pydantic validation."""

from __future__ import annotations


def normalize_volumes(value: object) -> object:
    """Expand ``source:target[:ro|rw]`` bind mounts."""
    if not isinstance(value, list):
        return value
    return [_normalize_volume(item) for item in value]


def _normalize_volume(item: object) -> object:
    if not isinstance(item, str):
        return item
    parts = item.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"volume {item!r} must be 'source:target' or 'source:target:ro|rw'")
    source, target = parts[0], parts[1]
    read_only = False
    if len(parts) == 3:
        mode = parts[2]
        if mode not in ("ro", "rw"):
            raise ValueError(f"volume {item!r} mode must be 'ro' or 'rw', got {mode!r}")
        read_only = mode == "ro"
    return {"type": "bind", "source": source, "target": target, "read_only": read_only}


def normalize_environment(value: object) -> object:
    """Convert ``KEY=value`` list entries to a mapping."""
    if not isinstance(value, list):
        return value
    result: dict[str, str] = {}
    for entry in value:
        if not isinstance(entry, str) or "=" not in entry:
            raise ValueError(f"environment entry {entry!r} must be 'KEY=value'")
        key, _, val = entry.partition("=")
        if not key:
            raise ValueError(f"environment entry {entry!r} has an empty key")
        result[key] = val
    return result


def normalize_ulimits(value: object) -> object:
    """Expand scalar ulimits to equal soft and hard values."""
    if not isinstance(value, dict):
        return value
    return {name: _normalize_ulimit(limit) for name, limit in value.items()}


def _normalize_ulimit(limit: object) -> object:
    if isinstance(limit, bool):
        raise ValueError("ulimit value must be an integer or a {soft, hard} mapping")
    if isinstance(limit, int):
        return {"soft": limit, "hard": limit}
    return limit
