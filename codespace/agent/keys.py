"""In-memory deploy keypair generation for the agent.

The agent generates the deploy keypair, injects the private half into the dev
container and returns the public half to the client (which registers it as a
GitHub deploy key). The agent never talks to GitHub and holds no token; nothing
is written to the agent's disk. See DESIGN.md §6.
"""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, ConfigDict


class DeployKeypair(BaseModel):
    """An in-memory ed25519 deploy keypair in OpenSSH text form."""

    model_config = ConfigDict(frozen=True)

    private_openssh: str
    public_openssh: str


def generate_deploy_keypair() -> DeployKeypair:
    """Generate an ed25519 keypair as OpenSSH text; nothing touches disk."""
    key = Ed25519PrivateKey.generate()
    private_openssh = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_openssh = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode("utf-8")
    )
    return DeployKeypair(private_openssh=private_openssh, public_openssh=public_openssh)
