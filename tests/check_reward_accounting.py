"""Run in the app container: python tests/check_reward_accounting.py.
Uses temporary tables, rolled back on exit; never changes the real ledger.
"""
import psycopg
from psycopg.rows import dict_row
from fleet import attribution, card, hourly, queries
from fleet.config import _database_url


def check():
    with psycopg.connect(_database_url(), row_factory=dict_row) as conn:
        conn.execute("CREATE TEMP TABLE provider_identities (provider_hash text, host text)")
        conn.execute("CREATE TEMP TABLE earnings (host text, payout_rowid bigint, "
                     "provider_hash text, model text, created_at float, micro_usd bigint, completion_tokens bigint)")
        rows = [
            (1, 'm1', 'nemotron', 100, 100, 50),
            (2, 'm1', 'base_reward', 110, 2000, 0),
            (3, 'm3', 'nemotron', 120, 300, 150),
            (4, 'm3', 'base_reward', 130, 1800, 0),
            (5, 'unknown', 'base_reward', 140, 9999, 0),
            (6, 'm1', 'base_reward', 1000, 9999, 0),
        ]
        for host in ['copy1', 'copy2']:
            conn.cursor().executemany("INSERT INTO earnings VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                      [(host, *r) for r in rows])
        for provider in ['m1', 'm3']:
            args = (0, 200, [provider])
            assert conn.execute(queries._EARNINGS_SUM_SQL, args).fetchone()['total'] == 2100
            assert conn.execute(card._SESSION_TOTALS_SQL, args).fetchone()['requests'] == 1
            jobs = conn.execute(hourly._HOURLY_SQL, args).fetchall()
            assert sum(row['n'] for row in jobs) == 1
            assert all(row['model'] != 'base_reward' for row in jobs)
        conn.execute("CREATE TEMP TABLE daemon_snapshots (host text, observed_at float, "
                     "requests_served bigint, started_at float)")
        conn.execute("INSERT INTO daemon_snapshots VALUES ('mac1',0,0,1),('mac1',200,1,1)")
        votes = conn.execute(attribution._VOTES_SQL).fetchall()
        assert {r['payout_rowid'] for r in votes} == {1, 3}
        # Exact identities bypass inference, including conflicts (resolved above SQL).
        conn.execute("INSERT INTO provider_identities VALUES ('m1','mac1')")
        assert {r['payout_rowid'] for r in conn.execute(attribution._VOTES_SQL)} == {3}
        conn.execute("DELETE FROM provider_identities")
        # The next snapshot must be from the same daemon session.
        conn.execute("UPDATE daemon_snapshots SET started_at=2 WHERE observed_at=200")
        assert conn.execute(attribution._VOTES_SQL).fetchall() == []
        conn.execute("UPDATE daemon_snapshots SET started_at=1")
        # Payouts exactly on a snapshot belong to the interval ending there.
        conn.execute("UPDATE earnings SET created_at=200 WHERE payout_rowid=1")
        assert {r['payout_rowid'] for r in conn.execute(attribution._VOTES_SQL)} == {1, 3}
        # Simultaneous work must not create a unique-host vote.
        conn.execute("INSERT INTO daemon_snapshots VALUES ('mac2',0,0,1),('mac2',200,1,1)")
        assert attribution._attributed_from_votes(conn.execute(attribution._VOTES_SQL).fetchall()) == {}
        conn.rollback()
    print('PASS: rewards counted once per provider; unknown/future excluded; jobs and votes exclude rewards')


if __name__ == '__main__':
    check()
