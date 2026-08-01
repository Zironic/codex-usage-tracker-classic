export type AllowancePlanComparisonStatus =
  | 'no_transition'
  | 'insufficient_completed_cycles'
  | 'descriptive_only'
  | 'supported_smaller'
  | 'supported_larger'
  | 'no_supported_difference';

export type AllowancePlanTransition = {
  selection_mode: 'auto' | 'explicit';
  from_plan: string | null;
  to_plan: string | null;
  observed_plan_types?: string[];
  before_run_start_date?: string | null;
  before_run_end_date?: string | null;
  after_run_start_date?: string | null;
  after_run_end_date?: string | null;
  boundary_cycle_count?: number;
  boundary_plan_types?: string[];
};

export type AllowancePlanCohortSummary = {
  plan_type: string;
  observed_cycle_count: number;
  eligible_cycle_count: number;
  start_date: string | null;
  end_date: string | null;
  median_credits_per_percent: number | null;
  estimated_full_meter_credits: number | null;
  q1_credits_per_percent: number | null;
  q3_credits_per_percent: number | null;
  minimum_credits_per_percent: number | null;
  maximum_credits_per_percent: number | null;
  median_price_coverage: number | null;
};

export type AllowanceMeterRelativeSize = {
  after_to_before_ratio: number | null;
  after_as_percent_of_before: number | null;
  before_to_after_multiplier: number | null;
  relative_change_percent: number | null;
};

export type AllowancePlanComparisonStatistics = {
  ratio_confidence_interval_95: {
    method: string;
    low: number | null;
    high: number | null;
    samples: number;
    seed: number;
  } | null;
  permutation: {
    method: string;
    two_sided_p_value: number | null;
    one_sided_p_value_after_smaller: number | null;
    assignments_evaluated: number;
    seed: number | null;
    monte_carlo_uncertainty: Record<string, unknown> | null;
  } | null;
  cliffs_delta_after_vs_before: number | null;
};

export type AllowanceEarlyIntervalEstimate = {
  status: string;
  before_interval_count: number;
  after_interval_count: number;
  before_median_credits_per_percent: number | null;
  after_median_credits_per_percent: number | null;
  after_to_before_ratio: number | null;
  after_as_percent_of_before?: number | null;
  token_mix: {
    before: Record<string, number> | null;
    after: Record<string, number> | null;
  };
  interpretation?: string;
};

export type AllowancePlanComparison = {
  status: AllowancePlanComparisonStatus;
  model_version: string;
  transition: AllowancePlanTransition;
  before: AllowancePlanCohortSummary | null;
  after: AllowancePlanCohortSummary | null;
  relative_meter_size: AllowanceMeterRelativeSize;
  statistics: AllowancePlanComparisonStatistics;
  early_interval_estimate: AllowanceEarlyIntervalEstimate;
  exclusions: Record<string, unknown>;
  caveats: string[];
};
