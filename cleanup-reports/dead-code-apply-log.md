# Dead code apply log

RED: `19ff335` (208 Python and 65 Vitest tests passed). GREEN: `02020c8` (same counts).

| Item | Result |
|---|---|
| dead-001 | SKIP REVIEW: external SQL consumers of `switch_lease` are unknown. |
| dead-002 | APPLY: remove unused `decisions` fixture parameter and three arguments. |
| dead-003 | SKIP REVIEW: external imports of the served `chip` export are unknown. |
| dead-004 | APPLY: remove unused `nowSec` test-harness export. |

Existing status and dashboard-poll tests cover the changed helpers.
