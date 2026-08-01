import { StatusBadge, Surface } from '../../design';
import type {
  AllowanceAnalysisPayload,
  AllowanceCapacityBoundary,
  AllowanceEvidenceRow,
} from '../../api/allowanceIntelligenceTypes';
import { AllowancePlanComparisonCard } from './AllowancePlanComparisonCard';
import styles from './AllowanceCapacity.module.css';

type AllowanceCapacityChangeTimelineProps = {
  analysis: AllowanceAnalysisPayload | undefined;
  evidenceRows: AllowanceEvidenceRow[];
  running: boolean;
};

type PricingChangeInference = {
  status: 'supported_change' | 'no_supported_change' | 'insufficient_evidence' | 'unavailable';
  confidence: 'high' | 'medium' | 'low' | 'none';
  reason?: string | null;
  revision?: {
    before_revision_id?: string;
    after_revision_id?: string;
    configured_effective_at?: string;
    configured_effective_at_precision?: string;
    source_modified_at?: string | null;
    first_observed_at?: string | null;
  } | null;
  estimate?: {
    effective_at_estimate?: string;
    effective_at_lower_bound?: string;
    effective_at_upper_bound?: string;
  } | null;
  evidence?: {
    informative_interval_count?: number;
    fit_improvement_over_best_null?: number;
    directional_advantage_over_reversed?: number;
  } | null;
};

export function AllowanceCapacityChangeTimeline({
  analysis,
  evidenceRows,
  running,
}: AllowanceCapacityChangeTimelineProps) {
  const boundaries = [...(analysis?.boundaries ?? [])]
    .sort((left, right) => Date.parse(right.effective_at) - Date.parse(left.effective_at));
  const hasSupportedChanges = boundaries.length > 0;
  const pricingChange = asPricingChangeInference(analysis?.pricing_change);

  return (
    <>
      <AllowancePlanComparisonCard
        comparison={analysis?.plan_comparison ?? null}
        loading={running || analysis?.status === 'missing'}
      />
      <PricingChangeCard inference={pricingChange} running={running} />
      <Surface className={styles.capacityChangePanel}>
        <div className={styles.capacityChangeHeader}>
          <div>
            <p className={styles.capacityChangeEyebrow}>Capacity changes</p>
            <h2>{timelineTitle(analysis, running, hasSupportedChanges)}</h2>
          </div>
          <StatusBadge tone={hasSupportedChanges ? 'caution' : analysis?.status === 'no_supported_change' ? 'positive' : 'neutral'}>
            {running ? 'Analyzing' : hasSupportedChanges ? `${boundaries.length} supported` : statusLabel(analysis)}
          </StatusBadge>
        </div>

        {hasSupportedChanges ? (
          <ol
            className={styles.capacityChangeList}
            aria-label="Supported capacity changes"
            data-localization-attributes="aria-label"
          >
            {boundaries.map(boundary => (
              <BoundaryItem
                key={boundary.boundary_id}
                analysisId={analysis?.snapshot_id ?? null}
                boundary={boundary}
                evidenceId={boundaryEvidenceId(boundary, evidenceRows)}
              />
            ))}
          </ol>
        ) : (
          <p className={styles.capacityChangeExplanation}>{timelineExplanation(analysis, running)}</p>
        )}

        <dl className={styles.capacityChangeMeta}>
          <div><dt>Eligible reset windows</dt><dd>{analysis?.eligible_cycle_count ?? '—'}</dd></div>
          <div><dt>Last analyzed</dt><dd>{analysis?.generated_at ? formatDateTime(analysis.generated_at) : running ? 'In progress' : 'Not yet'}</dd></div>
        </dl>
      </Surface>
    </>
  );
}

