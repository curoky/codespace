# Codespace Sidecar Agent Guide

This directory owns host-scoped shared-service container assets for Codespace.

## Definition

A sidecar is one common container instance on each configured host. It serves
all development environments on that host and is not attached to a project or
instance. Atuin server is the first intended shared service.

The term sidecar describes its relationship to the host's Codespace
environments; it is not a per-environment companion container.

## Invariants

- Exactly one Codespace sidecar container may exist per configured host.
- The sidecar uses host networking so development containers can reach shared
  loopback services.
- Sidecar identity is derived only from the host. It must not include project
  or instance IDs.
- Sidecar inventory and labels are separate from `codespace.managed=true`
  environment inventory.
- Sidecars have no project workspace, environment SSH port, login alias,
  deploy key, repository, or generated SSH projection.
- Creating or deleting an environment must not create, replace, or remove the
  host sidecar.
- Sidecar failure may be reported with host state, but it must not corrupt
  environment inventory.
- Persistent service data must use host storage owned by the sidecar contract,
  never the environment workspace root `~/codespace2/<project>/<instance>`.

## Container Contract

The current image is `ghcr.io/curoky/devspace:codespace-sidecar`. Its host-local
container name is `codespace-sidecar`, which gives each host exactly one
instance without embedding project or instance identity.

The container runs s6 as PID 1 and starts Atuin server with:

- host `127.0.0.1`;
- port `8002`;
- open registration disabled;
- required `ATUIN_DB_URI` supplied at container creation.

The image contains no Python control plane, Podman socket, project workspace,
SSH service, provider token, or repository credential. Atuin's database is
external, so the container itself has no persistent service-data mount.

Build and run manually from the repository root:

```bash
codespace/images/sidecar/build.sh
ATUIN_DB_URI=postgres://... codespace/images/sidecar/run.sh
```

`run.sh` replaces the fixed-name container and configures the Podman restart
policy. The existing development image's Atuin client continues to use
`http://127.0.0.1:8002`.

## Layout

| Path | Responsibility |
| --- | --- |
| `Dockerfile` | Minimal Debian, standalone Atuin, s6, and rootfs assembly. |
| `sb-pkgs.yaml` | Standalone Atuin and s6 package set. |
| `rootfs/` | Sidecar-only s6 bundle and shared services. |
| `build.sh` | Local image build from the repository root. |
| `run.sh` | Manual host-local singleton replacement. |

Do not copy the deleted agent service, Python application, uv environment,
workspace mount, or Podman socket into this image.

## Control-Plane Boundary

The image and manual launcher exist, but the local Codespace control plane does
not yet reconcile sidecars. When adding that lifecycle:

1. Define sidecar-specific labels and strict inventory validation.
2. Reuse the existing host Podman transport; do not add another protocol.
3. Idempotently ensure the fixed sidecar on each online configured host.
4. Report missing, stopped, duplicate, or malformed sidecars explicitly.
5. Add lifecycle and mixed online/offline host tests.
6. Update this file and `codespace/CLAUDE.md` with the final labels and API.

Do not add migration or compatibility behavior unless explicitly requested.
