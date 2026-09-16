"""Jobs-per-hour panel: attributed payouts in 40 portions of each hour."""
from __future__ import annotations

import string
from collections import Counter

from psycopg_pool import ConnectionPool

from .attribution import unique_payouts_sql

Row = dict[str, object]

HOUR_SECONDS = 3_600
BUCKETS = 24  # the current hour and the 23 before it
PORTIONS = 40
PORTION_SECONDS = HOUR_SECONDS // PORTIONS
ALPHABET = string.ascii_uppercase
# Letters, then digits; anything beyond 36 models shares one overflow glyph
# rather than failing the whole status payload.
LABELS = ALPHABET + string.digits
OVERFLOW = "?"

_HOURLY_SQL = (
    "SELECT floor(created_at/3600)*3600 AS hour, "
    f"floor((created_at-floor(created_at/3600)*3600)/{PORTION_SECONDS}) AS portion, "
    "model, count(*) AS n FROM ("
    + unique_payouts_sql(
        "created_at, model",
        "created_at >= %s AND created_at <= %s AND provider_hash = ANY(%s) AND model != 'base_reward'",
    )
    + ") unique_payouts GROUP BY 1,2,3 ORDER BY 1 DESC"
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


def _percentages(busy: int, size: int) -> tuple[int, int]:
    if not size:
        return 0, 0
    serving = round(100 * busy / size)
    return serving, 100 - serving


def _current_hour_size(hour: int, newest: int, now: float) -> int:
    if hour < newest:
        return PORTIONS
    if now <= hour:
        return 0
    return min(PORTIONS, int((now - hour) // PORTION_SECONDS) + 1)


def _hour_rows(hours: range, newest: int, now: float, buckets: dict[int, dict[str, int]],
               portions: dict[int, list[Counter[str]]]) -> list[Row]:
    output = []
    for hour in hours:
        size = _current_hour_size(hour, newest, now)
        values = [max(counts, key=lambda model, values=counts: (values[model], model)) if counts else None
                  for counts in portions[hour][:size]]
        busy = sum(value is not None for value in values)
        serving, idle = _percentages(busy, size)
        output.append({"hour": hour, "jobs": sum(buckets[hour].values()), "portions": values,
                       "serving_percentage": serving, "idle_percentage": idle})
    return output


def hourly_jobs(pool: ConnectionPool, hashes: list[str], now: float) -> Row:
    """Return one model letter or idle dot for each elapsed hour portion."""
    newest = int(now // HOUR_SECONDS) * HOUR_SECONDS
    hours = range(newest, newest - BUCKETS * HOUR_SECONDS, -HOUR_SECONDS)
    with pool.connection() as conn:
        rows = conn.execute(_HOURLY_SQL, (hours[-1], now, hashes)).fetchall()
    buckets: dict[int, dict[str, int]] = {hour: {} for hour in hours}
    portions: dict[int, list[Counter[str]]] = {
        hour: [Counter() for _ in range(PORTIONS)] for hour in hours
    }
    for row in sorted(rows, key=lambda r: (float(r["hour"]), str(r["model"]))):
        bucket = buckets.get(int(row["hour"]))  # a skewed future row has no bucket
        if bucket is not None:
            model = str(row["model"])
            count = int(row["n"])
            bucket[model] = bucket.get(model, 0) + count
            portions[int(row["hour"])][int(row["portion"])][model] += count
    totals: dict[str, int] = {}  # insertion order = order of first appearance
    for hour in reversed(hours):
        for model in sorted(buckets[hour]):
            totals[model] = totals.get(model, 0) + buckets[hour][model]
    letters = _assign_letters(list(totals))
    return {
        "legend": [{"letter": letters[m], "model": m} for m in sorted(totals)],
        "rows": _hour_rows(hours, newest, now, buckets, portions),
    }


def share_legends(hosts: list[Row]) -> None:
    """Use one ordered legend so model letters and colour slots match across hosts."""
    panels = [host["hourly_jobs"] for host in hosts if host.get("hourly_jobs") is not None]
    models = sorted({entry["model"] for panel in panels for entry in panel["legend"]})
    letters = _assign_letters(models)
    legend = [{"letter": letters[model], "model": model} for model in models]
    for panel in panels:
        panel["legend"] = legend
