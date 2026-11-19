# Production release and validation

Deal Analyzer runs on the web and API services in Railway production. Use
Diagnostics to confirm that both services run the approved commit. The previous
verified release, `52bd533b`, passed the backend, frontend and two browser
suites in [run 44617841521](https://github.com/Agape-14/deal-analyzer/actions/runs/44617841521).
Its live release check covered the dashboard, Summary, Compare, four deal PDFs
and the Excel comparison with the four saved deals.

## Release gates

Codex is the primary review workflow. Production paid fallback qualification
requires representative PDF-only and PDF-plus-workbook runs using authorized
credits, independently checked evidence, measured costs, and retry checks.
The paid review pause leaves document reading and evidence lookup available.

1. Wait for the **Release gate** on the exact commit. It depends on the backend,
   frontend build, and production and development browser jobs. Pin both
   services to that tested commit and inspect the staged changes.
2. Reviewed dependency locks. Python targets Linux/Python 3.12. The Dependency
   candidate workflow produces a candidate lock for review, without changing
   the accepted lock or deploying anything. Run full regression tests for updates.
   `.python-version` and Nixpacks now select Python 3.12 to match CI. Verify the
   runtime selection in the approved staging build before production rollout.
   The frontend `.nvmrc` selects Node 22, matching its CI runtime.
3. Confirm the most recent independent backup and retention schedule. Rehearse
   recovery of the database and originals in isolation. A bounded, in-service
   rehearsal verifies a temporary copy and replay. It does not verify the
   backup provider's schedule or restore point. Apply candidate migrations to
   a private copy first and verify counts, document hashes, saved
   analyses, manual locks, distributions and stable sponsor associations.
   The migration does not rewrite investment amounts or accepted financial facts.
4. Replay every saved deal on the private copy. Compare Summary, Questions,
   comparison, Assistant and exports. Keep financial files and replay evidence
   outside this public repository and public CI artifacts.
5. Verify both service commit identities and run the read-only source replay
   verification against the production records. It compares dashboard,
   Summary and Compare with their PDF and Excel output. Keep the source
   scope and data inside the service and clear the temporary replay selection.
6. Check a signed-in analyst and read-only viewer on the deployed domain.
   Railway uses `/api/healthz/ready` to gate deployment. The admin readiness
   view checks database schema, storage and review queue health. Confirm the
   uptime and backup alerts reach the designated recipient.

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

The public benchmark uses synthetic source labels. Keep the existing real
deal source reviews and independently checked figures in private storage.
Record which reviewed values, source locators, and export contexts a real-deal
replay covered. Qualify fresh provider extraction separately when enabling it.

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
