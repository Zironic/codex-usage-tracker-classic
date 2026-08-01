import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import {
  loadUsageStatistics,
  type StatisticsPayload,
  type StatisticsSeriesPoint,
} from '../../api/statistics';
import type { ContextRuntime } from '../../api/types';
import type { HistoryScope } from '../../data/dataScope';
import { Button, SegmentedControl, StatusBadge, Surface } from '../../design';
import styles from './StatisticsPage.module.css';

const ranges = [7, 30, 90, 365] as const;
type ChartGranularity = 'day' | 'hour';
type ChartMetric = 'credits' | 'calls';

export function StatisticsPage({
  contextRuntime,
  historyScope,
  sourceRevision,
  refreshing,
  onRefresh,
  onOpenInvestigator,
}: {
  contextRuntime: ContextRuntime;
  historyScope: HistoryScope;
  sourceRevision: string;
  refreshing: boolean;
  onRefresh: () => void;
  onOpenInvestigator: (recordId: string) => void;
}) {
  const [days, setDays] = useState<number | 'all'>(30);
  const [model, setModel] = useState('');
  const [sessionGap, setSessionGap] = useState(30);
  const [granularity, setGranularity] = useState<ChartGranularity>('day');
  const [metric, setMetric] = useState<ChartMetric>('credits');
  const range = useMemo(() => dateRange(days), [days]);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const hourlyRangeAvailable = days !== 'all' && days <= 30;

  useEffect(() => {
    if (!hourlyRangeAvailable && granularity === 'hour') {
      setGranularity('day');
    }
  }, [granularity, hourlyRangeAvailable]);

  const query = useQuery({
    queryKey: [
      'usage-statistics-v1',
      sourceRevision,
      historyScope,
      days,
      model,
      sessionGap,
      timezone,
    ],
    queryFn: ({ signal }) => loadUsageStatistics(contextRuntime, {
      ...range,
      timezone,
      history: historyScope,
      ...(model ? { model } : {}),
      session_gap_minutes: sessionGap,
      top_limit: 10,
      all_time: days === 'all',
    }, signal),
    enabled: Boolean(contextRuntime.apiToken) && !contextRuntime.fileMode,
    staleTime: 30_000,
    retry: 1,
  });
  const payload = query.data;
  const models = payload?.model_rows ?? [];

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Usage statistics</p>
          <h1>Statistics</h1>
          <p>Credit distributions, time-normalized rates, model mix, sessions, and concentration.</p>
        </div>
        <Button variant="primary" onClick={onRefresh} disabled={refreshing}>
          <RefreshCw size={16} /> {refreshing ? 'Refreshing…' : 'Refresh data'}
        </Button>
      </header>

      <Surface className={styles.controls}>
        <label>Range
          <select
            value={String(days)}
            onChange={event => setDays(event.target.value === 'all'
              ? 'all'
              : Number(event.target.value))}
          >
            {ranges.map(value => <option key={value} value={value}>{value} days</option>)}
            <option value="all">All time</option>
          </select>
        </label>
        <label>Model
          <select value={model} onChange={event => setModel(event.target.value)}>
            <option value="">All models</option>
            {models.map(row => (
              <option key={String(row.model)} value={String(row.model)}>
                {String(row.model)}
              </option>
            ))}
          </select>
        </label>
        <label>Session gap
          <select
            value={sessionGap}
            onChange={event => setSessionGap(Number(event.target.value))}
          >
            {[15, 30, 45, 60, 120].map(value => (
              <option key={value} value={value}>{value} minutes</option>
            ))}
          </select>
        </label>
        <StatusBadge tone={payload?.data_state === 'ready' ? 'positive' : 'caution'}>
          {query.isFetching
            ? 'Updating'
            : payload?.data_state === 'ready'
              ? 'Ready'
              : 'Refresh required'}
        </StatusBadge>
      </Surface>

      {query.isError ? (
        <Surface>
          <p>{query.error instanceof Error ? query.error.message : 'Statistics unavailable.'}</p>
        </Surface>
      ) : null}
      {payload?.data_state === 'refresh_required' ? (
        <Surface>
          <h2>Refresh required</h2>
          <p>
            Materialized call facts are missing or stale. Refresh the usage index before
            calculating statistics.
          </p>
        </Surface>
      ) : null}
      {payload?.data_state === 'ready' ? (
        <StatisticsContent
          payload={payload}
          onOpen={onOpenInvestigator}
          granularity={granularity}
          onGranularityChange={setGranularity}
          metric={metric}
          onMetricChange={setMetric}
          hourlyRangeAvailable={hourlyRangeAvailable}
        />
      ) : null}
    </div>
  );
}

