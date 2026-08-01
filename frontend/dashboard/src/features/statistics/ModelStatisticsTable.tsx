import { useMemo, useState } from 'react';

import type { StatisticsModelRow } from '../../api/statistics';
import { StatusBadge } from '../../design';
import styles from './StatisticsPage.module.css';

type ColumnPreset = 'summary' | 'tokens' | 'full';
type SortDirection = 'asc' | 'desc';
type ModelSortKey = keyof StatisticsModelRow;

type ModelColumn = {
  key: ModelSortKey;
  label: string;
  title: string;
  format: (value: StatisticsModelRow[ModelSortKey], row: StatisticsModelRow) => string;
};

const summaryColumns: ModelColumn[] = [
  column('calls', 'Calls', 'Number of calls logged for this model.', integer),
  column('call_share', 'Call share', 'Share of all selected calls.', ratio),
  creditColumn('known_credits', 'Credits', 'Known credits across priced calls.', decimal),
  creditColumn('credit_share', 'Credit share', 'Share of all known credits.', ratio),
  creditColumn('mean', 'Mean', 'Mean credits per priced call.', decimal),
  creditColumn('median', 'Median', 'Median credits per priced call.', decimal),
  creditColumn('p90', 'P90', '90th percentile credits per priced call.', decimal),
  creditColumn('p95', 'P95', '95th percentile credits per priced call.', decimal),
  column('priced_call_ratio', 'Coverage', 'Share of calls with a numeric credit estimate.', ratio),
];

const tokenColumns: ModelColumn[] = [
  column('calls', 'Calls', 'Number of calls logged for this model.', integer),
  column('avg_total_tokens_per_call', 'Avg total', 'Average total tokens per call.', integer),
  column('avg_input_tokens_per_call', 'Avg input', 'Average input tokens per call.', integer),
  column('avg_cached_input_tokens_per_call', 'Avg cached', 'Average cached input tokens per call.', integer),
  column('avg_uncached_input_tokens_per_call', 'Avg uncached', 'Average uncached input tokens per call.', integer),
  column('avg_output_tokens_per_call', 'Avg output', 'Average output tokens per call.', integer),
  column('avg_reasoning_tokens_per_call', 'Avg reasoning', 'Average reasoning-output tokens per call.', integer),
  column('weighted_cache_ratio', 'Cache ratio', 'Total cached input divided by total input tokens.', ratio),
  column('output_ratio', 'Output ratio', 'Total output tokens divided by total tokens.', ratio),
  column('reasoning_output_ratio', 'Reasoning ratio', 'Reasoning-output tokens divided by output tokens.', ratio),
  column('average_context_window_percent', 'Avg context', 'Mean recorded context-window utilization.', ratio),
];

const fullColumns: ModelColumn[] = [
  ...summaryColumns,
  ...tokenColumns.filter(item => item.key !== 'calls'),
  creditColumn(
    'credits_per_million_total_tokens',
    'Credits / 1M tokens',
    'Known credits normalized per million total tokens.',
    decimal,
  ),
];

const columnsByPreset: Record<ColumnPreset, ModelColumn[]> = {
  summary: summaryColumns,
  tokens: tokenColumns,
  full: fullColumns,
};

