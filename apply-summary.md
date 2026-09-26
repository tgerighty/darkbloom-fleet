# CBA nine-domain apply — 2026-09-26

Base tip: `5d4b680cb3bfae8d98576c4fae27de7a2c47b0b2` (`origin/main`). Terry authorized safe narrative findings despite `verified: false` in the assessment JSON. Source: the nine files in `cleanup-reports/` only.

| Domain | Applied | Skipped or resolved |
|---|---|---|
| Dead code | dead-002, dead-004 | dead-001 and dead-003: external consumers need review. |
| Legacy code | legacy-004, legacy-005 | legacy-001–003: external use or retention needs verification. |
| AI slop | ai-slop-001–008: correct stale text | None. |
| Deduplication | dedup-001 and dedup-003 | dedup-002: resolved upstream; dedup-004–008: keep separate. |
| Type consolidation | None | type-001: review only; type-002: keep separate. |
| Circular dependencies | None | No cycles in the assessment or current production import graph. |
| Weak typing | WT-001 runtime guards, WT-002, WT-004 | WT-001 `TypedDict` expansion and WT-003/005/006/007: optional typing without a checker or confirmed external contract. |
| Defensive programming | defensive-001–004 and 006 | defensive-001 health badge: resolved upstream; defensive-005: external earnings consumer and evidence contract unverified. |
| LOC limits | None | loc-001 and 003: conditional later work; loc-002: exempt. |

RED commits: `19ff335` records the baseline assessments; `1dbed63` and `ad52109` add failing boundary regressions. GREEN commits: `02020c8` (subtractive), `07bb525` (structural), `235abf7` and `938cd2f` (boundary fixes). Per-item results and overlap handling are in the nine `*-apply-log.md` files. Existing tests covered the comment, fixture, and deduplication paths. The new tests reproduced the failures before production changes. Independent diff review found two edge cases, which were fixed and covered by tests.

Verification: baseline 208 Python and 65 Vitest tests passed; final 219 Python and 66 Vitest tests passed. Ruff core (`E4,E7,E9,F`), Python compilation, and `git diff --check` passed. This repo has no configured Python type checker. The cluster Vitest runner failed before executing tests (job `3de30dc3-592f-4960-862e-f48ac0e21576`, all shards exit 123 with empty logs); the local locked Vitest 5.0.0 suite passed. Runtime source and tests changed across 22 files, excluding assessment reports and apply logs.

Remaining decisions: check external SQL use before removing `switch_lease` or decision history; confirm the earnings-profile consumer before changing missing-evidence output. The reports make serving and test-file splits conditional on later work. The open PR's exact-tip Sonar, CodeRabbit, and CI results are reported in the PR and final handoff.
