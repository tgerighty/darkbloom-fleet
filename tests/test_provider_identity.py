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


def test_identity_ingest_uses_fleet_host_id_not_provider_uuid(monkeypatch, fake_pool):
    provider_id = "00000000-0000-4000-8000-000000000003"
    replies = iter([
        {"providers": [{"provider_id": provider_id, "se_public_key": "key3"}]},
        {"earnings": [{"provider_id": provider_id, "provider_key": "nemotron-session"}]},
    ])
    monkeypatch.setattr(demand, "_get_json", lambda *args: next(replies))
    cfg = SimpleNamespace(host_id="m3-48-1", api_key="k", base_url="https://example.test")
    daemon = SimpleNamespace(fresh=True, attestation_public_key="key3")
    pool = fake_pool()
    collector._ingest_provider_identity(cfg, pool, daemon)
    assert pool.calls[0][1] == [
        (digest, "m3-48-1") for digest in sorted(
            hashlib.sha256(key.encode()).hexdigest()
            for key in (provider_id, "nemotron-session")
        )
    ]
    for bad_daemon in (None, SimpleNamespace(fresh=False, attestation_public_key="key3"),
                       SimpleNamespace(fresh=True, attestation_public_key=None)):
        silent = fake_pool()
        collector._ingest_provider_identity(cfg, silent, bad_daemon)
        assert silent.calls == []
