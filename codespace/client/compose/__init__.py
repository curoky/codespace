"""A strict, self-contained subset of the Docker Compose service schema.

This subpackage models only the container runtime fields the control plane
forwards to ``podman run`` (``cap_add``, ``security_opt``, ``pids_limit``,
``ulimits``, ``volumes``, ``environment``) using Compose's field names and both
its short and long syntaxes. Every field is optional, so one ``ServiceSpec``
serves as both the base block and an override layer, and ``merged_with`` owns
the shallow, key-level layering. It is deliberately isolated from the rest of
the client: it holds no control-plane knowledge, so reserved-key rejection stays
in the caller.
"""

from codespace.client.compose.models import (
    ServiceSpec,
    Ulimit,
    Volume,
)

__all__ = ["ServiceSpec", "Ulimit", "Volume"]
