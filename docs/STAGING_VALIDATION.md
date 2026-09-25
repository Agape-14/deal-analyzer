# Private staging validation

Production data must stay outside this public repository and its Actions jobs. Automated tests use synthetic records only. A replay checks behavior and integrity; source-content accuracy still requires checking the originals.

## Create the copy

Run on a host with authorized read access to the SQLite database and originals. Use a new private destination on a separate staging volume. SQLite's backup API opens the source read-only and creates a consistent database copy. Files are checked against their byte hashes; missing or changing files fail the operation. Do not point staging at the live volume.

```sh
python scripts/staging_snapshot.py --database /data/deal_analyzer.db --uploads /data/uploads --destination /private-staging/review-copy
python scripts/replay_staging.py --snapshot /private-staging/review-copy
```

Output: unchanged `original.db`, working `deal_analyzer.db`, all referenced originals, verified manifest and `replay-report.json`. Only the working copy has file paths remapped and pending review jobs cancelled. Manual metrics, locks and history remain unchanged. No providers, credentials, deployments or production writes are involved. Do not commit the output or attach it to public CI.

When moving the package to another host, retain the same absolute destination path or explicitly remap the working database's document paths and DB_DIR/UPLOADS_DIR. Preserve the original backup unchanged.

## Validate staging

1. Set DB_DIR and UPLOADS_DIR to the private copy. Set `REVIEW_WORKERS_ENABLED=0` and `DEAL_REVIEW_AUTO_AFTER_UPLOAD=0`. Configure staging authentication before exposing a browser route.
2. Apply `alembic upgrade head` only to the copy. The document migration adds columns and leaves existing sources active; it does not delete or automatically supersede any files.
3. Open every analysis preview. Check accepted/withheld facts, document choices, grouped questions and model limitations against actual PDF pages or workbook cells. Explicitly adopt reviewed candidates. Confirm detail, cards, comparison, PDF and Excel agree.
4. After verifying isolation, enable workers in staging and configure the existing approved provider. Run one controlled review, then the remaining packages, recording usage and failures. Test duplicate uploads, version choices, retry, restart, manual locks, stale-save rejection, restore, linked investments and distributions.

## Expected behavior

- Identical uploads reuse the existing record without another review request. Existing duplicate copies remain stored and count once. Different contents with the same filename are flagged and remain separate.
- Exact source IDs take precedence over names. Same-name citations to different file contents remain ambiguous. Byte-identical matches count as one source.
- Supporting amendments stay active. Whole-document replacement is explicit, revision-checked and reversible. Alternate scenarios are retained and excluded from primary review. Cross-deal references, replacement chains and cycles are rejected.
- Source changes invalidate old source checks; manual decisions, locks and reasons remain intact.
- Partial-year sale projections prorate operations and interest, annualize NOI at exit and use actual modeled times for IRR. Investor calculations require a valid amount and withhold unsupported waterfalls and additional capital calls.
- Refinancing, construction/lease-up debt and amortization require dated schedules. Multiple classes, catch-up, compounding and IRR hurdles require a fuller waterfall model. They return clear unavailable messages. Restrictions survive removal of unsupported raw fields from accepted numerical inputs. Hold strategies cannot silently use a sale forecast.

## Completion evidence

Keep the staging commit, database hash, document manifest, all-deal replay, source corrections, provider runs, export comparisons and recovery checks in private storage. Mark each deal passed only after checking its material accepted values against its originals. CI alone does not establish all-deal accuracy or justify production deployment.
