import type { ContextRuntime } from './types';

export type StatisticsRequest = {
  since: string;
  until: string;
  timezone: string;
  history: 'active' | 'all';
  model?: string;
  session_gap_minutes: number;
  top_limit?: number;
  all_time?: boolean;
};

export type StatisticsPayload = {
  schema: 'codex-usage-tracker.dashboard-statistics.v1';
  data_state: 'ready' | 'refresh_required';
  reason: string | null;
  scope: Record<string, unknown>;
  coverage?: {
    total_call_count: number;
    priced_call_count: number;
    priced_call_ratio: number;
    known_usage_credits: number;
  };
  headline?: Record<string, number | null>;
  distribution?: Record<string, number | null>;
  time_rates?: Record<string, number | null>;
  model_rows?: Array<Record<string, number | string | null>>;
  series?: { granularity: string; points: Array<Record<string, number | string | null>> };
  heatmap?: Array<{ weekday: number; hour: number; calls: number; known_credits: number }>;
  sessions?: { count: number; rows: Array<Record<string, unknown>> };
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
    usage_credits: number;
    usage_credit_confidence: string;
    total_tokens: number;
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
