import type { ContextRuntime } from './types';

export type DelegationPeriod = {
  calls: number;
  turns: number;
  calls_per_turn: number | null;
  exact_turn_calls: number;
  fallback_turn_calls: number;
  first_event: string | null;
  last_event: string | null;
  tokens_per_turn: number | null;
  uncached_input_tokens_per_turn: number | null;
  output_tokens_per_turn: number | null;
};

export type DelegationHistoricalComparison = {
  adoption_at: string | null;
  adoption_role: string | null;
  adoption_source: string;
  direct_model: string;
  before: DelegationPeriod;
  after: DelegationPeriod;
  absolute_delta: number | null;
  percent_delta: number | null;
  direction: 'decreased' | 'increased' | 'unchanged' | 'unavailable';
  interpretation: string;
};

type AgentResponse = {
  result?: {
    schema?: string;
    historical_comparison?: DelegationHistoricalComparison;
  };
  error?: { message?: string };
};

export async function loadDelegationEfficiency(
  contextRuntime: ContextRuntime,
  options: { since?: string | null; includeArchived?: boolean; signal?: AbortSignal },
): Promise<DelegationHistoricalComparison> {
  if (contextRuntime.fileMode || !contextRuntime.apiToken) {
    throw new Error('Luna comparison requires the live localhost dashboard.');
  }
  const argumentsPayload: Record<string, unknown> = {
    include_archived: Boolean(options.includeArchived),
  };
  if (options.since) argumentsPayload.since = options.since;
  const response = await fetch('/api/v2/agent', {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-Codex-Usage-Token': contextRuntime.apiToken,
    },
    body: JSON.stringify({
      schema: 'codex-usage-tracker.agent-request.v1',
      operation: 'delegation.efficiency.query',
      arguments: argumentsPayload,
    }),
    cache: 'no-store',
    signal: options.signal,
  });
  const payload = (await response.json()) as AgentResponse;
  if (!response.ok) {
    throw new Error(payload.error?.message || `Luna comparison failed (${response.status}).`);
  }
  const result = payload.result;
  if (
    result?.schema !== 'codex-usage-tracker.delegation-efficiency.v1'
    || !result.historical_comparison
  ) {
    throw new Error('Luna comparison returned an unexpected response.');
  }
  return result.historical_comparison;
}
