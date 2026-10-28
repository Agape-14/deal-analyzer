# Release validation — October 28, 2026

The draft branch contains the current implementation. Production deployment is a
separate approval and has not been performed. Record the final reviewed commit
and successful regression run in the PR before release; diagnostics exposes the
running frontend and backend commits so a stale service can be identified.

## Release gates

1. Full backend tests, frontend unit tests, production build, production and
   development browser journeys, including repeated saved-deal reloads.
2. Reviewed dependency locks. Python targets Linux/Python 3.12. The Dependency
   candidate workflow produces a candidate lock for review, without changing
   the accepted lock or deploying anything. Run full regression tests for updates.
   `.python-version` and Nixpacks now select Python 3.12 to match CI. Verify the
   runtime selection in the approved staging build before production rollout.
   The frontend `.nvmrc` selects Node 22, matching its CI runtime.
3. A current, verified backup and a private staging copy. Apply additive Alembic
   migrations through `c211028a007`; verify counts, document hashes, saved
   analyses, manual locks, distributions and stable sponsor associations.
   The migration does not rewrite investment amounts or accepted financial facts.
4. Replay every saved deal on the private copy. Compare Summary, Questions,
   comparison, Assistant and exports. Keep financial files and replay evidence
   outside this public repository and public CI artifacts.
5. Two pending provider extraction/verification retests require usable credits.
   Configuration health alone does not establish credits or semantic correctness.
6. Separately authorize a coordinated backend/frontend release. Verify both
   commit identities, authenticated PDF preview, upload/reading/review status,
   and rollback using the actual backup before treating production as updated.

## Portfolio definitions

Cash returned includes all recorded distributions plus exit proceeds not already
recorded as `sale_proceeds` or `exit_proceeds`. Exit amount means total exit
proceeds inclusive of those payments. DPI is cash returned / invested capital.
The existing `multiple` API field is this cash measure for compatibility.

TVPI adds a dated residual value, excluding distributions already received.
An active position with no valid residual value has no TVPI or total-value IRR.
Portfolio total-value measures require aligned active valuation dates and no cash
flows after that date. Exited positions have zero residual value and need complete
dated flows for IRR. Active interim IRR is not compared with a projected exit IRR.
Charts and the cash balance exclude residual value. Realized performer lists
contain exited positions only.

## Accuracy labels beyond the synthetic benchmark

`scripts/evaluate_analysis.py` checks false acceptance, missing required facts,
headline values, fact values, context and source locators independently.
`--reviewed-real` requires approved reviewer/date/source-hash attestations and
expected value/context/evidence labels for accepted facts. It evaluates saved
analysis inputs; it does not certify a fresh extraction or prove that someone
actually performed the attested review.

Create private cases independently from source documents. Cover clean PDF,
scanned/OCR PDF, missing pages, workbook formulas and external dependencies,
duplicate/superseded sources, conflicting classes, debt phases, liquidity/fees,
and missing currency or period. For each case, record source hashes, exact
page/sheet/cell/quote, required facts and deliberately unsupported claims. Have
an analyst review the expected labels before using a passing score as an accuracy
claim. Do not derive expected labels from the output being tested.

The current five-case public benchmark is synthetic. A reviewed real-source
label set and fresh paid extraction runs remain release gates; a green synthetic
suite is not a substitute.

## External context

The Census adapter returns ACS five-year population and median-household-income
estimates with geography, measured period, uncertainty, retrieval time and direct
source query. Negative Census sentinels are withheld. Publication dates are
explicitly unavailable when the adapter does not supply them. It uses the first
available vintage in a bounded year range and makes no claim to cover every
unincorporated area. Asset-specific property rent, vacancy, supply and forecasts
remain unavailable until matched evidence is supplied. HUD FMR is gross-rent
context, never a project rent-quality verdict.

Sources: [Census ACS API](https://www.census.gov/programs-surveys/acs/data/data-via-api.html),
[population variable](https://api.census.gov/data/2024/acs/acs5/variables/B01003_001E.json),
[income variable](https://api.census.gov/data/2024/acs/acs5/variables/B19013_001E.json),
[HUD FMR](https://www.huduser.gov/portal/datasets/fmr.html).
