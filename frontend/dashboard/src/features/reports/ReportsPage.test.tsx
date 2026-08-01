import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createDashboardQueryClient } from '../../data/queryRuntime';
import { fixtureModel } from '../../test-fixtures/dashboardFixture';
import { ReportsPage } from './ReportsPage';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Statistics dashboard destination', () => {
  it('switches the usage graph between daily and hourly credits or calls', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
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
        model_rows: [],
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
      }),
    } as Response));

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

    fireEvent.click(screen.getByRole('button', { name: 'Hourly' }));
    expect(screen.getByRole('img', { name: 'Hourly credit usage chart' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Calls' }));
    expect(screen.getByRole('img', { name: 'Hourly call usage chart' })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Range'), { target: { value: '90' } });
    expect(screen.getByRole('button', { name: 'Hourly' })).toBeDisabled();
    expect(screen.getByRole('img', { name: 'Daily call usage chart' })).toBeInTheDocument();
  });
});
