# Deduplication apply log

RED: `19ff335` (208 Python and 65 Vitest tests passed; existing tests cover both call sites). GREEN: `07bb525` (same counts).

| Item | Result |
|---|---|
| dedup-001 | APPLY: one `fmtAge` in `ui.js`, imported by dashboard and host. |
| dedup-002 | RESOLVED-UPSTREAM: earnings profile already uses `unique_payouts_sql` and has mixed-hash regression coverage. |
| dedup-003 | APPLY: hourly legend uses existing `ui.js` HTML escaping. |
| dedup-004–008 | SKIP KEEP SEPARATE: one-line formatter, different loop rules, distinct test fixtures, different numeric contracts, and scoped test stubs. |
