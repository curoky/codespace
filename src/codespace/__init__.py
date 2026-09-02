"""Codespace local control plane."""

import truststore

# Provider clients use the operating system trust store.
truststore.inject_into_ssl()
