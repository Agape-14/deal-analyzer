# Reviewed workflow

Start a deal by uploading up to ten PDF, Excel or CSV documents. The first filename supplies a temporary title when no name is entered. Explicit, unambiguous project, sponsor, city, state and property-type labels can fill details automatically. Conflicting labels and unsupported details stay visible; user edits take precedence. Retry uses the same request id and reuses identical files.

Summary shows accepted facts, evidence coverage and the next material questions. Unresolved capital terms are collapsed. Questions groups related issues into decisions. Documents retains the originals and allows explicit active, alternative and superseded source choices. Analysis contains editable deal details, reported metrics, optional projections and history.

The evidence assistant renders financial statements from current accepted facts and canonical headline returns. It uses no language-model provider, never takes financial claims from conversation history, preserves known class/basis/scenario/phase/period labels and links source documents. Earlier replies are retained as collapsed archived answers when their analysis revision changes. It is a factual lookup and explanation tool, not an open-ended investment recommendation generator.

Comparison defaults to Values. Return rows include their context. Winners, Deltas and Normalized fall back to values when class, scenario, unit, basis or period is unknown or different, or phase/currency differs. No overall investment winner is calculated. The legacy screen is retired; its browser route redirects to the current application and its API-side HTML endpoint returns 410.

Portfolio positions can be created, edited, given distributions, marked exited and restored through Undo after a soft delete. Edits to a position describe the investor's own record; they do not change the deal's reviewed facts.

## Accuracy benchmark

Run `python scripts/evaluate_analysis.py --output analysis-benchmark.json`. The versioned fixtures cover hold yield versus exit returns, current source locators, wrong values, conflicting aliases and stale sources. The report records false acceptance, missed expected acceptance and headline errors. CI requires these fixed cases to pass. This is a synthetic regression benchmark and does not establish live extraction accuracy. Private evaluations and real documents must stay outside the public repository and CI.

Automatic financial extraction and source review still require provider availability. The assistant works without it. External workbook links, missing formula caches, incomplete OCR and unsupported refinance/class models remain explicit limitations. They are not silently filled with assumptions. Production deployment requires separate authorization.
