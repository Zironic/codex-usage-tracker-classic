# Plan-switch weekly meter comparison

The plan comparison answers a fixed question: how large is the weekly Codex meter after an observed subscription-plan transition relative to the meter before it?

## Primary estimate

The primary result gives each eligible completed weekly reset cycle one vote. For the contiguous plan runs immediately before and after the selected transition, the tracker computes the median model-normalized credits consumed per visible percentage point. The reported ratio is:

```text
after_to_before_ratio = median(after credits per %) / median(before credits per %)
```

A ratio of `0.50` means the post-switch weekly meter appears to contain about half as much equivalently weighted local usage as the pre-switch meter. Multiplying either median by 100 produces a convenient whole-meter credit estimate, but the ratio is the authoritative result.

## Cohort and boundary rules

Automatic selection uses the latest contiguous transition between two known plan labels. `--from-plan` and `--to-plan` select the latest matching transition explicitly. Historical runs outside those two adjacent cohorts are not pooled into the result.

Cycles marked `mixed` or `unknown` at the transition boundary belong to neither cohort. Completed-cycle votes also require medium or high quality, at least 95% pricing coverage, no conflicts, and a positive finite credits-per-percent estimate.

## Statistical evidence

The tracker reports a deterministic bootstrap confidence interval for the ratio, a fixed-label permutation test, and Cliff's delta. Unlike the within-plan change detector, the plan boundary is supplied by telemetry rather than selected by searching for the most favorable split.

A result is labelled `supported_smaller` only when both cohorts contain at least four eligible completed cycles, the 95% ratio interval is entirely below 1, the two-sided permutation p-value is below 0.05, and the absolute Cliff's delta is at least 0.474. Equivalent rules apply to `supported_larger`.

## Early interval estimate

Positive allowance intervals inside the selected plan runs provide an exploratory estimate while completed post-switch cycles accumulate. This estimate is displayed separately and is never treated as a set of independent cycle observations for the primary significance claim.

## Limitations

The comparison normalizes local Codex calls using published model-specific input, cached-input, output, and Fast-tier credit weights. It assumes those weights are proportional to the hidden weekly-meter accounting. Usage from another device or surface, unpriced models, meter rounding, or a substantial change in missing local activity can bias the result.

The result therefore means: based on locally visible, model-normalized Codex usage, the post-switch weekly meter is estimated at a stated percentage of the pre-switch meter. It is not an official OpenAI allowance or billing ledger.
