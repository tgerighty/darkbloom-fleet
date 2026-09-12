"""Shared fakes: a psycopg-shaped pool that records SQL and replays canned rows,
so the database layer runs without Postgres (Sonar's coverage sandbox has no
route to one)."""
from contextlib import contextmanager

import pytest


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self, pool):
        self._pool = pool

    def execute(self, sql, params=None):
        self._pool.calls.append((sql, params))
        return FakeResult(self._pool.responses.pop(0) if self._pool.responses else [])

    def cursor(self):
        return self

    def executemany(self, sql, rows):
        self._pool.calls.append((sql, list(rows)))


class FakePool:
    """Each `execute` consumes the next canned row list, in call order."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    @contextmanager
    def connection(self):
        yield FakeConnection(self)


@pytest.fixture
def fake_pool():
    return FakePool
