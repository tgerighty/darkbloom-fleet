"""Payout attribution. The earnings ledger on every Mac is account-wide, so
the `host` column on an earnings row names only whose copy we read, not who
served the request. A payout's provider_hash names the provider *session*
that earned it; this module maps each hash to the host whose daemon actually
served it, using attestation identity joins. Historical sessions without an
identity join fall back to each host's request counter (daemon_snapshots).
Exact joins persist across provider restarts; counter votes are recomputed
once per /api/status request.
"""
from __future__ import annotations

from psycopg_pool import ConnectionPool

Row = dict[str, object]

# One row per (payout_rowid, host) whose request counter rose across the
# snapshot interval containing that payout (prev is the greatest snapshot
# strictly before the payout, next the first at or after it; same
# started_at, else a restart would read as a rise). Both hosts hold the
# same ledger rows, hence the DISTINCT. Dual-host rises stay in this
# result; _attributed_from_votes drops them.
_VOTES_SQL = """
WITH payout AS (
    SELECT DISTINCT payout_rowid, provider_hash, created_at FROM earnings
    WHERE provider_hash IS NOT NULL AND provider_hash <> '' AND model != 'base_reward'
),
pair AS (
    SELECT host, observed_at AS next_at, requests_served AS next_served, started_at AS next_started,
           lag(observed_at) OVER w AS prev_at,
           lag(requests_served) OVER w AS prev_served,
           lag(started_at) OVER w AS prev_started
    FROM daemon_snapshots
    WINDOW w AS (PARTITION BY host ORDER BY observed_at)
)
SELECT p.payout_rowid AS payout_rowid, p.provider_hash AS provider_hash, s.host AS host
FROM payout p JOIN pair s
  ON s.prev_at < p.created_at AND p.created_at <= s.next_at
 AND s.prev_started = s.next_started AND s.next_served > s.prev_served
"""


def unique_payouts_sql(columns: str, where: str) -> str:
    """One copy of each Mac ledger row. PRIMARY KEY is (host, payout_rowid);
    payout_rowid is the identity. ORDER BY host picks one copy deterministically
    when both machines ingested the same payout."""
    return (
        f"SELECT DISTINCT ON (payout_rowid) {columns} FROM earnings "
        f"WHERE {where} ORDER BY payout_rowid, (provider_hash IS NULL OR provider_hash = ''), host"
    )


def _unique_vote_leaders(votes: dict[str, dict[str, int]]) -> dict[str, str]:
    attributed: dict[str, str] = {}
    for provider_hash, by_host in votes.items():
        top = max(by_host.values())
        winners = [host for host, count in by_host.items() if count == top]
        if len(winners) == 1:
            attributed[provider_hash] = winners[0]
    return attributed


def _attributed_from_votes(rows: list[Row]) -> dict[str, str]:
    """A payout votes only when exactly one host's counter rose in its
    interval. The hash then goes to the unique vote leader."""
    hosts_for: dict[int, set[str]] = {}
    hash_for: dict[int, str] = {}
    for row in rows:
        provider_hash = str(row["provider_hash"] or "")
        if not provider_hash:
            continue
        payout_id = int(row["payout_rowid"])
        hosts_for.setdefault(payout_id, set()).add(str(row["host"]))
        hash_for[payout_id] = provider_hash
    votes: dict[str, dict[str, int]] = {}
    for payout_id, hosts in hosts_for.items():
        if len(hosts) != 1:
            continue
        host = next(iter(hosts))
        by_host = votes.setdefault(hash_for[payout_id], {})
        by_host[host] = by_host.get(host, 0) + 1
    return _unique_vote_leaders(votes)


def provider_hosts(pool: ConnectionPool) -> dict[str, str]:
    """Exact identities override counter votes; conflicting identities stay unassigned."""
    with pool.connection() as conn:
        rows = conn.execute(_VOTES_SQL).fetchall()
        identities = conn.execute("SELECT provider_hash, host FROM provider_identities").fetchall()
    attributed = _attributed_from_votes(rows)
    exact: dict[str, set[str]] = {}
    for row in identities:
        exact.setdefault(row["provider_hash"], set()).add(row["host"])
    for provider_hash, hosts in exact.items():
        attributed.pop(provider_hash, None)
        if len(hosts) == 1:
            attributed[provider_hash] = next(iter(hosts))
    return attributed


_UNATTRIBUTED_SQL = (
    "SELECT provider_hash FROM ("
    + unique_payouts_sql("provider_hash, created_at", "created_at <= %s")
    + ") unique_payouts ORDER BY created_at DESC LIMIT %s"
)


def unattributed_recent(pool: ConnectionPool, attributed: dict[str, str],
                        now: float, limit: int = 50) -> int:
    """How many of the latest `limit` unique ledger payouts map to no host:
    NULL provider_hash (ingested before attribution existed) or a hash with
    no winning votes yet. Same account-wide row identity as recent payouts.
    Shown on the dashboard so incomplete attribution is visible rather than
    silently looking like zero earnings."""
    with pool.connection() as conn:
        rows = conn.execute(_UNATTRIBUTED_SQL, (now, limit)).fetchall()
    return sum(1 for row in rows if row["provider_hash"] not in attributed)
