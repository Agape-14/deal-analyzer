# Deal Analyzer: usability, correctness and rebuild review

Review date: 2026-09-25. Draft changes: https://github.com/Agape-14/deal-analyzer/pull/2

## Recommendation

Keep the Next.js/FastAPI application, authentication, document storage, portfolio ledger and working screens. Rebuild the facts and review engine in stages. Cosmetic simplification alone cannot resolve the current disagreements.

The product should require three actions: upload the package, read a coherent summary, and answer only questions the documents cannot resolve. Automatic processing after upload already exists and should be retained.

A promise of zero manual checks would be misleading. Different document versions, equity classes, debt phases and contradictory sponsor statements can require a person or a newer source. The achievable objective is to eliminate routine reconciliation work and make genuine exceptions short and explicit.

## What was inspected and tested

The initial local working tree was inspected before changes. Prior comparison/timeout work was retained. The published branch was checked against local source; relevant differences were line endings and an existing text-encoding issue, not missing implementation. Changes are on an isolated draft branch, not production.

Live browser checks used the signed-in application and existing records. Production data was not edited, re-extracted, scored, deleted or submitted to a new AI conversation. The observed records and source documents are intentionally not reproduced in this repository report.

| Feature | Live inspection | Automated verification |
| --- | --- | --- |
| Dashboard and deal navigation | Loaded, reviewed cards, scores and attention states; checked text/status filters, empty state and alphabetical sorting | CRUD, list/detail and pipeline summary |
| Login and role-dependent controls | New Deal initially did nothing after sign-in; reload restored it | Existing authentication tests; build validation for navigation fix |
| Search and help | Search found a deal; command palette and help opened | Build/type checks |
| Deal summary and evidence | Inspected headline metrics, review queue and source drawer | Canonical selection, rejected values, field locks, nested edits |
| Metrics view | Observed DSCR as percent and loan duration as currency | Numeric formatting behavior checks |
| Documents | Listed PDF/workbook sources; PDF iframe refused connection | PDF upload; CSV upload, original download, reprocess/delete; frame headers |
| Comparison | Selected two deals, exercised values/deltas/normalized; reproduced header/table disagreement | Ordering, missing/deleted/duplicate IDs, canonical table paths, timeouts, Excel values |
| Cash flow | Loaded chart and annual table; observed fractional hold shortened | Missing/disputed-input gating, invested equity, annual IRR timing, fractional-hold protection |
| Waterfall | Loaded live output; static audit found invented splits and return assumptions | Missing-terms withholding and explicit-term cash conservation |
| Developers | Directory and sponsor profile loaded | CRUD and soft deletion tests |
| Portfolio | Empty state, manual form and existing-deal selection opened | Linked investment with sponsor, distributions, analytics, reports |
| Exports | Export controls and routes inspected | Deal PDF text, comparison workbook values, portfolio Excel/PDF, JSON and CSV archive |
| Notifications | Loaded history; excessive intermediate events evident | Upload event count and mark-read behavior |
| Location | Observed geocoding failure with no useful placement recovery in that state | Manual-coordinate validation/persistence |
| Analyst chat | Existing history and input inspected; historical answers changed interpretation | History read/delete. New paid AI answers were not tested |
| AI extraction/review | Pipeline and evidence code reviewed; existing results inspected | Bounded correction recheck with controlled provider responses; failure behavior |
| Trash, purge, session expiry, theme, mobile, legacy UI | No destructive production or exhaustive browser exercises | Existing soft-delete/auth tests cover some paths; remaining browser work listed below |

This is not certification of every feature or every extracted fact. Actual AI accuracy, map providers, OCR on difficult real files and all browser/device combinations still require the release checks below.

## Confirmed defects addressed in this draft

