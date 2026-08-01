import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createDashboardQueryClient } from '../../data/queryRuntime';
import { fixtureModel } from '../../test-fixtures/dashboardFixture';
import { ReportsPage } from './ReportsPage';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Statistics dashboard destination', () => {
  it('supports hourly ranges and detailed sortable model comparisons', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => statisticsPayload(),
    } as Response);
    vi.stubGlobal('fetch', fetchMock);

    const model = {
      ...fixtureModel,
      contextRuntime: {
        ...fixtureModel.contextRuntime,
        apiToken: 'local-token',
        fileMode: false,
      },
    };
    render(
      <QueryClientProvider client={createDashboardQueryClient()}>
        <ReportsPage
          model={model}
          refreshState="ready"
          includeArchived={false}
          loadWindow="all"
          loadLimit={500}
          sourceRevision="generation:1"
          onOpenInvestigator={vi.fn()}
          onCopyCallLink={vi.fn()}
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole('heading', { name: 'Statistics' })).toBeInTheDocument();
    expect(await screen.findByText('42')).toBeInTheDocument();
    expect(screen.getByText(/3 priced of 4 calls/)).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Daily credit usage chart' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Last 24 hours' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'GPT-5.6 Sol' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Unknown model' })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Columns'), { target: { value: 'tokens' } });
    expect(screen.getByRole('button', { name: 'Avg input' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cache ratio' })).toBeInTheDocument();
    expect(screen.getByText('1,500')).toBeInTheDocument();
    expect(screen.getByText('80.0%')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Columns'), { target: { value: 'summary' } });
    const unknownRow = screen.getByRole('row', { name: /Unknown model/ });
    expect(within(unknownRow).getAllByText('—').length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText('Range'), { target: { value: '1' } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('button', { name: 'Hourly' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('img', { name: 'Hourly credit usage chart' })).toBeInTheDocument();
    const rangeRequest = JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body));
    const rangeHours = (
      new Date(rangeRequest.until).getTime() - new Date(rangeRequest.since).getTime()
    ) / 3_600_000;
    expect(rangeHours).toBe(24);

    fireEvent.click(screen.getByRole('button', { name: 'Calls' }));
    expect(screen.getByRole('img', { name: 'Hourly call usage chart' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'GPT-5.6 Sol' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const modelRequest = JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body));
    expect(modelRequest.model).toBe('GPT-5.6 Sol');
    expect(screen.getByRole('button', { name: 'Clear model filter' })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Range'), { target: { value: '90' } });
    expect(screen.getByRole('button', { name: 'Hourly' })).toBeDisabled();
    expect(screen.getByRole('img', { name: 'Daily call usage chart' })).toBeInTheDocument();
  });
});

function statisticsPayload() {
  return {
    schema: 'codex-usage-tracker.dashboard-statistics.v1',
    data_state: 'ready',
    reason: null,
    scope: { timezone: 'Europe/Stockholm' },
    coverage: {
      total_call_count: 4,
      priced_call_count: 3,
      priced_call_ratio: 0.75,
      known_usage_credits: 42,
    },
    headline: {
      known_usage_credits: 42,
      calls: 4,
      mean_credits_per_priced_call: 14,
      median_credits_per_priced_call: 12,
      credits_per_calendar_day: 6,
      credits_per_active_hour: 10.5,
    },
    distribution: { mean: 14, median: 12, p75: 18, p90: 22, p95: 24, maximum: 25 },
    model_rows: [
      {
        model: 'GPT-5.6 Sol',
        calls: 3,
        call_share: 0.75,
        priced_calls: 3,
        priced_call_ratio: 1,
        known_credits: 42,
        credit_share: 1,
        mean: 14,
        median: 12,
        p75: 18,
        p90: 22,
        p95: 24,
        minimum: 5,
        maximum: 25,
        population_standard_deviation: 8,
        active_days: 2,
        active_hour_buckets: 3,
        total_tokens: 6000,
        input_tokens: 5625,
        cached_input_tokens: 4500,
        uncached_input_tokens: 1125,
        output_tokens: 375,
        reasoning_output_tokens: 150,
        avg_total_tokens_per_call: 2000,
        avg_input_tokens_per_call: 1875,
        avg_cached_input_tokens_per_call: 1500,
        avg_uncached_input_tokens_per_call: 375,
        avg_output_tokens_per_call: 125,
        avg_reasoning_tokens_per_call: 50,
        weighted_cache_ratio: 0.8,
        output_ratio: 0.0625,
        reasoning_output_ratio: 0.4,
        average_context_window_percent: 0.45,
        credits_per_million_total_tokens: 7000,
      },
      {
        model: 'Unknown model',
        calls: 1,
        call_share: 0.25,
        priced_calls: 0,
        priced_call_ratio: 0,
        known_credits: 0,
        credit_share: null,
        mean: null,
        median: null,
        p75: null,
        p90: null,
        p95: null,
        minimum: null,
        maximum: null,
        population_standard_deviation: null,
        active_days: 1,
        active_hour_buckets: 1,
        total_tokens: 100,
        input_tokens: 90,
        cached_input_tokens: 0,
        uncached_input_tokens: 90,
        output_tokens: 10,
        reasoning_output_tokens: 0,
        avg_total_tokens_per_call: 100,
        avg_input_tokens_per_call: 90,
        avg_cached_input_tokens_per_call: 0,
        avg_uncached_input_tokens_per_call: 90,
        avg_output_tokens_per_call: 10,
        avg_reasoning_tokens_per_call: 0,
        weighted_cache_ratio: 0,
        output_ratio: 0.1,
        reasoning_output_ratio: 0,
        average_context_window_percent: 0.1,
        credits_per_million_total_tokens: null,
      },
    ],
    series: {
      granularity: 'day',
      points: [
        { period_start: '2026-07-31', calls: 3, known_credits: 30 },
        { period_start: '2026-08-01', calls: 1, known_credits: 12 },
      ],
    },
    hourly_series: {
      granularity: 'hour',
      timezone: 'Europe/Stockholm',
      points: [
        {
          period_start: '2026-07-31T08:00:00Z',
          local_period_start: '2026-07-31T10:00:00+02:00',
          calls: 2,
          known_credits: 25,
        },
        {
          period_start: '2026-07-31T09:00:00Z',
          local_period_start: '2026-07-31T11:00:00+02:00',
          calls: 0,
          known_credits: 0,
        },
      ],
    },
    heatmap: [],
    sessions: { count: 2, rows: [] },
    concentration: {},
    model_transitions: { switch_count: 1, switches_per_100_calls: 25, rows: [] },
    top_calls: [],
  };
}
