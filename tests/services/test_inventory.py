"""Tests for Service inventory labels."""

from types import SimpleNamespace

from codespace.services import inventory


def test_service_inventory_uses_disjoint_kind_filter() -> None:
    running = SimpleNamespace(
        id="container-id",
        labels={
            "codespace.kind": "service",
            "codespace.service": "support",
            "codespace.image": "support:latest",
        },
        attrs={"State": {"Status": "running"}},
    )
    calls: list[dict[str, object]] = []
    client = SimpleNamespace(
        containers=SimpleNamespace(
            list=lambda **kwargs: (calls.append(kwargs), [running])[-1],
        )
    )

    services = inventory.list_services(client, "home")  # type: ignore[arg-type]

    assert calls == [{"all": True, "filters": {"label": "codespace.kind=service"}}]
    assert services[0].id == "codespace-service-support"
    assert services[0].status == "running"
