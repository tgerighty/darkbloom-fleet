"""Run in the app container: python tests/check_reward_accounting.py.
Uses temporary tables, rolled back on exit; never changes the real ledger.
"""
import psycopg
from psycopg.rows import dict_row
from fleet import attribution, card, hourly, queries
from fleet.config import _database_url


def check():
    with psycopg.connect(_database_url(), row_factory=dict_row) as conn:
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
        conn.rollback()
    print('PASS: rewards counted once per provider; unknown/future excluded; jobs and votes exclude rewards')


if __name__ == '__main__':
    check()
