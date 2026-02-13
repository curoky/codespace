"""Codespace: a self-contained lightweight remote development environment."""

import truststore

# Reuse the OS trust store (macOS Keychain / Linux system CA bundle) so that
# certificates re-signed by a corporate TLS inspection gateway (such as
# SealSuite SWG) for hosts like gitlab.com are trusted. Otherwise requests and
# urllib3 only trust the bundled certifi CAs and provider access fails SSL
# verification.
truststore.inject_into_ssl()
