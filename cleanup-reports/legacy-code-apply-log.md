# Legacy code apply log

RED: `19ff335` (208 Python and 65 Vitest tests passed). GREEN: `02020c8` (same counts).

| Item | Result |
|---|---|
| legacy-001 | SKIP NEEDS-VERIFICATION: `switch_lease` can have external SQL users. |
| legacy-002 | SKIP NEEDS-VERIFICATION: decision history has an explicit retention contract. |
| legacy-003 | SKIP NEEDS-VERIFICATION: measured-cost wrapper has test callers and possible external users. |
| legacy-004 | APPLY: remove retired decision fixture inputs; preserve the explicit absent-panel regression case. |
| legacy-005 | APPLY through ai-slop-002 and ai-slop-008; edit each comment once. |
