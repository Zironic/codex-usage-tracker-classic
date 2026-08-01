import type { CallRow, DashboardModel } from '../../api/types';
import type { LoadWindow } from '../../data/dataScope';
import { StatisticsPage } from '../statistics/StatisticsPage';

type ReportsPageProps = {
  model: DashboardModel;
  refreshState: string;
  includeArchived: boolean;
  loadWindow: LoadWindow;
  loadLimit: number;
  sourceKey?: string;
  sourceRevision: string;
  onOpenInvestigator: (recordId: string) => void;
  onCopyCallLink: (recordId: string) => void;
};

export function reportCallsForCurrentUrl(model: DashboardModel): CallRow[] {
  void model;
  return [];
}

export function ReportsPage({
  model,
  includeArchived,
  sourceRevision,
  onOpenInvestigator,
}: ReportsPageProps) {
  return (
    <StatisticsPage
      contextRuntime={model.contextRuntime}
      historyScope={includeArchived ? 'all' : 'active'}
      sourceRevision={sourceRevision}
      refreshing={false}
      onRefresh={() => window.location.reload()}
      onOpenInvestigator={onOpenInvestigator}
    />
  );
}
