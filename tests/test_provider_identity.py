import hashlib
from types import SimpleNamespace

import pytest

from fleet import collector, demand, remote


def test_identity_join_selects_only_this_mac_and_ignores_missing_ids(monkeypatch):
    replies = iter([
        {"providers": [{"provider_id": "m1", "se_public_key": "key1", "status": "serving"},
                       {"provider_id": "m3", "se_public_key": "key3"}]},
        {"earnings": [{"provider_id": "m1", "provider_key": "session1"},
                      {"provider_id": "m3", "provider_key": "session3"},
                      {"provider_id": "", "provider_key": "session3"},
                      {"provider_id": "m1"}, {"provider_id": "m1", "provider_key": "session1"}]},
    ])
    monkeypatch.setattr(demand, "_get_json", lambda *args: next(replies))
    hashes = demand.fetch_provider_hashes("https://example.test", "test-key", "key1")
    # Filtered to key1: session1 + sha256(provider_id m1) from the no-payouts seed.
    assert hashes == {hashlib.sha256(k.encode()).hexdigest() for k in ("session1", "m1")}
    monkeypatch.setattr(remote, "_run_ssh", lambda *args, **kw:
                        '{"written_at": 100, "attestation_public_key": "key1"}')
    cfg = SimpleNamespace(host_id="mac1", api_key="test-key",
                          base_url="https://example.test", daemon_freshness_seconds=90)
    daemon = remote.fetch_daemon_state(cfg, now=100)
    assert daemon.attestation_public_key == "key1"


def test_malformed_identity_response_fails(monkeypatch):
    monkeypatch.setattr(demand, "_get_json", lambda *args: {})
    with pytest.raises(ValueError):
        demand.fetch_provider_hashes("https://example.test", "test-key", "key1")


def test_account_provider_hosts_map_every_provider_id(monkeypatch):
    replies = iter([
        {"providers": [
            {"provider_id": "m3-48-1", "se_public_key": "key3"},
            {"provider_id": "m4-128-1", "se_public_key": "key4"},
            {"provider_id": "", "se_public_key": "x"},
            "junk",
        ]},
        {"earnings": [
            {"provider_id": "m4-128-1", "provider_key": "session-m4"},
            {"provider_id": "m3-48-1", "provider_key": "session-m3"},
            {"provider_id": "other", "provider_key": "skip"},
        ]},
    ])
    monkeypatch.setattr(demand, "_get_json", lambda *args: next(replies))
    hosts = demand.fetch_account_provider_hosts("https://example.test", "test-key")
    assert hosts[hashlib.sha256(b"session-m4").hexdigest()] == "m4-128-1"
    assert hosts[hashlib.sha256(b"session-m3").hexdigest()] == "m3-48-1"
    # Providers with no payouts yet still appear via sha256(provider_id).
    assert hosts[hashlib.sha256(b"m4-128-1").hexdigest()] == "m4-128-1"
    assert "other" not in hosts.values()


def test_account_identity_ingest_runs_on_probe_host_only(monkeypatch, fake_pool):
    mapping = {"aa": "m4-128-1", "bb": "m3-48-1"}
    monkeypatch.setattr(demand, "fetch_account_provider_hosts", lambda *a: mapping)
    probe = SimpleNamespace(probe_self_route=True, api_key="k", base_url="https://example.test")
    pool = fake_pool()
    collector._ingest_account_provider_identities(probe, pool)
    assert pool.calls[0][1] == sorted(mapping.items())
    silent = fake_pool()
    collector._ingest_account_provider_identities(
        SimpleNamespace(probe_self_route=False, api_key="k", base_url="https://example.test"), silent)
    assert silent.calls == []