function PricingChangeCard({
  inference,
  running,
}: {
  inference: PricingChangeInference | null;
  running: boolean;
}) {
  const supported = inference?.status === 'supported_change';
  const estimate = inference?.estimate;
  const intervalCount = inference?.evidence?.informative_interval_count;
  const improvement = inference?.evidence?.fit_improvement_over_best_null;
  return (
    <Surface className={styles.capacityChangePanel}>
      <div className={styles.capacityChangeHeader}>
        <div>
          <p className={styles.capacityChangeEyebrow}>Credit rate timing</p>
          <h2>{pricingChangeTitle(inference, running)}</h2>
        </div>
        <StatusBadge tone={supported ? 'caution' : 'neutral'}>
          {running ? 'Analyzing' : inference ? confidenceLabel(inference) : 'Unavailable'}
        </StatusBadge>
      </div>
      <p className={styles.capacityChangeExplanation}>
        {pricingChangeExplanation(inference, running)}
      </p>
      <dl className={styles.capacityChangeMeta}>
        <div><dt>Informative intervals</dt><dd>{intervalCount ?? '—'}</dd></div>
        <div><dt>Fit improvement</dt><dd>{typeof improvement === 'number' ? formatPercent(improvement) : '—'}</dd></div>
        <div><dt>Configured prior</dt><dd>{inference?.revision?.configured_effective_at ? formatDateTime(inference.revision.configured_effective_at) : '—'}</dd></div>
        <div><dt>Local estimate</dt><dd>{estimate?.effective_at_estimate ? formatDateTime(estimate.effective_at_estimate) : '—'}</dd></div>
      </dl>
    </Surface>
  );
}

function pricingChangeTitle(
  inference: PricingChangeInference | null,
  running: boolean,
): string {
  if (running) return 'Testing old and new rate tables';
  if (!inference || inference.status === 'unavailable') return 'No timestamped rate pair available';
  if (inference.status === 'insufficient_evidence') return 'More changed-model usage is needed';
  if (inference.status === 'supported_change') return 'Local usage supports a rate change boundary';
  return 'Local usage does not yet support the proposed boundary';
}

function pricingChangeExplanation(
  inference: PricingChangeInference | null,
  running: boolean,
): string {
  if (running) {
    return 'Weekly meter intervals are being repriced under old-only, new-only, old-to-new, and reversed hypotheses.';
  }
  if (!inference) return 'No pricing-change analysis has been produced for this data revision.';
  const estimate = inference.estimate;
  if (inference.status === 'supported_change' && estimate?.effective_at_estimate) {
    const bounds = estimate.effective_at_lower_bound && estimate.effective_at_upper_bound
      ? ` The plausible interval is ${formatDateTime(estimate.effective_at_lower_bound)} to ${formatDateTime(estimate.effective_at_upper_bound)}.`
      : '';
    return `The observed weekly meter fits the old-to-new rate tables best at ${formatDateTime(estimate.effective_at_estimate)}.${bounds}`;
  }
  if (inference.status === 'insufficient_evidence') {
    return 'There are not enough weekly intervals containing models whose credit rates changed on both sides of a candidate boundary.';
  }
  if (inference.status === 'unavailable') {
    return 'The active rate card does not contain two adjacent, different timestamped rate revisions.';
  }
  return 'The old-to-new hypothesis did not outperform both timeless and reversed alternatives by the required margins.';
}

function confidenceLabel(inference: PricingChangeInference): string {
  if (inference.status !== 'supported_change') {
    if (inference.status === 'insufficient_evidence') return 'Insufficient';
    if (inference.status === 'unavailable') return 'Unavailable';
    return 'Not supported';
  }
  return `${inference.confidence[0].toUpperCase()}${inference.confidence.slice(1)} confidence`;
}

function asPricingChangeInference(value: unknown): PricingChangeInference | null {
  if (!value || typeof value !== 'object') return null;
  const status = (value as { status?: unknown }).status;
  if (!['supported_change', 'no_supported_change', 'insufficient_evidence', 'unavailable'].includes(String(status))) {
    return null;
  }
  return value as PricingChangeInference;
}

