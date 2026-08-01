import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { useMemo, useState } from 'react';

import { loadUsageStatistics } from '../../api/statistics';
import type { ContextRuntime } from '../../api/types';
import type { HistoryScope } from '../../data/dataScope';
import { Button, StatusBadge, Surface } from '../../design';
import styles from './StatisticsPage.module.css';

const ranges = [7, 30, 90, 365] as const;

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
  const range = useMemo(() => dateRange(days), [days]);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const query = useQuery({
    queryKey: ['usage-statistics-v1', sourceRevision, historyScope, days, model, sessionGap, timezone],
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
          <select value={String(days)} onChange={event => setDays(event.target.value === 'all' ? 'all' : Number(event.target.value))}>
            {ranges.map(value => <option key={value} value={value}>{value} days</option>)}
            <option value="all">All time</option>
          </select>
        </label>
        <label>Model
          <select value={model} onChange={event => setModel(event.target.value)}>
            <option value="">All models</option>
            {models.map(row => <option key={String(row.model)} value={String(row.model)}>{String(row.model)}</option>)}
          </select>
        </label>
        <label>Session gap
          <select value={sessionGap} onChange={event => setSessionGap(Number(event.target.value))}>
            {[15, 30, 45, 60, 120].map(value => <option key={value} value={value}>{value} minutes</option>)}
          </select>
        </label>
        <StatusBadge tone={payload?.data_state === 'ready' ? 'positive' : 'caution'}>
          {query.isFetching ? 'Updating' : payload?.data_state === 'ready' ? 'Ready' : 'Refresh required'}
        </StatusBadge>
      </Surface>

      {query.isError ? <Surface><p>{query.error instanceof Error ? query.error.message : 'Statistics unavailable.'}</p></Surface> : null}
      {payload?.data_state === 'refresh_required' ? (
        <Surface><h2>Refresh required</h2><p>Materialized call facts are missing or stale. Refresh the usage index before calculating statistics.</p></Surface>
      ) : null}
      {payload?.data_state === 'ready' ? <StatisticsContent payload={payload} onOpen={onOpenInvestigator} /> : null}
    </div>
  );
}

function StatisticsContent({ payload, onOpen }: { payload: NonNullable<ReturnType<typeof useQuery>['data']> & any; onOpen: (id: string) => void }) {
  const headline = payload.headline ?? {};
  const distribution = payload.distribution ?? {};
  const coverage = payload.coverage ?? {};
  const points = payload.series?.points ?? [];
  const maxCredits = Math.max(1, ...points.map((point: any) => Number(point.known_credits ?? 0)));
  return <>
    <section className={styles.cards}>
      <Metric label="Known credits" value={number(headline.known_usage_credits)} />
      <Metric label="Calls" value={integer(headline.calls)} />
      <Metric label="Mean / priced call" value={number(headline.mean_credits_per_priced_call)} />
      <Metric label="Median / priced call" value={number(headline.median_credits_per_priced_call)} />
      <Metric label="Credits / calendar day" value={number(headline.credits_per_calendar_day)} />
      <Metric label="Credits / active hour" value={number(headline.credits_per_active_hour)} />
    </section>

    <section className={styles.grid}>
      <Surface><h2>Credit distribution</h2><dl className={styles.definitionList}>
        {['mean', 'median', 'p75', 'p90', 'p95', 'maximum', 'population_standard_deviation'].map(key => <div key={key}><dt>{label(key)}</dt><dd>{number(distribution[key])}</dd></div>)}
      </dl><p className={styles.note}>{integer(coverage.priced_call_count)} priced of {integer(coverage.total_call_count)} calls ({percent(coverage.priced_call_ratio)}).</p></Surface>
      <Surface><h2>Concentration</h2><dl className={styles.definitionList}>
        {Object.entries(payload.concentration ?? {}).map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd>{percent(value)}</dd></div>)}
      </dl></Surface>
    </section>

    <Surface><h2>Daily usage</h2><div className={styles.bars}>{points.map((point: any) => <div key={String(point.period_start)} className={styles.barColumn} title={`${point.period_start}: ${number(point.known_credits)} credits`}><div className={styles.bar} style={{ height: `${Math.max(2, Number(point.known_credits ?? 0) / maxCredits * 100)}%` }} /><span>{String(point.period_start).slice(5)}</span></div>)}</div></Surface>

    <Surface><h2>Models</h2><div className={styles.tableWrap}><table><thead><tr><th>Model</th><th>Calls</th><th>Credits</th><th>Mean</th><th>Median</th><th>P90</th><th>P95</th><th>Coverage</th></tr></thead><tbody>{(payload.model_rows ?? []).map((row: any) => <tr key={row.model}><td><button className={styles.linkButton}>{row.model}</button></td><td>{integer(row.calls)}</td><td>{number(row.known_credits)}</td><td>{number(row.mean)}</td><td>{number(row.median)}</td><td>{number(row.p90)}</td><td>{number(row.p95)}</td><td>{percent(row.priced_call_ratio)}</td></tr>)}</tbody></table></div></Surface>

    <section className={styles.grid}>
      <Surface><h2>Activity sessions</h2><p>{integer(payload.sessions?.count)} sessions inferred using the selected idle gap.</p>{(payload.sessions?.rows ?? []).slice(0, 5).map((row: any) => <div className={styles.listRow} key={row.start_at}><span>{new Date(row.start_at).toLocaleString()}</span><strong>{number(row.known_credits)} credits · {integer(row.calls)} calls</strong></div>)}</Surface>
      <Surface><h2>Model transitions</h2><p>{integer(payload.model_transitions?.switch_count)} switches · {number(payload.model_transitions?.switches_per_100_calls)} per 100 calls</p>{(payload.model_transitions?.rows ?? []).map((row: any) => <div className={styles.listRow} key={`${row.from_model}-${row.to_model}`}><span>{row.from_model} → {row.to_model}</span><strong>{row.count}</strong></div>)}</Surface>
    </section>

    <Surface><h2>Most expensive calls</h2>{(payload.top_calls ?? []).map((row: any) => <button className={styles.callRow} key={row.record_id} onClick={() => onOpen(row.record_id)}><span>{new Date(row.event_timestamp).toLocaleString()} · {row.model}</span><strong>{number(row.usage_credits)} credits</strong></button>)}</Surface>
  </>;
}

function Metric({ label: text, value }: { label: string; value: string }) { return <Surface className={styles.metric}><span>{text}</span><strong>{value}</strong></Surface>; }
function dateRange(days: number | 'all') { const until = new Date(); const since = new Date(days === 'all' ? 0 : until.getTime() - (days - 1) * 86400000); if (days !== 'all') since.setHours(0, 0, 0, 0); return { since: since.toISOString(), until: until.toISOString() }; }
function number(value: unknown) { const parsed = Number(value); return Number.isFinite(parsed) ? parsed.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—'; }
function integer(value: unknown) { const parsed = Number(value); return Number.isFinite(parsed) ? Math.round(parsed).toLocaleString() : '—'; }
function percent(value: unknown) { const parsed = Number(value); return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(1)}%` : '—'; }
function label(value: string) { return value.replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase()); }
