"""Shared lifecycle behavior for Service and Workspace resources."""

from types import SimpleNamespace

import pytest

from codespace.config import Config
from codespace.control import ControlPlane
from codespace.resources import Resource, ResourceConflict, ResourceNotFound
from codespace.runtime import container


@pytest.fixture
def manager(config: Config) -> ControlPlane:
    control = ControlPlane(config, transport=SimpleNamespace())  # type: ignore[arg-type]
    control.set_token("github", "token")
    return control


@pytest.mark.parametrize(
    "resource",
    [
        Resource("home", "support"),
        Resource("home", "debug", "scratch"),
        Resource("home", "debug", "codespace"),
    ],
)
def test_queue_and_dismiss_share_operation_rules(manager: ControlPlane, resource: Resource) -> None:
    operation = manager.queue(resource)
    assert operation.model_dump() == {
        "id": resource.id,
        "kind": resource.kind,
        "host": resource.host,
        "resource": resource.name,
        "project": resource.project,
        "status": "queued",
        "stage": "queued",
        "error": None,
    }
    with pytest.raises(ResourceConflict, match="already running"):
        manager.queue(resource)
    with pytest.raises(ResourceConflict, match="still queued"):
        manager.dismiss_failed(resource)
    manager.operations.update(resource.host, resource.id, status="failed", error="failed")
    assert manager.dismiss_failed(resource) is True
    assert manager.dismiss_failed(resource) is False


def test_operations_are_isolated_by_kind_and_host(manager: ControlPlane) -> None:
    data = manager.config.model_dump()
    data["services"]["support"]["hosts"].append("office")
    manager.config = Config.model_validate(data)
    resources = [
        Resource("home", "support"),
        Resource("office", "support"),
        Resource("home", "support", "scratch"),
    ]
    for resource in resources:
        manager.queue(resource)
    assert len(manager.operations.list()) == 3
    manager.operations.update("home", resources[0].id, status="failed")
    manager.dismiss_failed(resources[0])
    assert {(item.host, item.id) for item in manager.operations.list()} == {
        (item.host, item.id) for item in resources[1:]
    }


@pytest.mark.parametrize(
    "resource",
    [
        Resource("home", "missing"),
        Resource("office", "support"),
        Resource("home", "debug", "missing"),
        Resource("office", "debug", "scratch"),
    ],
)
def test_unknown_placement_fails_before_transport(
    manager: ControlPlane, resource: Resource
) -> None:
    for action in (manager.queue, manager.logs, manager.remove, manager.dismiss_failed):
        with pytest.raises(ResourceNotFound):
            action(resource)
    assert manager.operations.list() == []


def test_only_provider_workspace_requires_a_token(manager: ControlPlane) -> None:
    def missing(_provider: str) -> str:
        raise ResourceConflict("token is not set")

    manager._token = missing
    manager.queue(Resource("home", "support"))
    manager.queue(Resource("home", "debug", "scratch"))
    manager.queue(Resource("home", "debug", "personal"))
    with pytest.raises(ResourceConflict, match="token is not set"):
        manager.queue(Resource("home", "debug", "codespace"))
    assert len(manager.operations.list()) == 3


@pytest.mark.parametrize("project", [None, "scratch"])
def test_missing_container_removal_keeps_domain_semantics(
    manager: ControlPlane, monkeypatch: pytest.MonkeyPatch, project: str | None
) -> None:
    manager.transport = SimpleNamespace(client=lambda _host: object())  # type: ignore[assignment]
    monkeypatch.setattr(container, "find_container", lambda *_args, **_kwargs: None)
    resource = Resource("home", "support", project)
    if project is None:
        assert manager.remove(resource) is False
    else:
        with pytest.raises(ResourceNotFound, match="not found"):
            manager.remove(resource)