1. Extraction post-processing replaced hold IRR with cash yield/preferred return, overwrote source leverage, switched debt phases, and inferred DSCR from interest-only debt. It now preserves source values and only derives unambiguous missing metrics with dependencies. Debt divided by cost is explicitly LTC.
2. Canonical selection fell back to a rejected value if no clean candidate remained. Such values now remain unavailable. Hold summaries no longer borrow the sale scenario's multiple.
3. API normalization, headline helpers, comparison rows, linked investments and PDF exports selected returns differently. Their headline fields now use the backend canonical result, including deliberate nulls. The raw Metrics view no longer silently renames net IRR as target IRR.
4. Automatic corrections ignored locks and wrote dotted nested fields as literal keys. Locks now protect nested values as well as parent replacements; nested edits preserve scenario descriptions. Missing-data filling preserves explicit zeros and proposals require a source reference.
5. A corrected value inherited the original wrong verdict. Changed sections now receive one additional source check. A second disagreement stays unresolved; provider failure stops the pipeline. This adds a bounded provider call for changed sections.
6. Provisional scores appeared as prominent headline scores. Headline rings now require a passing quality gate; provisional detail remains available separately.
7. Investment risks were presented as data-cleanup chores. They are now grouped as informational cautions. Marking a question Unsure preserves the unresolved state, including legacy unsure entries.
8. Comparison requests could silently compare partial sets or include deleted deals. They now require distinct available deals, preserve selected order, and provide a clear error. Prior timeout/cancellation/retry improvements remain.
9. Excel export highlighted high leverage/costs as winners. Automatic best/worst colors are restricted to scores.
10. Cash-flow projections invented missing inputs, double-discounted investor ownership, omitted initial capital in the project chart and approximated IRR from a multiple. Missing/disputed inputs are withheld, ownership is not discounted twice, invested capital is included, and conventional annual cash flows use an actual IRR root. Partial-year holds are explicitly unsupported rather than shortened.
11. Waterfall projection invented default tiers, equity and multiples, overstated individual preferred distributions and double-counted hurdle intervals with three or more tiers. These calculations are corrected. It now requires explicit structured terms, project profit, simple annual hurdles and pro-rata preferences. IRR hurdles and unsupported terms show an explanation instead of fabricated distributions. The supported simplified model is labeled illustrative.
12. PDF previews were blocked by the application's own frame headers. Same-origin embedding is permitted only for authenticated document-file routes; ordinary pages retain frame denial.
13. DSCR and duration units were wrong in the Metrics display. Formatting now distinguishes multiples, months/years, percentages and currency.
14. The integrity popover sent section/field payloads to endpoints that require path. Revert and lock actions now use the API contract.
15. Root-level client components retained the anonymous login state. Successful login now performs a full navigation so creation/search controls load the new session.
16. Linking a deal to an investment could trigger asynchronous lazy loading of the sponsor. The sponsor is now eagerly loaded; unavailable deals are rejected and accepted returns are reused.
17. Quality counters counted calculated fields as verified and skipped the calculated bucket. Categories now match their test contract. Routine extraction-complete notifications no longer duplicate the upload notice.
18. A frontend test asserted source-code whitespace instead of behavior. It was replaced with executable return-selection tests.

Existing stored records are not migrated by these changes. Previously polluted fields, stale dotted aliases and scenario assignments need a controlled reanalysis against their documents, preserving manual locks.

## Why a deeper rebuild is needed

### One fact needs a complete identity

A plain field named target_irr is insufficient. A value needs a metric, unit, scenario, equity class, gross/net basis, debt phase and time period. Otherwise two correct source figures can be mistaken for a contradiction.

Introduce a typed fact record:

- Identity: metric, scenario, investor class, basis, phase and period.
- Value and unit: numeric value distinct from percentages, multiples, currency, dates and durations.
- Evidence: document content hash/version, PDF page or workbook sheet/cell range, and source excerpt.
- State: reported, independently checked, calculated from checked dependencies, disputed, missing or manually resolved.
- History: prior value, reason for replacement, actor and analysis-run ID.

Unknown keys from AI responses should be retained as unclassified evidence, not silently become scoring inputs. Normalize nested versus dotted shapes at ingestion and reject ambiguous aliases.

### One result should serve every screen

Produce an immutable accepted analysis snapshot. Cards, detail pages, comparison, exports, chat and portfolio defaults should consume that same snapshot. Preserve alternate scenarios explicitly. Withheld values must remain withheld throughout the application.

Separate three questions in the UI:

- What does the sponsor report?
- What does the app calculate under explicit assumptions?
- What is supported well enough to use?

A model confirming a number is not proof of investment quality. Remove uncalibrated confidence percentages from prominent decision UI; show evidence coverage and specific unresolved issues instead.

### Automatic checking should resolve exceptions

1. Parse text, tables and spreadsheet cells, preserving cell references and formula/cached-value availability.
2. Validate schema, units, currency, class and scenario before accepting extracted candidates.
3. Run deterministic checks using compatible inputs: sources/uses, unit totals, actual debt service, cash-flow timing and distributions.
4. Check material facts against cited evidence. Never apply an overall model confidence score to every individual field.
5. Automatically recheck changes once, then either accept supported results or create a question.
6. Group remaining questions by cause. A debt-phase ambiguity should generate one question with its affected outputs, not ten field confirmations.
7. Separate missing optional context and economic cautions from blockers. Make score coverage strategy/property-specific before relaxing existing score gates.
8. Recompute dependent values whenever an input changes. Previously accepted scores must be marked outdated until their dependencies have been reevaluated.

