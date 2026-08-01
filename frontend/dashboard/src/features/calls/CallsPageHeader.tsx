import { Copy, Download, RefreshCw } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import {
  callsExportModeOptions,
  type CallsExportMode,
} from './callsExport';
import styles from './CallsPage.module.css';

type CallsPageHeaderProps = {
  workspaceSwitcher?: ReactNode;
  canExport: boolean;
  onExport(mode: CallsExportMode): Promise<void>;
  onCopyView(): void;
  onRefresh(): void;
};

export function CallsPageHeader({
  workspaceSwitcher,
  canExport,
  onExport,
  onCopyView,
  onRefresh,
}: CallsPageHeaderProps) {
  const [exportMode, setExportMode] = useState<CallsExportMode>('compact-json');
  const [exporting, setExporting] = useState(false);

  async function handleExport() {
    if (exporting || !canExport) return;
    setExporting(true);
    try {
      await onExport(exportMode);
    } finally {
      setExporting(false);
    }
  }

  return (
    <header className={styles.pageHeader}>
      <div>
        <p className={styles.eyebrow}>Evidence explorer</p>
        <h1>Calls</h1>
        <p>Find expensive, cold, or context-heavy calls and move directly into their evidence.</p>
      </div>
      <div className={styles.headerActions}>
        {workspaceSwitcher}
        <select
          className={styles.exportModeSelect}
          aria-label="Calls export format"
          value={exportMode}
          onChange={event => setExportMode(event.target.value as CallsExportMode)}
          disabled={exporting}
        >
          {callsExportModeOptions.map(option => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <button
          className="toolbar-button"
          type="button"
          onClick={() => void handleExport()}
          disabled={!canExport || exporting}
        >
          <Download size={16} />
          {exporting ? 'Exporting…' : 'Export'}
        </button>
        <button className="toolbar-button" type="button" onClick={onCopyView}>
          <Copy size={16} />
          Copy view
        </button>
        <button className="primary-button" type="button" onClick={onRefresh}>
          <RefreshCw size={16} />
          Refresh
        </button>
      </div>
    </header>
  );
}
