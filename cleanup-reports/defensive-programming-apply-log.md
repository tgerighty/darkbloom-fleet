# Defensive programming apply log

RED: `1dbed63` and `ad52109` (boundary regressions reproduced). GREEN: `235abf7` and `938cd2f` (219 Python and 66 Vitest tests passed).

| Item | Result |
|---|---|
| defensive-001 | APPLY current-age check to API `daemon_fresh`; healthy-badge age check was RESOLVED-UPSTREAM. |
| defensive-002 | APPLY: reject a nonempty self-route list with no valid rows. Keep established mixed-row behavior and a genuinely empty list. |
| defensive-003 | APPLY: reject unknown capacity envelopes and supplied non-list price rows. |
| defensive-004 | APPLY: catch numeric `OverflowError` in existing optional parsers. |
| defensive-005 | SKIP NEEDS-VERIFICATION: null or omission could break the external earnings-profile consumer; evidence completeness is unconfirmed. |
| defensive-006 | APPLY: malformed HTTP 200 status, including malformed host and demand rows, keeps the last good dashboard data and shows the stale warning. |

No I/O catch or security guard was removed.
