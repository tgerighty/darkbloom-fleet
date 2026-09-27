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
    uuid_m3 = "00000000-0000-4000-8000-000000000003"
    uuid_m4 = "00000000-0000-4000-8000-000000000004"
    replies = iter([
        {"providers": [
            {"provider_id": uuid_m3, "se_public_key": "key3"},
            {"provider_id": uuid_m4, "se_public_key": "key4"},
            {"provider_id": "", "se_public_key": "x"},
            "junk",
        ]},
        {"earnings": [
            {"provider_id": uuid_m4, "provider_key": "session-m4"},
            {"provider_id": uuid_m3, "provider_key": "session-m3"},
            {"provider_id": "other", "provider_key": "skip"},
        ]},
    ])
    monkeypatch.setattr(demand, "_get_json", lambda *args: next(replies))
    hosts = demand.fetch_account_provider_hosts("https://example.test", "test-key")
    assert hosts[hashlib.sha256(b"session-m4").hexdigest()] == uuid_m4
    assert hosts[hashlib.sha256(b"session-m3").hexdigest()] == uuid_m3
    assert hosts[hashlib.sha256(uuid_m4.encode()).hexdigest()] == uuid_m4
    assert "other" not in hosts.values()


def test_account_identity_ingest_runs_on_probe_host_only(monkeypatch, fake_pool):
    mapping = {"aa": "00000000-0000-4000-8000-000000000004",
               "bb": "00000000-0000-4000-8000-000000000003"}
    monkeypatch.setattr(demand, "fetch_account_provider_hosts", lambda *a: mapping)
    probe = SimpleNamespace(probe_self_route=True, api_key="k", base_url="https://example.test")
    pool = fake_pool()
    collector._ingest_account_provider_identities(probe, pool)
    assert pool.calls[0][1] == sorted(mapping.items())
    assert "DELETE FROM provider_identities" in pool.calls[1][0]
    assert "DELETE FROM provider_fleet_hosts" in pool.calls[2][0]
    silent = fake_pool()
    collector._ingest_account_provider_identities(
        SimpleNamespace(probe_self_route=False, api_key="k", base_url="https://example.test"), silent)
    assert silent.calls == []


def test_record_provider_fleet_link_uses_se_key(monkeypatch, fake_pool):
    uuid_m3 = "00000000-0000-4000-8000-000000000003"
    monkeypatch.setattr(demand, "fetch_provider_ids_for_key", lambda *a: {uuid_m3})
    cfg = SimpleNamespace(host_id="m3-48-1", api_key="k", base_url="https://example.test")
    daemon = SimpleNamespace(fresh=True, attestation_public_key="key3")
    pool = fake_pool()
    collector._record_provider_fleet_link(cfg, pool, daemon)
    assert pool.calls[0][1] == [(uuid_m3, "m3-48-1")]
    assert "provider_fleet_hosts" in pool.calls[0][0]
    for bad in (None, SimpleNamespace(fresh=False, attestation_public_key="key3"),
                SimpleNamespace(fresh=True, attestation_public_key=None)):
        silent = fake_pool()
        collector._record_provider_fleet_link(cfg, silent, bad)
        assert silent.calls == []
