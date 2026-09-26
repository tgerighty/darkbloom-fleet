# Weak typing apply log

RED: `1dbed63` and `ad52109` (new boundary tests failed as expected). GREEN: `235abf7` and `938cd2f` (219 Python and 66 Vitest tests passed).

| Item | Result |
|---|---|
| WT-001 | APPLY runtime shape checks for required probe flags and saved alert records; preserve valid signals when optional manager fields are malformed. Malformed `pending` handling was RESOLVED-UPSTREAM. SKIP optional `TypedDict` expansion: no checker is configured. |
| WT-002 | APPLY through defensive-006: require a `hosts` array before accepting dashboard status. |
| WT-003 | SKIP: six broad row aliases span distinct data shapes; the report conditions the larger typing change on a checker. |
| WT-004 | APPLY: raw HTTP JSON returns `object`; supplied pricing rows require a list. |
| WT-005–006 | SKIP: optional annotations depend on a checker and confirmed external contracts. |
| WT-007 | SKIP REVIEW: local config typing is conditional on a checker. |
