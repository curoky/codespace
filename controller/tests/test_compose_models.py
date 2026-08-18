"""Tests for the Compose service subset schema and short-syntax parsing."""

import pytest
from pydantic import ValidationError

from controller.compose import ServiceSpec


def test_service_spec_all_fields_default_to_none() -> None:
    spec = ServiceSpec()

    assert spec.cap_add is None
    assert spec.security_opt is None
    assert spec.pids_limit is None
    assert spec.ulimits is None
    assert spec.volumes is None
    assert spec.environment is None
    assert spec.devices is None
    assert spec.shm_size is None


def test_shm_size_passes_through_as_string() -> None:
    spec = ServiceSpec.model_validate({"shm_size": "100g"})

    assert spec.shm_size == "100g"


def test_shm_size_rejects_blank_string() -> None:
    with pytest.raises(ValidationError):
        ServiceSpec.model_validate({"shm_size": "  "})


def test_volumes_short_syntax_expands_to_bind_mount() -> None:
    spec = ServiceSpec.model_validate(
        {"volumes": ["/etc/krb5.conf:/etc/krb5.conf:ro", "/data:/data"]}
    )

    assert spec.volumes is not None
    assert [(v.source, v.target, v.read_only) for v in spec.volumes] == [
        ("/etc/krb5.conf", "/etc/krb5.conf", True),
        ("/data", "/data", False),
    ]


def test_volumes_long_syntax_passes_through() -> None:
    spec = ServiceSpec.model_validate(
        {"volumes": [{"source": "/a", "target": "/b", "read_only": True}]}
    )

    assert spec.volumes is not None
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
        ServiceSpec.model_validate({"volumes": [entry]})


def test_environment_list_short_syntax_becomes_mapping() -> None:
    spec = ServiceSpec.model_validate({"environment": ["HTTP_PROXY=http://proxy:3128", "EMPTY="]})

    assert spec.environment == {"HTTP_PROXY": "http://proxy:3128", "EMPTY": ""}


@pytest.mark.parametrize("entry", ["NO_EQUALS", "=novalue"])
def test_environment_reject_malformed_list_entry(entry: str) -> None:
    with pytest.raises(ValidationError, match="environment entry"):
        ServiceSpec.model_validate({"environment": [entry]})


def test_ulimits_scalar_short_syntax_sets_equal_soft_hard() -> None:
    spec = ServiceSpec.model_validate({"ulimits": {"nofile": 65535}})

    assert spec.ulimits is not None
    assert (spec.ulimits["nofile"].soft, spec.ulimits["nofile"].hard) == (65535, 65535)


def test_ulimits_mapping_long_syntax_passes_through() -> None:
    spec = ServiceSpec.model_validate({"ulimits": {"memlock": {"soft": -1, "hard": -1}}})

    assert spec.ulimits is not None
    assert (spec.ulimits["memlock"].soft, spec.ulimits["memlock"].hard) == (-1, -1)


def test_ulimits_reject_boolean_scalar() -> None:
    with pytest.raises(ValidationError, match="ulimit value must be an integer"):
        ServiceSpec.model_validate({"ulimits": {"nofile": True}})


def test_service_spec_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        ServiceSpec.model_validate({"image": "img:latest"})


def test_merged_with_no_overrides_returns_equal_copy() -> None:
    spec = ServiceSpec.model_validate({"pids_limit": 100})

    assert spec.merged_with() == spec
    assert spec.merged_with(None, None) == spec


def test_merged_with_applies_layers_left_to_right() -> None:
    spec = ServiceSpec.model_validate({"pids_limit": 1, "security_opt": ["seccomp=unconfined"]})
    host = ServiceSpec.model_validate({"pids_limit": 2, "cap_add": ["SYS_ADMIN"]})
    project = ServiceSpec.model_validate({"pids_limit": 3})

    merged = spec.merged_with(host, project)

    # later layer wins on pids_limit; host-only key still applied
    assert merged.pids_limit == 3
    assert merged.cap_add == ["SYS_ADMIN"]
    # untouched keys inherit the base
    assert merged.security_opt == ["seccomp=unconfined"]


