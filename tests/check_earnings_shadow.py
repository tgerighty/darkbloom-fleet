"""PostgreSQL regression check; TEMP tables isolate all fixtures from live data."""
from contextlib import contextmanager
from fleet import attribution, config, db, earnings_shadow
from psycopg.types.json import Jsonb

pool = db.get_pool(config.load_configs()[0].database_url)
with pool.connection() as conn:
    conn.execute('CREATE TEMP TABLE daemon_snapshots (host text, observed_at double precision, fresh bool, warm_models text[], manager jsonb)')
    conn.execute('CREATE TEMP TABLE demand_samples (host text, model text, observed_at double precision, pressure double precision)')
    conn.execute('CREATE TEMP TABLE provider_identities (provider_hash text, host text)')
    conn.execute('CREATE TEMP TABLE earnings (host text, payout_rowid bigint, provider_hash text, model text, micro_usd bigint, created_at double precision)')
    conn.execute("INSERT INTO provider_identities VALUES ('one','test-m1'),('two','test-m3'),('conflict','test-m1'),('conflict','test-m3')")
    for host in ['test-m1', 'test-m3']:
        conn.cursor().executemany('INSERT INTO daemon_snapshots VALUES (%s,%s,%s,%s,%s)', [
            (host, 90000+i*60, host == 'test-m3' or i<60, ['a'], Jsonb({'target_model':'a'})) for i in range(121)])
        conn.execute('INSERT INTO demand_samples VALUES (%s,%s,%s,%s)', (host,'a',90000,2))
        # Each Mac has a copy of the account-wide ledger. These MUST NOT double income.
        conn.cursor().executemany('INSERT INTO earnings VALUES (%s,%s,%s,%s,%s,%s)', [
            (host, 1, 'one', 'a', 1000000, 95000), (host, 2, 'two', 'a', 2000000, 95000),
            (host, 3, 'one', 'base_reward', 9000000, 95000),
            (host, 4, 'conflict', 'a', 9000000, 95000)])
    class Pinned:
        @contextmanager
        def connection(self):
            yield conn
    one = earnings_shadow.build_profile(Pinned(), 'test-m1', 100000)['models']['a']
    two = earnings_shadow.build_profile(Pinned(), 'test-m3', 100000)['models']['a']
    assert one['allocated_seconds'] == two['allocated_seconds'] == 7200
    assert one['warm_seconds'] == 3600 and two['warm_seconds'] == 7200
    assert one['inference_usd'] == 1 and two['inference_usd'] == 2
    assert one['paid_requests'] == two['paid_requests'] == 1
    assert one['pressure_average'] == 2
    conn.execute("INSERT INTO earnings VALUES ('test-m1',5,NULL,'a',500000,95000),"
                 "('test-m3',5,'one','a',500000,95000)")
    selected = conn.execute(attribution.unique_payouts_sql('provider_hash', 'payout_rowid = 5')).fetchone()
    assert selected['provider_hash'] == 'one'
    with_duplicate = earnings_shadow.build_profile(Pinned(), 'test-m1', 100000)['models']['a']
    assert with_duplicate['paid_requests'] == 2 and with_duplicate['inference_usd'] == 1.5
    conn.rollback()
pool.close()
print('earnings SQL: exact host attribution, deduplication, base-reward exclusion, failed-loading time passed')
