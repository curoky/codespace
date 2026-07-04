"""Linux agent for the codespace scheme (Podman-out-of-Podman).

The agent is stateless: all persistent metadata lives in podman container
labels and GitHub deploy keys. See DESIGN.md §6.
"""
