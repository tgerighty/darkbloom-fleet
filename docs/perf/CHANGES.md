# Dashboard performance changes

## 2026-09-27

Live profile on image `c81307d`: `unattributed_recent` took 13,401 ms on 444,262 earnings rows and ran once per host. `shared_status_data` took 3,211 ms; two host rows took 15,230 ms and 16,142 ms; `/api/status` took about 33 seconds.

- Compute the account-wide unattributed count once per `/api/status` request and pass it to every host row.
- Read at most the newest `limit` payouts per ledger host through the existing host/time index, then preserve the current unique-payout selection and NULL/empty-hash counting rules.
- Reduce the common per-host status path from 15 statements and 13 checkouts to 14 statements and 12 checkouts.
- Use binary search to reduce each serving window to its relevant ordered snapshots.

No post-change live database timing is available. The fixture regression compares the pre-change unique-payout selection with the per-host candidate limit on duplicate host copies.
