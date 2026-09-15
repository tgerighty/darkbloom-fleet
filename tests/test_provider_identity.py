import hashlib
from dataclasses import replace

import pytest

from fleet import collector, demand, remote
from types import SimpleNamespace


def test_identity_join_selects_only_this_mac_and_ignores_missing_ids(monkeypatch, fake_pool):
    replies = iter([
        {'providers': [{'provider_id': 'm1', 'se_public_key': 'key1', 'status': 'serving'},
                       {'provider_id': 'm3', 'se_public_key': 'key3'}]},
        {'earnings': [{'provider_id': 'm1', 'provider_key': 'session1'},
                      {'provider_id': 'm3', 'provider_key': 'session3'},
                      {'provider_id': '', 'provider_key': 'session3'},
                      {'provider_id': 'm1'}, {'provider_id': 'm1', 'provider_key': 'session1'}]},
    ])
    monkeypatch.setattr(demand, '_get_json', lambda *args: next(replies))
    hashes = demand.fetch_provider_hashes('https://example.test', 'test-key', 'key1')
    assert hashes == {hashlib.sha256(k.encode()).hexdigest() for k in ('session1', 'm1')}
    monkeypatch.setattr(remote, '_run_ssh', lambda *args, **kw:
                        '{"written_at": 100, "attestation_public_key": "key1"}')
    cfg = SimpleNamespace(host_id='mac1', api_key='test-key',
                          base_url='https://example.test', daemon_freshness_seconds=90)
    daemon = remote.fetch_daemon_state(cfg, now=100)
    assert daemon.attestation_public_key == 'key1'
    monkeypatch.setattr(demand, 'fetch_provider_hashes', lambda *args: hashes)
    pool = fake_pool()
    collector._ingest_provider_identity(cfg, pool, daemon)
    assert pool.calls[0][1] == [(h, 'mac1') for h in sorted(hashes)]
    stale_pool = fake_pool()
    collector._ingest_provider_identity(cfg, stale_pool, replace(daemon, fresh=False))
    assert stale_pool.calls == []


def test_malformed_identity_response_fails(monkeypatch):
    monkeypatch.setattr(demand, '_get_json', lambda *args: {})
    with pytest.raises(ValueError):
        demand.fetch_provider_hashes('https://example.test', 'test-key', 'key1')