function StatisticsContent({
  payload,
  onOpen,
  granularity,
  onGranularityChange,
  metric,
  onMetricChange,
  hourlyRangeAvailable,
}: {
  payload: StatisticsPayload;
  onOpen: (id: string) => void;
  granularity: ChartGranularity;
  onGranularityChange: (value: ChartGranularity) => void;
  metric: ChartMetric;
  onMetricChange: (value: ChartMetric) => void;
  hourlyRangeAvailable: boolean;
}) {
  const headline = payload.headline ?? {};
  const distribution = payload.distribution ?? {};
  const coverage = payload.coverage ?? {};
  const hourlyAvailable = hourlyRangeAvailable && Boolean(payload.hourly_series);
  const activeGranularity = granularity === 'hour' && hourlyAvailable ? 'hour' : 'day';
  const selectedSeries = activeGranularity === 'hour'
    ? payload.hourly_series
    : payload.series;
  const points = selectedSeries?.points ?? [];
  const maxValue = Math.max(1, ...points.map(point => chartValue(point, metric)));

  return (
    <>
      <section className={styles.cards}>
        <Metric label="Known credits" value={number(headline.known_usage_credits)} />
        <Metric label="Calls" value={integer(headline.calls)} />
        <Metric
          label="Mean / priced call"
          value={number(headline.mean_credits_per_priced_call)}
        />
        <Metric
          label="Median / priced call"
          value={number(headline.median_credits_per_priced_call)}
        />
        <Metric
          label="Credits / calendar day"
          value={number(headline.credits_per_calendar_day)}
        />
        <Metric
          label="Credits / active hour"
          value={number(headline.credits_per_active_hour)}
        />
      </section>

      <section className={styles.grid}>
        <Surface>
          <h2>Credit distribution</h2>
          <dl className={styles.definitionList}>
            {[
              'mean',
              'median',
              'p75',
              'p90',
              'p95',
              'maximum',
              'population_standard_deviation',
            ].map(key => (
              <div key={key}>
                <dt>{label(key)}</dt>
                <dd>{number(distribution[key])}</dd>
              </div>
            ))}
          </dl>
          <p className={styles.note}>
            {integer(coverage.priced_call_count)} priced of{' '}
            {integer(coverage.total_call_count)} calls ({percent(coverage.priced_call_ratio)}).
          </p>
        </Surface>
        <Surface>
          <h2>Concentration</h2>
          <dl className={styles.definitionList}>
            {Object.entries(payload.concentration ?? {}).map(([key, value]) => (
              <div key={key}>
                <dt>{label(key)}</dt>
                <dd>{percent(value)}</dd>
              </div>
            ))}
          </dl>
        </Surface>
      </section>

      <Surface>
        <div className={styles.chartHeader}>
          <div>
            <h2>Usage over time</h2>
            <p className={styles.note}>
              Hourly view uses elapsed UTC buckets displayed in {String(payload.scope.timezone ?? 'local time')}.
            </p>
          </div>
          <div className={styles.chartControls}>
            <SegmentedControl
              label="Time granularity"
              value={activeGranularity}
              onValueChange={onGranularityChange}
              options={[
                { label: 'Daily', value: 'day' },
                {
                  label: 'Hourly',
                  value: 'hour',
                  disabled: !hourlyAvailable,
                },
              ]}
            />
            <SegmentedControl
              label="Usage metric"
              value={metric}
              onValueChange={onMetricChange}
              options={[
                { label: 'Credits', value: 'credits' },
                { label: 'Calls', value: 'calls' },
              ]}
            />
          </div>
        </div>
        {!hourlyRangeAvailable ? (
          <p className={styles.note}>Hourly view is available for 7- and 30-day ranges.</p>
        ) : null}
        <div
          className={`${styles.bars} ${activeGranularity === 'hour' ? styles.hourlyBars : ''}`}
          role="img"
          aria-label={`${activeGranularity === 'hour' ? 'Hourly' : 'Daily'} ${metric === 'credits' ? 'credit' : 'call'} usage chart`}
        >
          {points.map((point, index) => {
            const value = chartValue(point, metric);
            const height = value > 0 ? Math.max(2, value / maxValue * 100) : 0;
            return (
              <div
                key={point.period_start}
                className={styles.barColumn}
                title={pointTitle(point, activeGranularity, metric)}
              >
                <div className={styles.bar} style={{ height: `${height}%` }} />
                <span>{axisLabel(point, index, activeGranularity)}</span>
              </div>
            );
          })}
        </div>
      </Surface>

      <Surface>
        <h2>Models</h2>
        <div className={styles.tableWrap}>
          <table>
            <thead>
              <tr>
                <th>Model</th><th>Calls</th><th>Credits</th><th>Mean</th>
                <th>Median</th><th>P90</th><th>P95</th><th>Coverage</th>
              </tr>
            </thead>
            <tbody>
              {(payload.model_rows ?? []).map(row => (
                <tr key={String(row.model)}>
                  <td><button className={styles.linkButton}>{String(row.model)}</button></td>
                  <td>{integer(row.calls)}</td>
                  <td>{number(row.known_credits)}</td>
                  <td>{number(row.mean)}</td>
                  <td>{number(row.median)}</td>
                  <td>{number(row.p90)}</td>
                  <td>{number(row.p95)}</td>
                  <td>{percent(row.priced_call_ratio)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Surface>

      <section className={styles.grid}>
        <Surface>
          <h2>Activity sessions</h2>
          <p>{integer(payload.sessions?.count)} sessions inferred using the selected idle gap.</p>
          {(payload.sessions?.rows ?? []).slice(0, 5).map(row => (
            <div className={styles.listRow} key={String(row.start_at)}>
              <span>{new Date(String(row.start_at)).toLocaleString()}</span>
              <strong>
                {number(row.known_credits)} credits · {integer(row.calls)} calls
              </strong>
            </div>
          ))}
        </Surface>
        <Surface>
          <h2>Model transitions</h2>
          <p>
            {integer(payload.model_transitions?.switch_count)} switches ·{' '}
            {number(payload.model_transitions?.switches_per_100_calls)} per 100 calls
          </p>
          {(payload.model_transitions?.rows ?? []).map(row => (
            <div
              className={styles.listRow}
              key={`${row.from_model}-${row.to_model}`}
            >
              <span>{row.from_model} → {row.to_model}</span>
              <strong>{row.count}</strong>
            </div>
          ))}
        </Surface>
      </section>

      <Surface>
        <h2>Most expensive calls</h2>
        {(payload.top_calls ?? []).map(row => (
          <button
            className={styles.callRow}
            key={row.record_id}
            onClick={() => onOpen(row.record_id)}
          >
            <span>{new Date(row.event_timestamp).toLocaleString()} · {row.model}</span>
            <strong>{number(row.usage_credits)} credits</strong>
          </button>
        ))}
      </Surface>
    </>
  );
}

function Metric({ label: text, value }: { label: string; value: string }) {
  return (
    <Surface className={styles.metric}>
      <span>{text}</span>
      <strong>{value}</strong>
    </Surface>
  );
}

function dateRange(days: number | 'all') {
  const until = new Date();
  const since = new Date(days === 'all' ? 0 : until.getTime() - (days - 1) * 86_400_000);
  if (days !== 'all') since.setHours(0, 0, 0, 0);
  return { since: since.toISOString(), until: until.toISOString() };
}

function chartValue(point: StatisticsSeriesPoint, metric: ChartMetric): number {
  return metric === 'credits' ? point.known_credits : point.calls;
}

function pointTitle(
  point: StatisticsSeriesPoint,
  granularity: ChartGranularity,
  metric: ChartMetric,
): string {
  const period = granularity === 'hour'
    ? new Date(point.period_start).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        timeZoneName: 'short',
      })
    : point.period_start;
  const value = metric === 'credits'
    ? `${number(point.known_credits)} credits`
    : `${integer(point.calls)} calls`;
  return `${period}: ${value}`;
}

function axisLabel(
  point: StatisticsSeriesPoint,
  index: number,
  granularity: ChartGranularity,
): string {
  if (granularity === 'day') return point.period_start.slice(5);
  const local = new Date(point.period_start);
  if (index !== 0 && local.getHours() !== 0) return '';
  return local.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function number(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : '—';
}

function integer(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed).toLocaleString() : '—';
}

function percent(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(1)}%` : '—';
}

function label(value: string) {
  return value.replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}
