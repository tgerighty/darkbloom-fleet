"""Jobs-per-hour panel: attributed payout counts bucketed by hour over the
last 24 h, plus the letter legend the page's terminal-style rendering uses.
Kept here so queries.py stays small (same split as card.py); the 40-char
distribution bar and the percentages are drawn client-side from each row's
`counts`, so the API stays data-only."""
from __future__ import annotations

import string

from psycopg_pool import ConnectionPool

Row = dict[str, object]

DAY_SECONDS = 86_400
ALPHABET = string.ascii_uppercase
# Letters, then digits; anything beyond 36 models shares one overflow glyph
# rather than failing the whole status payload.
LABELS = ALPHABET + string.digits
OVERFLOW = "?"

_HOURLY_SQL = (
    "SELECT floor(created_at/3600)*3600 AS hour, model, count(*) AS n FROM earnings "
    "WHERE host = %s AND created_at > %s AND provider_hash = ANY(%s) GROUP BY 1,2 ORDER BY 1 DESC"
)


def _assign_letters(order: list[str]) -> dict[str, str]:
    """One A–Z letter per model, in order of first appearance over the range:
    the initial of the model's name when free, else the initial of a later
    hyphen-separated word (gpt-oss-20b next to gemma-4-26b-qat settles on O),
    else the first still-free label (A–Z, then 0–9); past 36 models the rest
    share OVERFLOW so the payload never fails."""
    used: set[str] = set()
    letters: dict[str, str] = {}
    for model in order:
        words = model.split("-")
        candidates = [w[:1].upper() for w in (model[:1], *words[1:]) if w[:1].isalpha()]
        free = [c for c in candidates if c in ALPHABET and c not in used]
        letter = free[0] if free else next((c for c in LABELS if c not in used), OVERFLOW)
        used.add(letter)
        letters[model] = letter
    return letters


def hourly_jobs(pool: ConnectionPool, host: str, hashes: list[str], now: float) -> Row:
    """Legend (letter + model, alphabetical), each model's share of the whole
    range, and one row per hour bucket with a job count and per-model counts —
    newest first, only buckets with at least one job."""
    with pool.connection() as conn:
        rows = conn.execute(_HOURLY_SQL, (host, now - DAY_SECONDS, hashes)).fetchall()
    buckets: dict[int, dict[str, int]] = {}
    for row in sorted(rows, key=lambda r: (float(r["hour"]), str(r["model"]))):
        buckets.setdefault(int(row["hour"]), {})[str(row["model"])] = int(row["n"])
    totals: dict[str, int] = {}  # insertion order = order of first appearance
    for hour in sorted(buckets):
        for model in sorted(buckets[hour]):
            totals[model] = totals.get(model, 0) + buckets[hour][model]
    letters = _assign_letters(list(totals))
    jobs = sum(totals.values())
    return {
        "legend": [{"letter": letters[m], "model": m} for m in sorted(totals)],
        "range_share": {m: round(100 * n / jobs) for m, n in sorted(totals.items())},
        "rows": [{"hour": hour, "jobs": sum(buckets[hour].values()), "counts": buckets[hour]}
                 for hour in sorted(buckets, reverse=True)],
    }
