"""Tests for in-memory deploy keypair generation."""

from cryptography.hazmat.primitives.serialization import load_ssh_private_key, load_ssh_public_key

from codespace.agent import keys


def test_generate_deploy_keypair_is_parsable_ed25519() -> None:
    kp = keys.generate_deploy_keypair()

    assert kp.private_openssh.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert kp.public_openssh.startswith("ssh-ed25519 ")

    # Both halves must be loadable by cryptography (valid OpenSSH encoding).
    load_ssh_private_key(kp.private_openssh.encode(), password=None)
    load_ssh_public_key(kp.public_openssh.encode())


def test_generate_deploy_keypair_is_unique() -> None:
    first = keys.generate_deploy_keypair()
    second = keys.generate_deploy_keypair()
    assert first.private_openssh != second.private_openssh
    assert first.public_openssh != second.public_openssh