### The pipeline needs durable jobs

Current in-process asyncio jobs do not survive a process restart, and overlapping document/field writes can race. Add persisted analysis runs with document fingerprints, queued steps, heartbeat, retries, cancellation and resumable checkpoints.

Use optimistic revision checks when accepting a result. If documents or manual facts changed during a run, queue the new revision rather than publishing the older result over it. An upload burst should produce one run and one outcome notification. Review completion must distinguish ready, questions remain, unsupported model and failed.

## Proposed product structure

- **Summary:** strategy and investor class first; accepted return metrics, capital/debt summary, key risks, source coverage and last-reviewed document revision. Avoid pipeline-velocity widgets as the main screen for a small deal book.
- **Questions:** only material unresolved facts. Each question shows competing evidence, impact and the shortest available resolution. Optional facts stay in source details. An Unsure choice records uncertainty without pretending to resolve it.
- **Documents:** upload multiple files directly, show reading progress, page/cell evidence and version history. Create/populate the deal from the documents when possible.
- Put detailed metrics, hypothetical scenarios, math logs and technical diagnostics under a secondary Analysis view.
- Compare should default to a small set of accepted, comparable values. Show scenario/class/time period beside returns; do not award an overall winner across incomparable or incomplete deals.
- Portfolio should keep the existing link-to-deal workflow. Investor contribution, actual date and actual distributions are legitimate manual inputs unless an authorized transaction source is connected.
- Chat should answer from accepted facts, cite evidence and clearly distinguish unresolved alternatives. It should not silently create another version of the numbers.

## Delivery sequence and acceptance criteria

### Stage 1 — correctness patch (this draft)

Complete CI and review the patch. It is intentionally not deployed or merged. Projections may become unavailable where the former version invented assumptions; this is an expected behavior change.

Before release, test the draft build in an authenticated staging environment: sign in, create a synthetic deal, upload PDF and workbook, inspect PDF preview, run extraction/recheck, resolve a nested field, compare/export, link an investment and record a distribution. Verify provider failure, retry, timeout and logout/expiry.

### Stage 2 — accepted facts and question engine

Add typed facts and additive database migrations. Keep the current metrics JSON as a compatibility output while moving all consumers to a versioned analysis snapshot. Implement scenario/class-aware checks, dependency invalidation and material-question grouping.

Create a private evaluation set of representative offering documents and spreadsheets with human-reviewed answers and evidence. Include hold/sale alternatives, multiple investor classes, construction/permanent debt, refinancings, zero values, missing fields, conflicting versions and scanned tables.

Required gates:
- No cash-yield/IRR or LTV/LTC substitution.
- No unsupported invented source facts.
- Every headline fact has a source or inspectable dependency formula.
- All display/export consumers agree for the same snapshot.
- Locks survive re-extraction, verification and nested replacements.
- Ambiguous cases stay unresolved instead of becoming false passes.
- Track critical-field accuracy, source accuracy, false acceptance, questions per deal, run cost and latency. Set the automation target after measuring the private evaluation set; do not invent an accuracy percentage.

### Stage 3 — simplify the workflow and harden release

Ship the Summary/Questions/Documents flow over the new engine. Add durable jobs, automatic retries and explicit stale-data states. Migrate each existing deal in a preview run and show differences before accepting changed facts. Preserve manual decisions and complete rollback by snapshot ID.

Repair map failure recovery and remove setup-variable instructions from normal user screens. Add useful spreadsheet cell previews, consistent numeric precision, accessible mobile controls, shared session state and session-aware search caches.

Validate full browser journeys and failure paths against staging, then recheck the representative private document set. Keep the draft branch until the staged behavior is reviewable.

## Test results

Initial production-code baseline: 65 backend tests passed and 4 failed. The final functional revision passed **99 backend tests, 23 frontend tests and the Next.js production build** ([CI run](https://github.com/Agape-14/deal-analyzer/actions/runs/36159631901), commit `784bde5`). Subsequent cleanup only restores existing line endings and updates this report. All checks are also available on the draft pull request.

The provider-boundary correction tests use controlled replies. They verify orchestration, locking and failure handling, not the factual accuracy of an AI provider. No claim of zero manual review or complete extraction accuracy is made.
