# Claims ledger

Generated 2026-11-04 from the repo's own README.

| Claim | Tag | Evidence |
|---|---|---|
| Point-in-time-correct join layer over marketdata-lakehouse (prices) and pit-fundamentals-store (fundamentals) | Demonstrated — per portfolio-products-plan.md P0-12, 13 tests pass locally against two fixture Postgres DBs with real AAPL FY2009 restatement data | `tests/`, CI (`ci.yml` written, Bud to move to repo root per P0-12) |
| Resolves tickers to SEC identifiers from SEC's live ticker map | Demonstrated | README "What was built" |
| Batches multi-security fundamentals queries into a fixed number of round trips regardless of universe size | Stated as built; not independently re-verified at scale this session | README "Methodology" |
| Zero cross-repo Python imports — each upstream treated as a database, not a library dependency | Demonstrated (architectural claim, verifiable by inspection) | import statements |
| CI not yet confirmed green on GitHub (per P0-12, `ci.yml` was written to repo root by the device bridge, pending Bud moving it) | Open item carried from plan doc | portfolio-products-plan.md |

## Action
No overclaim found in the README text itself. Confirm the P0-12 CI-file-placement is done and CI has actually run green before treating "13 tests pass" as repo-verified rather than locally-verified.
