import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createDashboardQueryClient } from '../../data/queryRuntime';
import { fixtureModel } from '../../test-fixtures/dashboardFixture';
import { ReportsPage } from './ReportsPage';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Statistics dashboard destination', () => {
  it('loads dashboard statistics through the promoted reports route', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        schema: 'codex-usage-tracker.dashboard-statistics.v1',
        data_state: 'ready',
        reason: null,
        scope: {},
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
        series: { granularity: 'day', points: [] },
        heatmap: [],
        sessions: { count: 2, rows: [] },
        concentration: {},
        model_transitions: { switch_count: 1, switches_per_100_calls: 25, rows: [] },
        top_calls: [],
      }),
    } as Response));

    const model = {
      ...fixtureModel,
      contextRuntime: { ...fixtureModel.contextRuntime, apiToken: 'local-token', fileMode: false },
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
  });
});