export function ModelStatisticsTable({
  rows,
  activeModel,
  onSelectModel,
}: {
  rows: StatisticsModelRow[];
  activeModel: string;
  onSelectModel: (model: string) => void;
}) {
  const [preset, setPreset] = useState<ColumnPreset>('summary');
  const [sortKey, setSortKey] = useState<ModelSortKey>('known_credits');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const columns = columnsByPreset[preset];
  const sortedRows = useMemo(
    () => sortModelRows(rows, sortKey, sortDirection),
    [rows, sortDirection, sortKey],
  );

  function updateSort(key: ModelSortKey) {
    if (key === sortKey) {
      setSortDirection(current => current === 'desc' ? 'asc' : 'desc');
      return;
    }
    setSortKey(key);
    setSortDirection(key === 'model' ? 'asc' : 'desc');
  }

  return (
    <>
      <div className={styles.modelTableHeader}>
        <div>
          <h2>Models</h2>
          <p className={styles.note}>
            Token ratios are weighted from aggregate token totals. Credit metrics use priced calls only.
          </p>
        </div>
        <label className={styles.columnControl}>
          Columns
          <select value={preset} onChange={event => setPreset(event.target.value as ColumnPreset)}>
            <option value="summary">Summary</option>
            <option value="tokens">Token composition</option>
            <option value="full">Full</option>
          </select>
        </label>
      </div>
      <div className={styles.tableWrap}>
        <table className={styles.modelTable}>
          <thead>
            <tr>
              <SortableHeader
                label="Model"
                title="Logged model label. Select a row to filter the full page."
                columnKey="model"
                activeKey={sortKey}
                direction={sortDirection}
                onSort={updateSort}
                sticky
              />
              {columns.map(item => (
                <SortableHeader
                  key={item.key}
                  label={item.label}
                  title={item.title}
                  columnKey={item.key}
                  activeKey={sortKey}
                  direction={sortDirection}
                  onSort={updateSort}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedRows.map(row => {
              const selected = activeModel === row.model;
              return (
                <tr key={row.model} className={selected ? styles.activeModelRow : undefined}>
                  <td className={styles.stickyColumn}>
                    <button
                      className={styles.linkButton}
                      type="button"
                      onClick={() => onSelectModel(selected ? '' : row.model)}
                    >
                      {modelLabel(row.model)}
                    </button>
                    {selected ? <StatusBadge tone="context">Filtered</StatusBadge> : null}
                  </td>
                  {columns.map(item => (
                    <td key={item.key}>{item.format(row[item.key], row)}</td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function SortableHeader({
  label,
  title,
  columnKey,
  activeKey,
  direction,
  onSort,
  sticky = false,
}: {
  label: string;
  title: string;
  columnKey: ModelSortKey;
  activeKey: ModelSortKey;
  direction: SortDirection;
  onSort: (key: ModelSortKey) => void;
  sticky?: boolean;
}) {
  const active = activeKey === columnKey;
  return (
    <th
      className={sticky ? styles.stickyColumn : undefined}
      aria-sort={active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'}
      title={title}
    >
      <button className={styles.sortButton} type="button" onClick={() => onSort(columnKey)}>
        {label}{active ? (direction === 'asc' ? ' ↑' : ' ↓') : ''}
      </button>
    </th>
  );
}

function column(
  key: ModelSortKey,
  label: string,
  title: string,
  formatter: (value: unknown) => string,
): ModelColumn {
  return { key, label, title, format: value => formatter(value) };
}

function creditColumn(
  key: ModelSortKey,
  label: string,
  title: string,
  formatter: (value: unknown) => string,
): ModelColumn {
  return {
    key,
    label,
    title,
    format: (value, row) => row.priced_calls > 0 ? formatter(value) : '—',
  };
}

function sortModelRows(
  rows: StatisticsModelRow[],
  key: ModelSortKey,
  direction: SortDirection,
): StatisticsModelRow[] {
  return [...rows].sort((left, right) => {
    const leftValue = sortableValue(left[key]);
    const rightValue = sortableValue(right[key]);
    if (leftValue === null && rightValue === null) return left.model.localeCompare(right.model);
    if (leftValue === null) return 1;
    if (rightValue === null) return -1;
    const comparison = typeof leftValue === 'string' && typeof rightValue === 'string'
      ? leftValue.localeCompare(rightValue)
      : Number(leftValue) - Number(rightValue);
    return direction === 'asc' ? comparison : -comparison;
  });
}

function sortableValue(value: unknown): number | string | null {
  if (typeof value === 'string') return value.trim().toLocaleLowerCase();
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  return null;
}

function modelLabel(value: string): string {
  return value.trim() || 'Unknown model';
}

function decimal(value: unknown): string {
  return formatNumber(value, 2);
}

function integer(value: unknown): string {
  return formatNumber(value, 0);
}

function ratio(value: unknown): string {
  const parsed = finiteNumber(value);
  return parsed === null ? '—' : `${(parsed * 100).toFixed(1)}%`;
}

function formatNumber(value: unknown, digits: number): string {
  const parsed = finiteNumber(value);
  return parsed === null
    ? '—'
    : parsed.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function finiteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
