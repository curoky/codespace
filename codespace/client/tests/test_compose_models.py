"""Tests for the Compose service subset schema and short-syntax parsing."""

import pytest
from pydantic import ValidationError

from codespace.client.compose import ServiceOverride, ServiceSpec

_BASE: dict[str, object] = {
    "cap_add": ["NET_RAW"],
    "security_opt": ["seccomp=unconfined"],
    "pids_limit": -1,
    "ulimits": {},
}


def test_service_spec_defaults_volumes_and_environment_empty() -> None:
    spec = ServiceSpec.model_validate(_BASE)

    assert spec.volumes == []
    assert spec.environment == {}


def test_volumes_short_syntax_expands_to_bind_mount() -> None:
    spec = ServiceSpec.model_validate(
        {**_BASE, "volumes": ["/etc/krb5.conf:/etc/krb5.conf:ro", "/data:/data"]}
    )

    assert [(v.source, v.target, v.read_only) for v in spec.volumes] == [
        ("/etc/krb5.conf", "/etc/krb5.conf", True),
        ("/data", "/data", False),
    ]


def test_volumes_long_syntax_passes_through() -> None:
    spec = ServiceSpec.model_validate(
        {**_BASE, "volumes": [{"source": "/a", "target": "/b", "read_only": True}]}
    )

    assert (spec.volumes[0].source, spec.volumes[0].read_only) == ("/a", True)


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ("/only-one", "source:target"),
        ("/a:/b:rx", "must be 'ro' or 'rw'"),
        ("relative:/b", "must be an absolute path"),
    ],
)
def test_volumes_reject_malformed_short_syntax(entry: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ServiceSpec.model_validate({**_BASE, "volumes": [entry]})


def test_environment_list_short_syntax_becomes_mapping() -> None:
    spec = ServiceSpec.model_validate(
        {**_BASE, "environment": ["HTTP_PROXY=http://proxy:3128", "EMPTY="]}
    )

    assert spec.environment == {"HTTP_PROXY": "http://proxy:3128", "EMPTY": ""}


@pytest.mark.parametrize("entry", ["NO_EQUALS", "=novalue"])
def test_environment_reject_malformed_list_entry(entry: str) -> None:
    with pytest.raises(ValidationError, match="environment entry"):
        ServiceSpec.model_validate({**_BASE, "environment": [entry]})


def test_ulimits_scalar_short_syntax_sets_equal_soft_hard() -> None:
    spec = ServiceSpec.model_validate({**_BASE, "ulimits": {"nofile": 65535}})

    assert (spec.ulimits["nofile"].soft, spec.ulimits["nofile"].hard) == (65535, 65535)


def test_ulimits_mapping_long_syntax_passes_through() -> None:
    spec = ServiceSpec.model_validate({**_BASE, "ulimits": {"memlock": {"soft": -1, "hard": -1}}})

    assert (spec.ulimits["memlock"].soft, spec.ulimits["memlock"].hard) == (-1, -1)


def test_ulimits_reject_boolean_scalar() -> None:
    with pytest.raises(ValidationError, match="ulimit value must be an integer"):
        ServiceSpec.model_validate({**_BASE, "ulimits": {"nofile": True}})


def test_service_spec_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        ServiceSpec.model_validate({**_BASE, "image": "img:latest"})


def test_merged_with_no_overrides_returns_equal_copy() -> None:
    spec = ServiceSpec.model_validate({**_BASE, "pids_limit": 100})

    assert spec.merged_with() == spec
    assert spec.merged_with(None, None) == spec


def test_merged_with_applies_layers_left_to_right() -> None:
    spec = ServiceSpec.model_validate({**_BASE, "pids_limit": 1})
    host = ServiceOverride.model_validate({"pids_limit": 2, "cap_add": ["SYS_ADMIN"]})
    project = ServiceOverride.model_validate({"pids_limit": 3})

    merged = spec.merged_with(host, project)

    # later layer wins on pids_limit; host-only key still applied
    assert merged.pids_limit == 3
    assert merged.cap_add == ["SYS_ADMIN"]
    # untouched keys inherit the base
    assert merged.security_opt == ["seccomp=unconfined"]


def test_merged_with_replaces_environment_wholesale_no_deep_merge() -> None:
    spec = ServiceSpec.model_validate({**_BASE, "environment": {"BASE": "1"}})
    override = ServiceOverride.model_validate({"environment": {"PROJECT": "1"}})

    merged = spec.merged_with(override)

    assert merged.environment == {"PROJECT": "1"}


def test_merged_with_result_is_revalidated() -> None:
    spec = ServiceSpec.model_validate(_BASE)
    override = ServiceOverride.model_validate({"volumes": ["/a:/b:ro"]})

    merged = spec.merged_with(override)

    assert [(v.source, v.target, v.read_only) for v in merged.volumes] == [("/a", "/b", True)]
