import type { ContextRuntime } from './types';

export type StatisticsRequest = {
  since: string;
  until: string;
  timezone: string;
  history: 'active' | 'all';
  model?: string;
  session_gap_minutes: number;
  active_gap_cap_minutes: number;
  comparison_at?: string;
  top_limit?: number;
  all_time?: boolean;
};

export type StatisticsSeriesPoint = {
  period_start: string;
  local_period_start?: string;
  calls: number;
  known_credits: number;
  active_minutes: number;
  rolling_7d_credits?: number;
  rolling_30d_credits?: number;
};

export type StatisticsSeries = {
  granularity: 'day' | 'hour';
  timezone?: string;
  points: StatisticsSeriesPoint[];
};

export type StatisticsMixRow = {
  label: string;
  calls: number;
  share: number | null;
};

export type StatisticsGroupRow = {
  label: string;
  calls: number;
  call_share: number | null;
  total_tokens: number;
  tokens_per_call: number | null;
  known_credits: number;
  priced_calls: number;
  priced_call_ratio: number | null;
  credit_share: number | null;
  active_minutes: number;
  active_time_share: number | null;
  turns: number;
  calls_per_turn: number | null;
  credits_per_turn: number | null;
  credits_per_active_hour: number | null;
  subagent_calls: number;
  subagent_calls_per_turn: number | null;
  model_mix?: StatisticsMixRow[];
  effort_mix?: StatisticsMixRow[];
  project?: string;
  thread?: string;
};

export type StatisticsCohortRow = StatisticsGroupRow & {
  plan: string | null;
  rate_revision: string | null;
  since: string;
  until: string;
  elapsed_days: number;
  calls_per_day: number | null;
  active_minutes_per_day: number | null;
  turns_per_day: number | null;
  credits_per_day: number | null;
  credits_per_call: number | null;
  primary_meter_burn_percent_per_day: number | null;
  secondary_meter_burn_percent_per_day: number | null;
};

export type StatisticsWorkPeriod = {
  start_at: string;
  end_at: string;
  duration_seconds: number;
  active_seconds: number;
  active_minutes: number;
  calls: number;
  turns: number;
  known_credits: number;
  priced_calls: number;
  credits_per_active_hour: number | null;
  models: string[];
  subagent_calls: number;
  model_switches: number;
};

export type StatisticsActivity = {
  estimated_active_seconds: number;
  estimated_active_minutes: number;
  estimated_active_hours: number;
  measured_call_duration_seconds: number;
  capped_inter_call_gap_seconds: number;
  distinct_turns: number;
  calls_per_turn: number | null;
  credits_per_turn: number | null;
  subagent_calls: number;
  subagent_calls_per_turn: number | null;
  calls_per_active_hour: number | null;
  credits_per_active_hour: number | null;
  median_session_duration_seconds: number | null;
  p75_session_duration_seconds: number | null;
  p90_session_duration_seconds: number | null;
  longest_work_periods: StatisticsWorkPeriod[];
  most_active_turns: Array<Record<string, unknown>>;
};

export type StatisticsModelRow = {
  model: string;
  calls: number;
  call_share: number | null;
  priced_calls: number;
  priced_call_ratio: number | null;
  known_credits: number;
  credit_share: number | null;
  mean: number | null;
  median: number | null;
  p75: number | null;
  p90: number | null;
  p95: number | null;
  minimum: number | null;
  maximum: number | null;
  population_standard_deviation: number | null;
  active_days: number;
  active_hour_buckets: number;
  total_tokens: number;
  input_tokens: number;
  cached_input_tokens: number;
  uncached_input_tokens: number;
  output_tokens: number;
  reasoning_output_tokens: number;
  avg_total_tokens_per_call: number | null;
  avg_input_tokens_per_call: number | null;
  avg_cached_input_tokens_per_call: number | null;
  avg_uncached_input_tokens_per_call: number | null;
  avg_output_tokens_per_call: number | null;
  avg_reasoning_tokens_per_call: number | null;
  weighted_cache_ratio: number | null;
  output_ratio: number | null;
  reasoning_output_ratio: number | null;
  average_context_window_percent: number | null;
  credits_per_million_total_tokens: number | null;
};

export type StatisticsPayload = {
  schema: 'codex-usage-tracker.dashboard-statistics.v1';
  data_state: 'ready' | 'refresh_required';
  reason: string | null;
  scope: Record<string, unknown>;
  coverage?: {
    total_call_count: number;
    priced_call_count: number;
    unpriced_call_count: number;
    priced_call_ratio: number;
    known_usage_credits: number;
  };
  headline?: Record<string, number | null>;
  distribution?: Record<string, number | null>;
  time_rates?: Record<string, number | null>;
  activity?: StatisticsActivity;
  model_rows?: StatisticsModelRow[];
  series?: StatisticsSeries;
  hourly_series?: StatisticsSeries | null;
  heatmap?: Array<{
    weekday: number;
    hour: number;
    calls: number;
    known_credits: number;
    active_minutes: number;
  }>;
  sessions?: {
    count: number;
    duration_distribution: Record<string, number | null>;
    active_duration_distribution: Record<string, number | null>;
    rows: StatisticsWorkPeriod[];
  };
  turns?: {
    count: number;
    calls_per_turn: number | null;
    credits_per_turn: number | null;
    subagent_calls_per_turn: number | null;
    rows: Array<Record<string, unknown>>;
  };
  breakdowns?: Record<string, StatisticsGroupRow[]>;
  attribution?: {
    projects: StatisticsGroupRow[];
    threads: StatisticsGroupRow[];
    concentration: Record<string, number | null>;
  };
  cohorts?: {
    comparison_at: string | null;
    plan_rate_rows: StatisticsCohortRow[];
    breakpoint_rows: StatisticsCohortRow[];
  };
  concentration?: Record<string, number | null>;
  model_transitions?: {
    switch_count: number;
    switches_per_100_calls: number | null;
    rows: Array<{ from_model: string; to_model: string; count: number }>;
  };
  top_calls?: Array<{
    record_id: string;
    event_timestamp: string;
    model: string;
    effort: string;
    initiator_kind: string;
    project: string;
    thread: string;
    usage_credits: number;
    usage_credit_confidence: string;
    total_tokens: number;
    duration_seconds: number;
    active_seconds: number;
    reasoning_output_tokens: number;
    cache_ratio: number | null;
    context_window_percent: number | null;
  }>;
};

export async function loadUsageStatistics(
  runtime: ContextRuntime,
  request: StatisticsRequest,
  signal?: AbortSignal,
): Promise<StatisticsPayload> {
  if (runtime.fileMode || !runtime.apiToken) {
    throw new Error('Usage statistics require the localhost dashboard server.');
  }
  const response = await fetch('/api/v2/statistics', {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-Codex-Usage-Token': runtime.apiToken,
    },
    body: JSON.stringify(request),
    cache: 'no-store',
    signal,
  });
  const payload = await response.json() as Record<string, unknown>;
  if (!response.ok) {
    const error = payload.error as Record<string, unknown> | undefined;
    throw new Error(typeof error?.message === 'string'
      ? error.message
      : `Usage statistics failed with HTTP ${response.status}.`);
  }
  if (payload.schema !== 'codex-usage-tracker.dashboard-statistics.v1') {
    throw new Error('Usage statistics returned an unsupported schema.');
  }
  return payload as StatisticsPayload;
}
