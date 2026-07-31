import type { AllowancePlanComparison } from '../../api/allowancePlanComparison';
import { StatusBadge, Surface } from '../../design';
import styles from './LimitsIntelligence.module.css';

type AllowancePlanComparisonCardProps = {
  comparison: AllowancePlanComparison | null;
  loading?: boolean;
};

export function AllowancePlanComparisonCard({
  comparison,
  loading = false,
}: AllowancePlanComparisonCardProps) {
  if (!comparison) {
    return loading ? (
      <Surface className={styles.comparisonCard}>
        <p className={styles.comparisonEyebrow}>Plan-switch capacity</p>
        <p>Calculating the weekly meter before and after the subscription-plan change…</p>
      </Surface>
    ) : null;
  }

  const transition = comparison.transition;
  const primaryPercent = comparison.relative_meter_size.after_as_percent_of_before;
  const earlyPercent = comparison.early_interval_estimate.after_as_percent_of_before
    ?? (comparison.early_interval_estimate.after_to_before_ratio === null
      ? null
      : comparison.early_interval_estimate.after_to_before_ratio * 100);
  const displayedPercent = primaryPercent ?? earlyPercent;
  const multiplier = comparison.relative_meter_size.before_to_after_multiplier;
  const interval = comparison.statistics.ratio_confidence_interval_95;
  const hasCompletedComparison = comparison.before !== null && comparison.after !== null;
  const exploratory = comparison.status === 'insufficient_completed_cycles'
    || comparison.status === 'descriptive_only';

  return (
    <Surface className={styles.comparisonCard}>
      <div className={styles.comparisonHeader}>
        <div>
          <p className={styles.comparisonEyebrow}>Plan-switch capacity</p>
          <h2>Post-switch weekly meter</h2>
        </div>
        <StatusBadge tone={statusTone(comparison.status)}>{statusLabel(comparison.status)}</StatusBadge>
      </div>

      {comparison.status === 'no_transition' ? (
        <p>
          No contiguous transition between two known weekly plan types is available yet.
          {transition.observed_plan_types?.length
            ? ` Observed plans: ${transition.observed_plan_types.join(', ')}.`
            : ''}
        </p>
      ) : (
        <>
          <div className={styles.comparisonHero}>
            <strong className={styles.comparisonRatio}>
              {displayedPercent === null ? 'Not enough data' : `${displayedPercent.toFixed(1)}%`}
            </strong>
            <div>
              <p>of the previous weekly capacity</p>
              <p className={styles.comparisonTransition}>
                {formatPlan(transition.from_plan)} → {formatPlan(transition.to_plan)}
                {multiplier === null ? '' : ` · previous meter estimated ${multiplier.toFixed(2)}× larger`}
              </p>
            </div>
          </div>

          {hasCompletedComparison ? (
            <div className={styles.comparisonCohorts}>
              <CohortSummary label="Before" cohort={comparison.before} />
              <CohortSummary label="After" cohort={comparison.after} />
            </div>
          ) : null}

          <div className={styles.comparisonEvidence}>
            {interval?.low !== null && interval?.high !== null ? (
              <span>95% ratio interval: {(interval.low * 100).toFixed(1)}%–{(interval.high * 100).toFixed(1)}%</span>
            ) : null}
            {comparison.statistics.permutation?.two_sided_p_value !== null
              && comparison.statistics.permutation ? (
                <span>Fixed-label p={comparison.statistics.permutation.two_sided_p_value.toFixed(4)}</span>
              ) : null}
            {comparison.statistics.cliffs_delta_after_vs_before !== null ? (
              <span>Cliff’s δ={comparison.statistics.cliffs_delta_after_vs_before.toFixed(3)}</span>
            ) : null}
          </div>

          {exploratory ? (
            <p className={styles.comparisonCaveats}>
              Exploratory estimate: too few eligible completed cycles exist on one side of the
              switch for a supported claim. The interval estimate is shown only as early evidence.
            </p>
          ) : null}
          <p className={styles.comparisonCaveats}>
            Based on locally visible, model-normalized Codex usage. This is not an official OpenAI
            allowance or billing ledger.
          </p>
        </>
      )}
    </Surface>
  );
}

function CohortSummary({
  label,
  cohort,
}: {
  label: string;
  cohort: NonNullable<AllowancePlanComparison['before']>;
}) {
  return (
    <div>
      <span>{label} · {formatPlan(cohort.plan_type)}</span>
      <strong>{formatCredits(cohort.median_credits_per_percent)} credits/%</strong>
      <small>{cohort.eligible_cycle_count} eligible of {cohort.observed_cycle_count} completed-cycle records</small>
    </div>
  );
}

function formatCredits(value: number | null): string {
  return value === null ? '—' : value.toFixed(1);
}

function formatPlan(value: string | null): string {
  if (!value) return 'Unknown plan';
  return value.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}

function statusLabel(status: AllowancePlanComparison['status']): string {
  switch (status) {
    case 'supported_smaller': return 'Supported decrease';
    case 'supported_larger': return 'Supported increase';
    case 'no_supported_difference': return 'No supported difference';
    case 'insufficient_completed_cycles': return 'Early estimate';
    case 'descriptive_only': return 'Descriptive';
    default: return 'No plan transition';
  }
}

function statusTone(status: AllowancePlanComparison['status']): 'positive' | 'warning' | 'neutral' {
  if (status === 'supported_smaller') return 'positive';
  if (status === 'supported_larger' || status === 'insufficient_completed_cycles') return 'warning';
  return 'neutral';
}
