from codespace.client.service import _agent_target_host, _ssh_forward_target_host


def test_ssh_forward_target_host_wraps_ipv6_addresses() -> None:
    assert (
        _ssh_forward_target_host("2605:340:cd52:105:3634:f427:f62d:4143")
        == "[2605:340:cd52:105:3634:f427:f62d:4143]"
    )


def test_ssh_forward_target_host_leaves_non_ipv6_hosts_unchanged() -> None:
    assert _ssh_forward_target_host("127.0.0.1") == "127.0.0.1"
    assert _ssh_forward_target_host("agent.internal") == "agent.internal"


def test_agent_target_host_maps_ipv6_wildcard_to_loopback() -> None:
    assert _agent_target_host("::") == "127.0.0.1"
