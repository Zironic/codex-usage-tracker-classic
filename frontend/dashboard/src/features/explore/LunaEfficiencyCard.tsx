import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Sparkles } from 'lucide-react';

import {
  loadDelegationEfficiency,
  type DelegationHistoricalComparison,
  type DelegationPeriod,
} from '../../api/delegationEfficiency';
import type { ContextRuntime } from '../../api/types';
import styles from './ExplorePage.module.css';

type LunaEfficiencyCardProps = {
  contextRuntime: ContextRuntime;
  includeArchived?: boolean;
  scopeSince?: string | null;
  sourceRevision?: string;
};

export function LunaEfficiencyCard({
  contextRuntime,
  includeArchived = false,
  scopeSince = null,
  sourceRevision = 'unversioned',
}: LunaEfficiencyCardProps) {
  const comparison = useQuery({
    queryKey: ['delegation-efficiency', sourceRevision, scopeSince, includeArchived],
    queryFn: ({ signal }) => loadDelegationEfficiency(contextRuntime, {
      since: scopeSince,
      includeArchived,
      signal,
    }),
    enabled: !contextRuntime.fileMode && Boolean(contextRuntime.apiToken),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  if (!comparison.isPending && !comparison.data && !comparison.error) return null;

  return (
    <section className={styles.efficiencyCard} aria-labelledby="luna-efficiency-title">
      <header className={styles.efficiencyHeader}>
        <div>
          <p className={styles.eyebrow}>Delegation breakpoint</p>
          <h2 id="luna-efficiency-title">Did Luna reduce Sol&apos;s work?</h2>
        </div>
        {comparison.data ? <DeltaBadge comparison={comparison.data} /> : null}
      </header>

      {comparison.isPending ? (
        <p className={styles.efficiencyState}>Measuring direct Sol turns before and after Luna…</p>
      ) : comparison.isError ? (
        <p className={styles.efficiencyState} role="alert">
          {comparison.error instanceof Error ? comparison.error.message : 'Luna comparison is unavailable.'}
        </p>
      ) : comparison.data?.adoption_at ? (
        <ComparisonBody comparison={comparison.data} />
      ) : (
        <p className={styles.efficiencyState}>
          No Luna worker role was observed in the selected timeframe.
        </p>
      )}
    </section>
  );
}

function ComparisonBody({ comparison }: { comparison: DelegationHistoricalComparison }) {
  return (
    <>
      <div className={styles.breakpointGrid}>
        <Period label="Before Luna" period={comparison.before} />
        <div className={styles.breakpointMarker} aria-label="Luna adoption boundary">
          <span className={styles.breakpointLine} />
          <span className={styles.breakpointIcon}><Sparkles aria-hidden="true" size={15} /></span>
          <strong>Luna observed</strong>
          <time dateTime={comparison.adoption_at ?? undefined}>
            {formatDateTime(comparison.adoption_at)}
          </time>
          <span>{formatRole(comparison.adoption_role)}</span>
        </div>
        <Period label="After Luna" period={comparison.after} />
      </div>
      <footer className={styles.efficiencyFooter}>
        <span>{comparison.interpretation}</span>
        <span>
          Turn identity coverage: {formatInteger(comparison.before.exact_turn_calls + comparison.after.exact_turn_calls)} exact,
          {' '}{formatInteger(comparison.before.fallback_turn_calls + comparison.after.fallback_turn_calls)} fallback.
        </span>
      </footer>
    </>
  );
}

function Period({ label, period }: { label: string; period: DelegationPeriod }) {
  return (
    <article className={styles.period}>
      <p>{label}</p>
      <strong>{formatTokens(period.tokens_per_turn)}</strong>
      <span>direct Sol tokens / turn</span>
      <dl>
        <div><dt>Turns</dt><dd>{formatInteger(period.turns)}</dd></div>
        <div><dt>Calls / turn</dt><dd>{formatDecimal(period.calls_per_turn)}</dd></div>
        <div><dt>Uncached / turn</dt><dd>{formatTokens(period.uncached_input_tokens_per_turn)}</dd></div>
        <div><dt>Output / turn</dt><dd>{formatTokens(period.output_tokens_per_turn)}</dd></div>
      </dl>
    </article>
  );
}

function DeltaBadge({ comparison }: { comparison: DelegationHistoricalComparison }) {
  const delta = comparison.percent_delta;
  const label = delta === null
    ? 'Comparison unavailable'
    : `${delta > 0 ? '+' : ''}${delta.toFixed(1)}% tokens / turn`;
  return (
    <span className={`${styles.deltaBadge} ${styles[comparison.direction]}`}>
      {label}<ArrowRight aria-hidden="true" size={15} />
    </span>
  );
}

function formatTokens(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('en-US', {
    notation: value >= 100_000 ? 'compact' : 'standard',
    maximumFractionDigits: value >= 100_000 ? 2 : 0,
  }).format(value);
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value);
}

function formatDecimal(value: number | null): string {
  return value === null ? '—' : value.toFixed(1);
}

function formatDateTime(value: string | null): string {
  if (!value) return 'Unknown time';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function formatRole(value: string | null): string {
  return value?.replaceAll('_', ' ') || 'caller-supplied boundary';
}
