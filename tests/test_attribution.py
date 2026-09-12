from fleet import attribution


def _vote_rows(*rows):
    return [{"provider_hash": h, "host": host, "votes": n} for h, host, n in rows]


def test_the_hash_goes_to_the_host_with_the_most_votes(fake_pool):
    pool = fake_pool(_vote_rows(("s1", "mac1", 3), ("s1", "mac2", 1), ("s2", "mac2", 2)))
    assert attribution.provider_hosts(pool) == {"s1": "mac1", "s2": "mac2"}


def test_a_tie_or_no_votes_leaves_the_hash_unattributed(fake_pool):
    pool = fake_pool(_vote_rows(("tie", "mac1", 2), ("tie", "mac2", 2), ("solo", "mac1", 1)))
    assert attribution.provider_hosts(pool) == {"solo": "mac1"}
    assert attribution.provider_hosts(fake_pool([])) == {}


def test_unattributed_recent_counts_null_and_unknown_hashes(fake_pool):
    pool = fake_pool([{"provider_hash": None}, {"provider_hash": "s1"}, {"provider_hash": "no-votes"}])
    assert attribution.unattributed_recent(pool, "h", {"s1": "h"}) == 2
