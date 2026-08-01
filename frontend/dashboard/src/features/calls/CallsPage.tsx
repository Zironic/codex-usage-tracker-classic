import { useInfiniteQuery } from '@tanstack/react-query';
import type { ColumnDef, SortingState } from '@tanstack/react-table';
import { useEffect, useMemo, type ReactNode } from 'react';
import type { CallRow, ContextRuntime, DashboardModel } from '../../api/types';
import {
  callsInfiniteQueryOptions,
  loadCallsPage,
} from '../../data/exploreQueries';
import { csvDateStamp, downloadCsv, rowsToCsv } from '../shared/exportCsv';
import { copyText } from '../shared/copyText';
import { presetLabel } from '../shared/investigationPresets';
import { callActionColumn, callColumns, callCsvColumns } from '../shared/tables';
import { buildCallsFilterSummary, type CallsSortKey } from './callFilterSummary';
import {
  buildCallsViewLink,
  defaultCallsSortDirection,
  detailFirstSelectedCallId,
  readCallsSearchParam,
  readCallsSortKeyParam,
  readConfidenceFilterParam,
  readDateInputParam,
  readSortDirectionParam,
  readSourceFilterParam,
  readTimeFilterParam,
} from './callsUrlState';
import {
  buildCompactCallsCsv,
  buildCompactCallsExport,
  downloadText,
  type CallsExportMode,
  type CallsExportScope,
} from './callsExport';
import { filterCalls, sortCalls } from './callsFilterSort';
import { callsEndpointState } from './callsEndpointState';
import { CallsExplorerView } from './CallsExplorerView';
import { callsTablePageSize, useCallsExplorerControls } from './useCallsExplorerControls';
import { useFocusedCallFilterOptions } from './useFocusedCallFilterOptions';

export type CallsPageProps = {
  model: DashboardModel;
  globalQuery: string;
  activePreset: string;
  onRefresh: () => void;
  contextRuntime: ContextRuntime;
  onContextApiEnabledChange: (enabled: boolean) => void;
  onOpenInvestigator: (recordId: string) => void;
  onCopyCallLink: (recordId: string) => void;
  includeArchived?: boolean;
  sourceKey?: string;
  sourceRevision?: string;
  scopeSince?: string | null;
  focusedEndpointsEnabled?: boolean;
  workspaceSwitcher?: ReactNode;
};

export function callsForCurrentUrl(calls: CallRow[], globalQuery = '', activePreset = ''): CallRow[] {
  const sortKey = readCallsSortKeyParam();
  return sortCalls(
    filterCalls(calls, {
      globalQuery,
      localQuery: readCallsSearchParam('call_q'),
      modelFilter: readCallsSearchParam('model') || 'all',
      effortFilter: readCallsSearchParam('effort') || 'all',
      confidenceFilter: readConfidenceFilterParam(),
      sourceFilter: readSourceFilterParam(),
      timeFilter: readTimeFilterParam(),
      dateStart: readDateInputParam('from'),
      dateEnd: readDateInputParam('to'),
      activePreset,
    }),
    sortKey,
    readSortDirectionParam(sortKey),
  );
}

