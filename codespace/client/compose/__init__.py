"""A strict, self-contained subset of the Docker Compose service schema.

This subpackage models only the container runtime fields the control plane
forwards to ``podman run`` (``cap_add``, ``security_opt``, ``pids_limit``,
``ulimits``, ``volumes``, ``environment``) using Compose's field names and both
its short and long syntaxes. It is deliberately isolated from the rest of the
client: it holds no control-plane knowledge, so reserved-key rejection and
override layering stay in the caller.
"""

from codespace.client.compose.models import (
    ServiceOverride,
    ServiceSpec,
    Ulimit,
    Volume,
)

__all__ = ["ServiceOverride", "ServiceSpec", "Ulimit", "Volume"]
