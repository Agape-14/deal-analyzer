# Rebuild implementation and release checks

The approved rebuild is implemented on draft PR #2. Existing source metrics, files, portfolio records and manual locks are retained. The draft has not been merged or deployed.

## User workflow

1. Upload the document package in Documents. Reading and review are owned by the server and continue after the browser closes.
2. Read Summary: one analysis revision supplies the accepted return values, capital and operating facts, and source coverage. Source checks, supported calculations and analyst decisions have distinct labels.
3. Open Questions for material missing evidence, source disagreements or failed reconciliation. Resolve related fields together or upload better evidence. Optional market context and investment cautions do not create confirmation chores.
4. Use Analysis for reported values, illustrative projections, location, source evidence and revision history. Preview existing data before saving a reviewed revision. Restore prior inputs explicitly as a new revision when necessary.

## Implemented behavior

| Area | Behavior |
| --- | --- |
| Typed facts | Explicit metric vocabulary and units; scenario, class, gross/net basis, debt phase, period and currency context. Unknown fields remain inspectable raw data and are excluded from accepted inputs and scoring. |
| Evidence | Source-checked facts need a uniquely identified current document and page or spreadsheet locator. Source hashes and document-package changes invalidate old checks. This validates traceability, not the truth of the provider's interpretation. |
| Returns | Yield/IRR and LTV/LTC remain distinct. Alternate scenarios and incompatible investor classes do not silently become the primary headline. Empty alternate scenarios do not change the strategy. |
| Calculations | Recompute LTC, yield-on-cost and DSCR from accepted compatible inputs; challenge conflicting reported ratios. Reconcile debt plus equity against project cost, with a documented tolerance of the greater of 1,000 currency units or 1% of cost. |
| Review | Group related material issues; preserve analyst values, reasons and locks. A later source challenge reopens the issue without overwriting the analyst's number. Correcting a field removes its conflicting dotted aliases. |
| Shared consumers | Cards, summary, comparison, comparison Excel, deal PDF, chat context and linked-investment defaults use the accepted analysis. Scores and illustrative projections consume accepted inputs. Source-citation rows use the same revision and states as Summary. |
| History | Immutable snapshot payloads plus retained source inputs, optimistic deal revisions, atomic grouped resolutions and history of removed fields. Stale saves return 409. Notes alone do not create new fact revisions. |
| Existing deals | Read-only preview and explicit adoption with both revision and input-hash checks. No bulk source rewrite. Restoration makes a new revision and rechecks current documents; deleted files are not resurrected. Older snapshots without retained inputs cannot be restored. |
| Durable jobs | Atomic upload-record/queue persistence, upload-burst coalescing, leases and heartbeats, conditional ownership checks at writes, bounded retries, cache reuse, restart recovery and one outcome notification per completed review request. |
| UI recovery | Explicit retry in Documents, location coordinates after failed address lookup, missing benchmarks treated as optional, and a secondary home-page pipeline summary. |

The migrations are additive: `c210925a001` adds analysis revisions, `c210925a002` adds durable jobs, and `c210925a003` adds restorable source inputs. Tests apply them twice to a legacy row and verify that the original metrics are unchanged.

## Verification

- Backend tests cover API journeys with real temporary SQLite databases, uploads, exports, soft deletion, nested edits, snapshots, adoption and restore, source removal, class/scenario separation, bounds, ratio/funding reconciliation, stale sessions, expired workers, retry limits and upload coalescing.
- An integrated queued review runs the real extraction/verification/scoring orchestration with controlled provider replies. Additional tests exercise correction/recheck boundaries and structured waterfall cash conservation.
- Frontend tests verify return selection, numeric formatting, comparison behavior and request failures. TypeScript checking and the Next.js production build run in CI.
- Browser checks use the actual production frontend build against a local synthetic API fixture: Summary, grouped resolution, refreshed accepted values, Documents, advanced tabs, unavailable projections, history, location recovery and a 390-pixel mobile layout. This is frontend validation, not a live-provider staging run.
- Original production inspection and feature coverage are recorded in `APP_REVIEW_2026-09-25.md`. The signed-in production app was inspected without changing its deal records or running paid analysis.

The exact final checks and revision are linked in the pull request. Local Python execution is unavailable on this Windows host; backend verification runs in GitHub Actions. Local TypeScript and production builds were also checked.

## Release requirements and remaining limits

Keep this as a draft until the following external validation is complete:

1. Run an authenticated staging journey with the actual provider: PDF and workbook upload, source review, correction, comparison/export, linked investment and distribution, failure/retry, session expiry and restart during a review. Exercise PostgreSQL as well if that is the deployment database; the automated database tests currently use SQLite.
2. Build a private, human-reviewed document evaluation set. Measure critical-field accuracy, citation accuracy, false acceptance, unresolved questions per deal, cost and latency across hold/sale alternatives, investor classes, construction/permanent debt, refinancing, missing fields, conflicting versions and scans. No accuracy percentage or zero-review guarantee is supported by the current tests.
3. Back up the database and original files, apply migrations in staging, preview changes on existing deals and inspect differences before production adoption. Application-level input restoration does not replace a database/file backup or a deployment rollback.

This is a deliberately bounded underwriting engine. It does not model every refinance, partial-year cash flow, IRR hurdle, catch-up provision, tax allocation or spreadsheet formula. The simple waterfall accepts explicitly mapped supported tiers and otherwise stays unavailable. Projections clearly state their assumptions. The old heuristic overall score remains gated and has not been calibrated as an investment recommendation. Optional source vocabulary can be expanded only with defined units, evidence rules and tests.

Source citations remain dependent on the quality of parsed documents and provider interpretation. Material ambiguity may require a newer document or an analyst decision. The rebuild removes repetitive coordination and confirmation work; it does not establish that every sponsor claim is correct.
