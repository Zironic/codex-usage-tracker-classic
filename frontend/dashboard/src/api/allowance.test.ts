import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ContextRuntime } from './types';
import {
  loadAllowanceDiagnostics,
  loadAllowanceEvidenceExport,
  loadAllowanceHistory,
} from './allowance';

const runtime: ContextRuntime = {
  apiToken: 'local-allowance-token',
  contextApiEnabled: false,
  fileMode: false,
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('allowance API', () => {
  it('loads uncapped local history with record identifiers for dashboard links', async () => {
    const payload = {
      schema: 'codex-usage-tracker-allowance-history-v1',
      generated_at: '2026-07-10T12:00:00Z',
      privacy_mode: 'normal',
      include_archived: true,
      window_kind: null,
      row_count: 0,
      rows: [],
      notes: [],
    };
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(payload));

    await expect(loadAllowanceHistory(runtime, { includeArchived: true, limit: 0 })).resolves.toEqual(payload);

    const [input, init] = fetchMock.mock.calls[0];
    const url = new URL(String(input), 'http://localhost');
    expect(url.pathname).toBe('/api/allowance/history');
    expect(url.searchParams.get('limit')).toBe('0');
    expect(url.searchParams.get('include_archived')).toBe('1');
    expect(url.searchParams.get('privacy_mode')).toBe('normal');
    expect(url.searchParams.has('_')).toBe(false);
    expect(new Headers(init?.headers).get('X-Codex-Usage-Token')).toBe(runtime.apiToken);
  });

  it('defaults evidence export to minute-resolution compact v3', async () => {
    const diagnostics = { schema: 'codex-usage-tracker-allowance-diagnostics-v1' };
    const exported = {
      schema: 'codex-usage-tracker-allowance-evidence-export-v3',
      privacy_mode: 'strict',
    };
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse(diagnostics))
      .mockResolvedValueOnce(jsonResponse(exported));

    await loadAllowanceDiagnostics(runtime, { limit: null, windowKind: 'weekly' });
    await expect(loadAllowanceEvidenceExport(runtime, { limit: null })).resolves.toEqual(exported);

    const diagnosticsUrl = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost');
    const exportUrl = new URL(String(fetchMock.mock.calls[1][0]), 'http://localhost');
    expect(diagnosticsUrl.searchParams.get('limit')).toBe('None');
    expect(diagnosticsUrl.searchParams.get('window_kind')).toBe('weekly');
    expect(exportUrl.searchParams.get('limit')).toBe('None');
    expect(exportUrl.searchParams.get('format')).toBe('compact');
    expect(exportUrl.searchParams.has('privacy_mode')).toBe(false);
  });

  it('can request the date-only compact v2 export', async () => {
    const exported = {
      schema: 'codex-usage-tracker-allowance-evidence-export-v2',
      privacy_mode: 'strict',
    };
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(exported));

    await expect(loadAllowanceEvidenceExport(runtime, {
      format: 'compact-v2',
      limit: null,
    })).resolves.toEqual(exported);

    const url = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost');
    expect(url.searchParams.get('format')).toBe('compact-v2');
  });

  it('can request the historical verbose v1 export', async () => {
    const exported = {
      schema: 'codex-usage-tracker-allowance-evidence-export-v1',
      privacy_mode: 'strict',
    };
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(exported));

    await expect(loadAllowanceEvidenceExport(runtime, {
      format: 'verbose',
      limit: null,
    })).resolves.toEqual(exported);

    const url = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost');
    expect(url.searchParams.get('format')).toBe('verbose');
  });

  it('rejects incompatible schemas and file mode before the payload is used', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ schema: 'future-v4' }));

    await expect(loadAllowanceDiagnostics(runtime)).rejects.toThrow('unsupported schema');
    await expect(loadAllowanceHistory({ ...runtime, fileMode: true })).rejects.toThrow('localhost dashboard server');
  });
});

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  } as Response;
}