const callsSortToColumnId: Record<CallsSortKey, string> = {
  time: 'time',
  duration: 'duration',
  gap: 'previousCallGap',
  attention: 'signal',
  thread: 'thread',
  initiator: 'initiator',
  model: 'model',
  effort: 'effort',
  total: 'totalTokens',
  cached: 'cachedInput',
  uncached: 'uncachedInput',
  output: 'output',
  reasoning: 'reasoningOutput',
  cost: 'cost',
  usage: 'credits',
  cache: 'cachedPct',
  context: 'contextWindowPct',
};
const callsColumnIdToSort = Object.fromEntries(Object.entries(callsSortToColumnId).map(([sortKey, columnId]) => [columnId, sortKey])) as Record<string, CallsSortKey>;
export function CallsPage({
  model,
  globalQuery,
  activePreset,
  onRefresh,
  contextRuntime,
  onContextApiEnabledChange,
  onOpenInvestigator,
  onCopyCallLink,
  includeArchived = false,
  sourceKey,
  sourceRevision = '',
  scopeSince = null,
  focusedEndpointsEnabled = import.meta.env.MODE !== 'test',
  workspaceSwitcher,
}: CallsPageProps) {
  const controls = useCallsExplorerControls(model, globalQuery);
  const {
    localQuery,
    modelFilter,
    effortFilter,
    confidenceFilter,
    sourceFilter,
    timeFilter,
    dateStart,
    dateEnd,
    sortKey,
    setSortKey,
    sortDirection,
    setSortDirection,
    gridPreferences,
    density,
    selectedCallId,
    setSelectedCallId,
    visibleCallRows,
    setVisibleCallRows,
    exportStatus,
    setExportStatus,
    filterStatus,
    detailsExpanded,
    searchInputRef,
    modelOptions,
    effortOptions,
    sourceCoverage,
    dateRangeStatus,
    resetCallTablePage,
    updateLocalQuery,
    updateModelFilter,
    updateEffortFilter,
    updateConfidenceFilter,
    updateSourceFilter,
    updateTimeFilter,
    updateDateStart,
    updateDateEnd,
    updateSortKey,
    updateSortDirection,
    clearCallFilters,
    toggleCallDetails,
  } = controls;
  const interactiveCallColumns = useMemo<Array<ColumnDef<CallRow, unknown>>>(() => [...callColumns, callActionColumn({ onOpenInvestigator, onCopyCallLink })], [onCopyCallLink, onOpenInvestigator]);
  const endpointState = useMemo(
    () =>
      callsEndpointState({
        runtime: contextRuntime,
        enabled: focusedEndpointsEnabled,
        activePreset,
        sourceFilter,
        sortKey,
        scopeSince,
        timeFilter,
        dateStart,
        dateEnd,
        confidenceFilter,
        globalQuery,
        localQuery,
        modelFilter,
        effortFilter,
      }),
    [activePreset, confidenceFilter, contextRuntime, dateEnd, dateStart, effortFilter, focusedEndpointsEnabled, globalQuery, localQuery, modelFilter, sortKey, sourceFilter, scopeSince, timeFilter],
  );
  const focusedCallsRequest = useMemo(
    () => ({
      runtime: contextRuntime,
      includeArchived,
      sourceKey,
      sourceRevision,
      filters: endpointState.filters,
      sort: endpointState.sort,
      direction: sortDirection,
      pageSize: callsTablePageSize,
    }),
    [contextRuntime, endpointState.filters, endpointState.sort, includeArchived, sortDirection, sourceKey, sourceRevision],
  );
  const focusedCallsQuery = useInfiniteQuery({
    ...callsInfiniteQueryOptions(focusedCallsRequest),
    enabled: endpointState.enabled,
    placeholderData: (previous) => previous,
  });
  const locallyFilteredCalls = useMemo(
    () =>
      filterCalls(model.calls, {
        globalQuery,
        localQuery,
        modelFilter,
        effortFilter,
        confidenceFilter,
        sourceFilter,
        timeFilter,
        dateStart,
        dateEnd,
        activePreset,
      }),
    [activePreset, confidenceFilter, dateEnd, dateStart, effortFilter, globalQuery, localQuery, model.calls, modelFilter, sourceFilter, timeFilter],
  );
  const localSortedCalls = useMemo(() => sortCalls(locallyFilteredCalls, sortKey, sortDirection), [locallyFilteredCalls, sortDirection, sortKey]);
  const focusedCalls = useMemo(() => focusedCallsQuery.data?.pages.flatMap((page) => page.rows) ?? [], [focusedCallsQuery.data]);
  const focusedFilterOptions = useFocusedCallFilterOptions({
    calls: focusedCalls,
    modelOptions,
    effortOptions,
    focusedModelOptions: focusedCallsQuery.data?.pages[0]?.filterOptions.models ?? [],
    focusedEffortOptions: focusedCallsQuery.data?.pages[0]?.filterOptions.efforts ?? [],
    selectedModel: modelFilter,
    selectedEffort: effortFilter,
  });
  const usingFocusedCalls = endpointState.enabled && Boolean(focusedCallsQuery.data);
  const sortedCalls = useMemo(() => (usingFocusedCalls ? sortCalls(focusedCalls, sortKey, sortDirection) : localSortedCalls), [focusedCalls, localSortedCalls, sortDirection, sortKey, usingFocusedCalls]);
  const totalMatchedCalls = usingFocusedCalls ? (focusedCallsQuery.data?.pages[0]?.totalMatchedRows ?? sortedCalls.length) : model.calls.length;
  const tableSubtitle = useMemo(
    () =>
      buildCallsFilterSummary({
        shownCount: sortedCalls.length,
        totalCount: totalMatchedCalls,
        localQuery,
        globalQuery,
        modelFilter,
        effortFilter,
        confidenceFilter,
        sourceFilter,
        timeFilter,
        dateRangeStatus,
        activePresetLabel: activePreset ? presetLabel(activePreset) : '',
      }),
    [activePreset, confidenceFilter, dateRangeStatus, effortFilter, globalQuery, localQuery, modelFilter, sortedCalls.length, sourceFilter, timeFilter, totalMatchedCalls],
  );
  const tableSorting = useMemo<SortingState>(() => [{ id: callsSortToColumnId[sortKey], desc: sortDirection === 'desc' }], [sortDirection, sortKey]);
  const selectedCall = selectedCallId === detailFirstSelectedCallId ? (sortedCalls[0] ?? null) : (sortedCalls.find((call) => call.id === selectedCallId) ?? sortedCalls[0] ?? null);
  const selectedRecordId = selectedCall && (selectedCall.id === selectedCallId || selectedCallId === detailFirstSelectedCallId) ? selectedCall.id : '';

  useEffect(() => {
    if (selectedCallId === detailFirstSelectedCallId && selectedRecordId) {
      setSelectedCallId(selectedRecordId);
    }
  }, [selectedCallId, selectedRecordId]);

  useEffect(() => {
    const url = buildCallsViewLink({
      localQuery,
      modelFilter,
      effortFilter,
      confidenceFilter,
      sourceFilter,
      timeFilter,
      dateStart,
      dateEnd,
      sortKey,
      sortDirection,
      density,
      selectedRecordId,
      visibleRowCount: visibleCallRows,
      pageSize: callsTablePageSize,
    });
    if (url.toString() !== window.location.href) {
      window.history.replaceState(null, '', url);
    }
  }, [confidenceFilter, dateEnd, dateStart, density, effortFilter, localQuery, modelFilter, selectedRecordId, sortDirection, sortKey, sourceFilter, timeFilter, visibleCallRows]);

  async function exportCalls(mode: CallsExportMode): Promise<void> {
    setExportStatus('Preparing complete filtered export…');
    try {
      const livePage = endpointState.enabled
        ? await loadCallsPage(
            { ...focusedCallsRequest, pageSize: 0 },
            0,
            0,
          )
        : null;
      const exportRows = livePage?.rows ?? sortedCalls;
      const matchedCallCount = livePage?.totalMatchedRows ?? exportRows.length;
      const scope: CallsExportScope = {
        source: livePage ? 'live-api' : 'loaded-snapshot',
        filters: exportFilterSummary(),
        sort: endpointState.sort,
        direction: sortDirection,
        includeArchived,
        matchedCallCount,
        completeResultSet: livePage
          ? !livePage.hasMore && exportRows.length === matchedCallCount
          : true,
        sourceRevision,
      };
      const date = csvDateStamp();
      if (mode === 'compact-json') {
        const payload = buildCompactCallsExport(exportRows, scope);
        downloadText(
          `codex-calls-compact-${date}.json`,
          JSON.stringify(payload),
          'application/json;charset=utf-8',
        );
      } else if (mode === 'compact-csv') {
        downloadCsv(
          `codex-calls-compact-${date}.csv`,
          buildCompactCallsCsv(exportRows),
        );
      } else {
        downloadCsv(
          `codex-calls-full-${date}.csv`,
          rowsToCsv(exportRows, callCsvColumns),
        );
      }
      const sourceLabel = livePage ? 'complete filtered result' : 'loaded snapshot';
      setExportStatus(`Exported ${exportRows.length.toLocaleString()} calls from ${sourceLabel}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown export error';
      setExportStatus(`Export failed: ${message}`);
    }
  }

  function exportFilterSummary(): Record<string, string | boolean | null> {
    return {
      query: [globalQuery.trim(), localQuery.trim()].filter(Boolean).join(' ') || null,
      model: modelFilter === 'all' ? null : modelFilter,
      effort: effortFilter === 'all' ? null : effortFilter,
      confidence: confidenceFilter === 'all' ? null : confidenceFilter,
      source: sourceFilter === 'all' ? null : sourceFilter,
      time: timeFilter === 'all' ? null : timeFilter,
      date_start: dateStart || null,
      date_end: dateEnd || null,
      active_preset: activePreset || null,
      include_archived: includeArchived,
    };
  }

  async function copyCallsViewLink() {
    try {
      const url = buildCallsViewLink({
        localQuery,
        modelFilter,
        effortFilter,
        confidenceFilter,
        sourceFilter,
        timeFilter,
        dateStart,
        dateEnd,
        sortKey,
        sortDirection,
        density,
        selectedRecordId,
        visibleRowCount: visibleCallRows,
        pageSize: callsTablePageSize,
      });
      const copied = await copyText(url.toString());
      if (!copied) {
        throw new Error('Clipboard unavailable');
      }
      setExportStatus('Copied Calls view link');
    } catch {
      setExportStatus('Copy unavailable in browser');
    }
  }

  function updateTableSorting(updater: SortingState | ((old: SortingState) => SortingState)) {
    const nextSorting = typeof updater === 'function' ? updater(tableSorting) : updater;
    const nextSort = callsColumnIdToSort[nextSorting[0]?.id ?? ''] ?? 'time';
    const isChangingSortKey = nextSort !== sortKey;
    setSortKey(nextSort);
    setSortDirection(isChangingSortKey ? defaultCallsSortDirection(nextSort) : nextSorting[0]?.desc ? 'desc' : 'asc');
    resetCallTablePage();
  }

  async function loadMoreFocusedCalls() {
    if (!focusedCallsQuery.hasNextPage || focusedCallsQuery.isFetchingNextPage) return;
    await focusedCallsQuery.fetchNextPage();
    setVisibleCallRows((current) => current + callsTablePageSize);
  }

  return (
    <CallsExplorerView
      model={model}
      header={{
        workspaceSwitcher,
        canExport: Boolean(sortedCalls.length),
        onExport: exportCalls,
        onCopyView: copyCallsViewLink,
        onRefresh,
      }}
      filters={{
        searchInputRef,
        localQuery,
        modelFilter,
        effortFilter,
        confidenceFilter,
        sourceFilter,
        timeFilter,
        dateStart,
        dateEnd,
        sortKey,
        sortDirection,
        modelOptions: focusedFilterOptions.models,
        effortOptions: focusedFilterOptions.efforts,
        sourceCoverage,
        dateRangeStatus,
        onLocalQueryChange: updateLocalQuery,
        onModelFilterChange: updateModelFilter,
        onEffortFilterChange: updateEffortFilter,
        onConfidenceFilterChange: updateConfidenceFilter,
        onSourceFilterChange: updateSourceFilter,
        onTimeFilterChange: updateTimeFilter,
        onDateStartChange: updateDateStart,
        onDateEndChange: updateDateEnd,
        onSortKeyChange: updateSortKey,
        onSortDirectionChange: updateSortDirection,
        onClear: clearCallFilters,
      }}
      table={{
        activePreset,
        exportStatus,
        filterStatus,
        subtitle: tableSubtitle,
        focused: usingFocusedCalls,
        focusedReason: endpointState.reason,
        isFetching: focusedCallsQuery.isFetching,
        isFetchingNextPage: focusedCallsQuery.isFetchingNextPage,
        hasNextPage: Boolean(focusedCallsQuery.hasNextPage),
        detailsExpanded,
        calls: sortedCalls,
        totalMatchedCalls,
        columns: interactiveCallColumns,
        sorting: tableSorting,
        gridPreferences,
        selectedCall,
        onSortingChange: updateTableSorting,
        onSelectCall: setSelectedCallId,
        onLoadMore: loadMoreFocusedCalls,
        onToggleDetails: toggleCallDetails,
      }}
      inspector={{
        contextRuntime,
        includeArchived,
        sourceRevision,
        hydrateThreadCalls: focusedEndpointsEnabled,
        onContextApiEnabledChange,
        onOpenInvestigator,
        onCopyCallLink,
      }}
    />
  );
}
