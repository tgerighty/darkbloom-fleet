"""Payout attribution. The earnings ledger on every Mac is account-wide, so
the `host` column on an earnings row names only whose copy we read, not who
served the request. A payout's provider_hash names the provider *session*
that earned it; this module maps each hash to the host whose daemon actually
served it, by watching each host's own request counter (daemon_snapshots).
Recomputed on every build_status call — a handful of hashes a day, so no
caching table (see progress.md).
"""
from __future__ import annotations

from psycopg_pool import ConnectionPool

# One row per (provider_hash, host) with the number of payouts that host's
# request counter rose across: a payout votes for host h when h served at
# least one request in the snapshot interval containing the payout (prev is
# the greatest snapshot strictly before the payout, next the first at or
# after it; same started_at, else the counter reset at a restart would read
# as a rise). Both hosts hold the same ledger rows, hence the DISTINCT.
_VOTES_SQL = """
WITH payout AS (
    SELECT DISTINCT payout_rowid, provider_hash, created_at FROM earnings WHERE provider_hash IS NOT NULL
),
pair AS (
    SELECT host, observed_at AS next_at, requests_served AS next_served, started_at AS next_started,
           lag(observed_at) OVER w AS prev_at,
           lag(requests_served) OVER w AS prev_served,
           lag(started_at) OVER w AS prev_started
    FROM daemon_snapshots
    WINDOW w AS (PARTITION BY host ORDER BY observed_at)
),
vote AS (
    SELECT DISTINCT p.provider_hash AS provider_hash, s.host AS host
    FROM payout p JOIN pair s
      ON s.prev_at < p.created_at AND p.created_at <= s.next_at
     AND s.prev_started = s.next_started AND s.next_served > s.prev_served
)
SELECT provider_hash, host, count(*) AS votes FROM vote GROUP BY provider_hash, host
"""


def provider_hosts(pool: ConnectionPool) -> dict[str, str]:
    """provider_hash -> the host that served it. The hash goes to the host
    with the most votes; a tie or no votes at all leaves it unattributed
    (better to show no money than the other machine's)."""
    with pool.connection() as conn:
        rows = conn.execute(_VOTES_SQL).fetchall()
    votes: dict[str, dict[str, int]] = {}
    for row in rows:
        votes.setdefault(str(row["provider_hash"]), {})[str(row["host"])] = int(row["votes"])
    attributed: dict[str, str] = {}
    for provider_hash, by_host in votes.items():
        top = max(by_host.values())
        winners = [host for host, count in by_host.items() if count == top]
        if len(winners) == 1:
            attributed[provider_hash] = winners[0]
    return attributed


def unattributed_recent(pool: ConnectionPool, host: str, attributed: dict[str, str], limit: int = 50) -> int:
    """How many of this host's latest `limit` ledger rows map to no host: NULL
    provider_hash (ingested before attribution existed) or a hash with no
    winning votes yet. Shown on the dashboard so incomplete attribution is
    visible rather than silently looking like zero earnings."""
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT provider_hash FROM earnings WHERE host = %s ORDER BY created_at DESC LIMIT %s",
            (host, limit),
        ).fetchall()
    return sum(1 for row in rows if row["provider_hash"] not in attributed)
