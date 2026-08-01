import type { CallRow } from '../../api/types';
import { rowsToCsv, type CsvColumn } from '../shared/exportCsv';

export type CallsExportMode = 'compact-json' | 'compact-csv' | 'full-csv';

export const callsExportModeOptions: ReadonlyArray<{
  value: CallsExportMode;
  label: string;
}> = [
  { value: 'compact-json', label: 'Compact JSON' },
  { value: 'compact-csv', label: 'Compact CSV' },
  { value: 'full-csv', label: 'Full CSV' },
];

export type CallsExportScope = {
  source: 'live-api' | 'loaded-snapshot';
  filters: Record<string, string | boolean | null>;
  sort: string;
  direction: 'asc' | 'desc';
  includeArchived: boolean;
  matchedCallCount: number;
  completeResultSet: boolean;
  sourceRevision: string;
};

const compactColumns = [
  'time_second',
  'thread',
  'project',
  'model',
  'rated_model',
  'effort',
  'input_tokens',
  'cached_input_tokens',
  'output_tokens',
  'reasoning_output_tokens',
  'total_tokens',
  'usage_credits',
  'credit_confidence',
  'duration_seconds',
  'previous_gap_seconds',
  'initiator',
  'service_tier',
  'context_window_percent',
  'flags',
] as const;

export function buildCompactCallsExport(
  rows: CallRow[],
  scope: CallsExportScope,
  generatedAt = new Date(),
): Record<string, unknown> {
  const originMs = earliestTimestamp(rows);
  const dictionaries = {
    threads: new StringDictionary(),
    projects: new StringDictionary(),
    models: new StringDictionary(),
    ratedModels: new StringDictionary(),
    efforts: new StringDictionary(),
    creditConfidences: new StringDictionary(),
    initiators: new StringDictionary(),
    serviceTiers: new StringDictionary(),
    flags: new StringDictionary(),
  };
  const encodedRows = rows.map(row => {
    const timestamp = callTimestamp(row);
    return [
      timestamp === null || originMs === null
        ? null
        : Math.floor((timestamp - originMs) / 1000),
      dictionaries.threads.index(row.thread),
      dictionaries.projects.index(row.project),
      dictionaries.models.index(row.model),
      dictionaries.ratedModels.index(row.usageCreditModel),
      dictionaries.efforts.index(row.effort),
      finiteNumber(row.input),
      finiteNumber(row.cachedInput),
      finiteNumber(row.output),
      finiteNumber(row.reasoningOutput),
      finiteNumber(row.totalTokens),
      roundedNumber(row.credits, 6),
      dictionaries.creditConfidences.index(row.usageCreditConfidence),
      roundedNumber(row.durationSeconds, 3),
      roundedNumber(row.previousCallGapSeconds, 3),
      dictionaries.initiators.index(row.initiator),
      dictionaries.serviceTiers.index(row.serviceTier || row.usageCreditTier),
      roundedNumber(row.contextWindowPct, 3),
      callFlags(row).map(flag => dictionaries.flags.index(flag)),
    ];
  });
  const fetchedAt = uniqueStrings(rows.map(row => row.usageCreditFetchedAt));
  const liveResult = scope.source === 'live-api';
  const completeResultSet = liveResult && scope.completeResultSet;

  return {
    schema: 'codex-usage-tracker-calls-export-v2',
    generated_at: generatedAt.toISOString(),
    format: 'compact-json',
    privacy_mode: 'inherits-dashboard',
    scope: {
      source: scope.source,
      filters: scope.filters,
      sort: scope.sort,
      direction: scope.direction,
      include_archived: scope.includeArchived,
      matched_call_count: liveResult ? scope.matchedCallCount : null,
      exported_call_count: rows.length,
      complete_result_set: completeResultSet,
      truncated: liveResult ? !completeResultSet : null,
      source_revision: scope.sourceRevision || null,
    },
    pricing_basis: {
      usage_credit_fetched_at: fetchedAt,
    },
    layout: {
      time_origin: originMs === null ? null : isoSecond(originMs),
      time_unit: 'second',
      columns: [...compactColumns],
      conventions: {
        dictionary_index: 'zero-based index; null means unavailable',
        time_second: 'integer seconds from layout.time_origin',
        flags: 'array of zero-based indexes into dictionaries.flags',
        usage_credits: 'historically priced Codex credits when available',
      },
    },
    dictionaries: {
      threads: dictionaries.threads.values,
      projects: dictionaries.projects.values,
      models: dictionaries.models.values,
      rated_models: dictionaries.ratedModels.values,
      efforts: dictionaries.efforts.values,
      credit_confidences: dictionaries.creditConfidences.values,
      initiators: dictionaries.initiators.values,
      service_tiers: dictionaries.serviceTiers.values,
      flags: dictionaries.flags.values,
    },
    rows: encodedRows,
  };
}