def test_merged_with_unset_key_does_not_clear_base() -> None:
    spec = ServiceSpec.model_validate({"pids_limit": 5, "cap_add": ["NET_RAW"]})
    override = ServiceSpec.model_validate({"pids_limit": 6})

    merged = spec.merged_with(override)

    # override leaves cap_add unset (None), so the base value survives
    assert merged.pids_limit == 6
    assert merged.cap_add == ["NET_RAW"]


def test_merged_with_replaces_environment_wholesale_no_deep_merge() -> None:
    spec = ServiceSpec.model_validate({"environment": {"BASE": "1"}})
    override = ServiceSpec.model_validate({"environment": {"PROJECT": "1"}})

    merged = spec.merged_with(override)

    assert merged.environment == {"PROJECT": "1"}


def test_merged_with_result_is_revalidated() -> None:
    spec = ServiceSpec()
    override = ServiceSpec.model_validate({"volumes": ["/a:/b:ro"]})

    merged = spec.merged_with(override)

    assert merged.volumes is not None
    assert [(v.source, v.target, v.read_only) for v in merged.volumes] == [("/a", "/b", True)]


def test_secrets_bare_name_short_syntax_becomes_mount() -> None:
    spec = ServiceSpec.model_validate({"secrets": ["supabase_service_key"]})

    assert spec.secrets is not None
    secret = spec.secrets[0]
    assert (secret.source, secret.mode, secret.target) == ("supabase_service_key", "mount", None)


def test_secrets_long_syntax_env_mode_passes_through() -> None:
    spec = ServiceSpec.model_validate(
        {
            "secrets": [
                {"source": "supabase_anon", "mode": "env", "target": "SUPABASE_ANON_KEY"},
            ]
        }
    )

    assert spec.secrets is not None
    secret = spec.secrets[0]
    assert (secret.source, secret.mode, secret.target) == (
        "supabase_anon",
        "env",
        "SUPABASE_ANON_KEY",
    )


def test_secrets_mount_accepts_ownership_and_mode() -> None:
    spec = ServiceSpec.model_validate(
        {
            "secrets": [
                {
                    "source": "db_password",
                    "target": "/run/secrets/db",
                    "uid": 1000,
                    "gid": 1000,
                    "file_mode": 0o440,
                }
            ]
        }
    )

    assert spec.secrets is not None
    secret = spec.secrets[0]
    assert (secret.target, secret.uid, secret.gid, secret.file_mode) == (
        "/run/secrets/db",
        1000,
        1000,
        0o440,
    )


def test_secrets_env_mode_requires_target() -> None:
    with pytest.raises(ValidationError, match="mode 'env' requires 'target'"):
        ServiceSpec.model_validate({"secrets": [{"source": "x", "mode": "env"}]})


@pytest.mark.parametrize("name", ["BAD-NAME", "1BAD", "bad.name"])
def test_secrets_env_target_must_be_valid_env_name(name: str) -> None:
    with pytest.raises(ValidationError, match=r"\^\[A-Za-z_\]"):
        ServiceSpec.model_validate({"secrets": [{"source": "x", "mode": "env", "target": name}]})


def test_secrets_env_mode_rejects_ownership_fields() -> None:
    with pytest.raises(ValidationError, match="must not set uid/gid/file_mode"):
        ServiceSpec.model_validate(
            {"secrets": [{"source": "x", "mode": "env", "target": "TOKEN", "uid": 1000}]}
        )


def test_secrets_mount_target_must_be_absolute() -> None:
    with pytest.raises(ValidationError, match="must be an absolute path"):
        ServiceSpec.model_validate({"secrets": [{"source": "x", "target": "relative/path"}]})


def test_secrets_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        ServiceSpec.model_validate({"secrets": [{"source": "x", "driver": "file"}]})


def test_merged_with_replaces_secrets_wholesale() -> None:
    spec = ServiceSpec.model_validate({"secrets": ["base"]})
    override = ServiceSpec.model_validate({"secrets": ["project"]})

    merged = spec.merged_with(override)

    assert merged.secrets is not None
    assert [secret.source for secret in merged.secrets] == ["project"]