function BoundaryItem({
  analysisId,
  boundary,
  evidenceId,
}: {
  analysisId: string | null;
  boundary: AllowanceCapacityBoundary;
  evidenceId: string | null;
}) {
  const before = boundary.effect_size.median_before_credits_per_percent;
  const after = boundary.effect_size.median_after_credits_per_percent;
  const deltaPercent = before === 0 ? null : ((after - before) / before) * 100;
  const direction = after < before ? 'decreased' : after > before ? 'increased' : 'changed';
  const accessibleLabel = `Credits per 1% ${direction} ${formatCredits(before)} to ${formatCredits(after)} on ${formatDate(boundary.effective_at)}`;
  return (
    <li className={styles.capacityChangeItem} aria-label={accessibleLabel}>
      <time dateTime={boundary.effective_at}>{formatDate(boundary.effective_at)}</time>
      <div className={styles.capacityChangeDetail}>
        <div>
          <span className={styles.capacityChangeType}>Supported change</span>
          <strong>Credits per 1% {direction}</strong>
          <p>{formatCredits(before)} → {formatCredits(after)}{deltaPercent === null ? '' : ` (${formatSignedPercent(deltaPercent)})`}</p>
        </div>
        {analysisId && evidenceId ? (
          <a
            className={styles.capacityEvidenceLink}
            href={allowanceEvidenceHref(analysisId, evidenceId)}
            aria-label={`Open supporting Evidence for ${boundary.boundary_id}`}
          >
            View Evidence
          </a>
        ) : null}
      </div>
    </li>
  );
}

function boundaryEvidenceId(
  boundary: AllowanceCapacityBoundary,
  rows: AllowanceEvidenceRow[],
): string | null {
  const match = rows.find(row => (
    row.cycle_id === boundary.after_cycle_id || row.cycle_id === boundary.before_cycle_id
  ) && row.interval_id);
  return match?.interval_id ?? null;
}

function allowanceEvidenceHref(analysisId: string, evidenceId: string): string {
  const params = new URLSearchParams({
    view: 'evidence',
    kind: 'allowance',
    analysis: analysisId,
    evidence: evidenceId,
  });
  if (new URLSearchParams(window.location.search).get('history') === 'all') params.set('history', 'all');
  return `?${params.toString()}`;
}

function timelineTitle(
  analysis: AllowanceAnalysisPayload | undefined,
  running: boolean,
  hasSupportedChanges: boolean,
): string {
  if (running) return 'Checking capacity history';
  if (hasSupportedChanges) return analysis?.boundaries?.length === 1
    ? '1 reliable capacity change detected'
    : `${analysis?.boundaries?.length ?? 0} reliable capacity changes detected`;
  if (analysis?.status === 'insufficient_evidence') return 'More completed reset windows needed';
  if (analysis?.status === 'missing') return 'Capacity analysis is queued';
  return 'No reliable capacity change detected';
}

function timelineExplanation(analysis: AllowanceAnalysisPayload | undefined, running: boolean): string {
  if (running) return 'The aggregate-only detector is testing completed-cycle boundaries for this data revision.';
  if (!analysis || analysis.status === 'missing') return 'Analysis starts automatically when this data revision is available.';
  if (analysis.status === 'insufficient_evidence') {
    return analysis.reason ?? 'There are not yet enough quality-approved reset windows on both sides of a boundary.';
  }
  return 'No boundary passed both the family-wise significance gate and the strong-effect gate. Rejected candidate values are intentionally hidden.';
}

function statusLabel(analysis: AllowanceAnalysisPayload | undefined): string {
  if (!analysis || analysis.status === 'missing') return 'Queued';
  if (analysis.status === 'insufficient_evidence') return 'Insufficient evidence';
  return 'No supported change';
}

function formatCredits(value: number): string {
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)} credits / 1%`;
}

function formatSignedPercent(value: number): string {
  const formatted = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(Math.abs(value));
  return `${value > 0 ? '+' : value < 0 ? '−' : ''}${formatted}%`;
}

function formatPercent(value: number): string {
  return new Intl.NumberFormat(undefined, { style: 'percent', maximumFractionDigits: 1 }).format(value);
}

function formatDate(value: string): string {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp)
    ? new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(timestamp)
    : value;
}

function formatDateTime(value: string): string {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp)
    ? new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(timestamp)
    : value;
}
