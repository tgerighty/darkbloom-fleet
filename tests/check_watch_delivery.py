"""Run inside the fleet image with fleet.watch installed; uses only a TEMP table.
Checks delivery retries against a real PostgreSQL transaction and HTTP server.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from fleet import config, db, watch


class Receiver(BaseHTTPRequestHandler):
    status = 200
    received = []

    def do_POST(self):
        self.received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(self.status)
        self.end_headers()

    def log_message(self, *_args):
        pass


cfg = config.load_configs()[0]
pool = db.get_pool(cfg.database_url)
# Pin one connection so the TEMP table shadows any production watch_state.
with pool.connection() as conn:
    conn.execute('CREATE TEMP TABLE watch_state (host TEXT PRIMARY KEY, state JSONB NOT NULL)')
    conn.commit()

    class PinnedPool:
        def connection(self):
            from contextlib import contextmanager

            @contextmanager
            def transaction():
                with conn.transaction():
                    yield conn
            return transaction()

    server = HTTPServer(('127.0.0.1', 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    healthy = {'provider_running': True, 'provider_fresh': True, 'warm': ['oss'],
               'manager_running': True, 'manager_fresh': True, 'pending': None, 'reason': ''}
    failed = {**healthy, 'pending': {'target': 'gemma', 'command_error': 'bootstrap failed'}}
    try:
        with patch.object(watch.remote, '_run_ssh', return_value=json.dumps(failed)):
            watch.tick(cfg, PinnedPool(), url)
        assert len(Receiver.received[-1]) == 1
        assert Receiver.received[-1][0]['labels']['alertname'] == 'DarkbloomManagerSwitchFailed'
        Receiver.status = 503
        with patch.object(watch.remote, '_run_ssh', return_value=json.dumps(healthy)):
            try:
                watch.tick(cfg, PinnedPool(), url)
            except Exception as error:
                assert getattr(error, 'code', None) == 503
            else:
                raise AssertionError('failed delivery must not count as success')
        state = conn.execute('SELECT state FROM watch_state').fetchone()['state']
        assert state['DarkbloomManagerSwitchFailed']['ended']
        Receiver.status = 200
        with patch.object(watch.remote, '_run_ssh', return_value=json.dumps(healthy)):
            watch.tick(cfg, PinnedPool(), url)
        assert conn.execute('SELECT state FROM watch_state').fetchone()['state'] == {}
        assert Receiver.received[-1] == Receiver.received[-2]
        print('watch delivery: firing, failed recovery delivery, durable retry and resolution passed')
    finally:
        server.shutdown()
        thread.join()
pool.close()
