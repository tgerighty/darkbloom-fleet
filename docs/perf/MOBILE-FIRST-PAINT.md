# Mobile dashboard first-paint speedups

Evidence baseline: `docs/perf/history-bottlenecks.md` (~37k HTML chars/host with open hourly panel; full HTML rebuild + DOMParser on every 60s poll).

Changes (no feature removal):
- Lazy code-split `hourly.js` after first paint (idle); fold remains present with loading stub, then full chart.
- Skip identical re-renders via status fingerprint (cuts poll thrash DOM work when payload unchanged).
- Paginate recent payouts (15 → Show all N); full history still available.
- Pause `/api/status` polling while `document.hidden`; refresh on visible.
