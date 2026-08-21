"""Codespace-agnostic runtime infrastructure.

Groups the reusable lower layers the control plane builds on: the Podman
container engine (:mod:`.engine`) and its connection transport
(:mod:`.transport`), generic remote-command and atomic file primitives
(:mod:`.remote`), and the Compose syntax subset parser (:mod:`.compose`). None
of these modules import Codespace business modules.
"""