export function buildCompactCallsCsv(rows: CallRow[]): string {
  return rowsToCsv(rows, compactCallCsvColumns);
}

export function downloadText(
  filename: string,
  text: string,
  contentType: string,
): void {
  const blob = new Blob([text], { type: contentType });
  const objectUrl =
    typeof URL.createObjectURL === 'function'
      ? URL.createObjectURL(blob)
      : `data:${contentType},${encodeURIComponent(text)}`;
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  if (objectUrl.startsWith('blob:') && typeof URL.revokeObjectURL === 'function') {
    URL.revokeObjectURL(objectUrl);
  }
}

const compactCallCsvColumns: Array<CsvColumn<CallRow>> = [
  { header: 'timestamp', value: row => row.eventTimestamp || row.callStartedAt || row.rawTime },
  { header: 'thread', value: row => row.thread },
  { header: 'project', value: row => row.project },
  { header: 'model', value: row => row.model },
  { header: 'rated_model', value: row => row.usageCreditModel },
  { header: 'effort', value: row => row.effort },
  { header: 'input_tokens', value: row => row.input },
  { header: 'cached_input_tokens', value: row => row.cachedInput },
  { header: 'output_tokens', value: row => row.output },
  { header: 'reasoning_output_tokens', value: row => row.reasoningOutput },
  { header: 'total_tokens', value: row => row.totalTokens },
  { header: 'usage_credits', value: row => numericCsv(row.credits, 6) },
  { header: 'credit_confidence', value: row => row.usageCreditConfidence },
  { header: 'duration_seconds', value: row => numericCsv(row.durationSeconds, 3) },
  { header: 'previous_gap_seconds', value: row => numericCsv(row.previousCallGapSeconds, 3) },
  { header: 'initiator', value: row => row.initiator },
  { header: 'service_tier', value: row => row.serviceTier || row.usageCreditTier },
  { header: 'context_window_percent', value: row => numericCsv(row.contextWindowPct, 3) },
  { header: 'flags', value: row => callFlags(row).join('|') },
];

class StringDictionary {
  readonly values: string[] = [];
  private readonly indexes = new Map<string, number>();

  index(value: string | null | undefined): number | null {
    const normalized = String(value ?? '').trim();
    if (!normalized) return null;
    const existing = this.indexes.get(normalized);
    if (existing !== undefined) return existing;
    const index = this.values.length;
    this.values.push(normalized);
    this.indexes.set(normalized, index);
    return index;
  }
}

function earliestTimestamp(rows: CallRow[]): number | null {
  let earliest: number | null = null;
  for (const row of rows) {
    const timestamp = callTimestamp(row);
    if (timestamp === null) continue;
    earliest = earliest === null ? timestamp : Math.min(earliest, timestamp);
  }
  return earliest === null ? null : Math.floor(earliest / 1000) * 1000;
}

function callTimestamp(row: CallRow): number | null {
  for (const value of [row.eventTimestamp, row.callStartedAt, row.rawTime]) {
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function callFlags(row: CallRow): string[] {
  return uniqueStrings([row.signal, ...row.efficiencyFlags])
    .filter(flag => flag.toLowerCase() !== 'aggregate');
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const normalized = String(value ?? '').trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function finiteNumber(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function roundedNumber(
  value: number | null | undefined,
  digits: number,
): number | null {
  const finite = finiteNumber(value);
  if (finite === null) return null;
  const scale = 10 ** digits;
  return Math.round(finite * scale) / scale;
}

function numericCsv(value: number | null | undefined, digits: number): string {
  const rounded = roundedNumber(value, digits);
  return rounded === null ? '' : String(rounded);
}

function isoSecond(timestamp: number): string {
  return new Date(timestamp).toISOString().replace('.000Z', 'Z');
}
