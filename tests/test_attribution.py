from fleet import attribution


def _vote_rows(*rows):
    return [{"payout_rowid": pid, "provider_hash": h, "host": host} for pid, h, host in rows]


def test_the_hash_goes_to_the_host_with_the_most_votes(fake_pool):
    pool = fake_pool(_vote_rows(
        (1, "s1", "mac1"), (2, "s1", "mac1"), (3, "s1", "mac1"),
        (4, "s1", "mac2"),
        (5, "s2", "mac2"), (6, "s2", "mac2"),
    ))
    assert attribution.provider_hosts(pool) == {"s1": "mac1", "s2": "mac2"}


def test_a_tie_or_no_votes_leaves_the_hash_unattributed(fake_pool):
    pool = fake_pool(_vote_rows(
        (1, "tie", "mac1"), (2, "tie", "mac1"),
        (3, "tie", "mac2"), (4, "tie", "mac2"),
        (5, "solo", "mac1"),
    ))
    assert attribution.provider_hosts(pool) == {"solo": "mac1"}
    assert attribution.provider_hosts(fake_pool([])) == {}


def test_vote_sql_emits_one_row_per_payout_and_rising_host():
    sql = attribution._VOTES_SQL
    assert "payout_rowid" in sql
    assert "GROUP BY" not in sql
    assert "next_served > s.prev_served" in sql
    assert "provider_hash <> ''" in sql


def test_a_dual_host_rise_leaves_the_hash_unattributed(fake_pool):
    pool = fake_pool(_vote_rows((1, "s1", "mac1"), (1, "s1", "mac2")))
    assert attribution.provider_hosts(pool) == {}


def test_unique_rises_still_assign_a_hash_after_dropping_dual_host_payouts(fake_pool):
    pool = fake_pool(_vote_rows(
        (1, "s1", "mac1"),
        (2, "s1", "mac1"), (2, "s1", "mac2"),
        (3, "s1", "mac1"),
    ))
    assert attribution.provider_hosts(pool) == {"s1": "mac1"}


def test_unattributed_recent_counts_null_and_unknown_hashes(fake_pool):
    pool = fake_pool([{"provider_hash": None}, {"provider_hash": "s1"}, {"provider_hash": "no-votes"}])
    assert attribution.unattributed_recent(pool, {"s1": "h"}, now=50.0) == 2


def test_empty_provider_hash_is_not_attributed(fake_pool):
    pool = fake_pool(_vote_rows((1, "", "mac1"), (2, "", "mac1"), (3, None, "mac1")))
    assert attribution.provider_hosts(pool) == {}


def test_unique_payouts_prefer_a_populated_hash():
    sql = attribution.unique_payouts_sql("provider_hash, created_at", "created_at <= %s")
    assert "DISTINCT ON (payout_rowid)" in sql
    assert "(provider_hash IS NULL OR provider_hash = '')" in sql


def test_unattributed_recent_uses_the_account_wide_unique_ledger(fake_pool):
    pool = fake_pool([{"provider_hash": "s_other"}, {"provider_hash": None}])
    assert attribution.unattributed_recent(pool, {"s_other": "mac2", "s1": "mac1"}, now=9.0) == 1
    sql, params = pool.calls[0]
    assert "DISTINCT ON (payout_rowid)" in sql
    assert "host = %s" not in sql
    assert "created_at <= %s" in sql
    assert params == (9.0, 50)


def test_exact_identity_recovers_dual_host_jobs_and_overrides_wrong_votes(fake_pool):
    rows = _vote_rows((1, 'm1', 'mac1'), (1, 'm1', 'mac2'), (2, 'm3', 'mac1'))
    identities = [{'provider_hash': 'm1', 'host': 'mac1'}, {'provider_hash': 'm3', 'host': 'mac2'}]
    assert attribution.provider_hosts(fake_pool(rows, identities)) == {'m1': 'mac1', 'm3': 'mac2'}
    identities.append({'provider_hash': 'm3', 'host': 'mac1'})
    assert attribution.provider_hosts(fake_pool(rows, identities)) == {'m1': 'mac1'}
