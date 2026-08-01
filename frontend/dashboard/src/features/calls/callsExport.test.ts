import { describe, expect, it } from 'vitest';

import type { CallRow } from '../../api/types';
import {
  buildCompactCallsCsv,
  buildCompactCallsExport,
  type CallsExportScope,
} from './callsExport';

type ResearchCallRow = CallRow & {
  plan: string;
  rateRevision: string;
};

const scope: CallsExportScope = {
  source: 'live-api',
  filters: { model: 'gpt-5.6-luna', include_archived: false },
  sort: 'time',
  direction: 'asc',
  includeArchived: false,
  matchedCallCount: 2,
  completeResultSet: true,
  sourceRevision: 'revision-1',
};

describe('compact calls export', () => {
  it('dictionary-encodes repeated strings, research dimensions, and timestamps', () => {
    const payload = buildCompactCallsExport(
      [
        call({
          id: 'secret-record-1',
          eventTimestamp: '2026-08-01T08:00:00Z',
          thread: 'Tracker work',
          credits: 12.3456789,
          signal: 'low-cache',
        }),
        call({
          id: 'secret-record-2',
          eventTimestamp: '2026-08-01T08:00:07Z',
          thread: 'Tracker work',
          credits: 1.5,
          signal: 'low-cache',
        }),
      ],
      scope,
      new Date('2026-08-01T09:00:00Z'),
    );

    expect(payload.schema).toBe('codex-usage-tracker-calls-export-v2');
    expect(payload.layout).toMatchObject({
      time_origin: '2026-08-01T08:00:00Z',
      time_unit: 'second',
    });
    expect(payload.dictionaries).toMatchObject({
      threads: ['Tracker work'],
      projects: ['codex-usage-tracker'],
      models: ['gpt-5.6-luna'],
      plans: ['prolite'],
      rate_revisions: ['2026-07-14'],
      subagent_types: ['worker'],
      flags: ['low-cache'],
    });
    const rows = payload.rows as unknown[][];
    expect(rows[0][0]).toBe(0);
    expect(rows[1][0]).toBe(7);
    expect(rows[0][1]).toBe(0);
    expect(rows[1][1]).toBe(0);
    expect(rows[0][8]).toBe(false);
    expect(rows[0][9]).toBe(0);
    expect(rows[1][9]).toBe(0);
    expect(rows[0][16]).toBe(12.345679);
    expect(rows[0][23]).toEqual([0]);
  });

  it('omits local record, session, turn, source-file, and cwd identifiers', () => {
    const payload = buildCompactCallsExport([call({})], scope);
    const encoded = JSON.stringify(payload);

    expect(encoded).not.toContain('secret-record');
    expect(encoded).not.toContain('secret-session');
    expect(encoded).not.toContain('secret-turn');
    expect(encoded).not.toContain('C:/private/project');
    expect(encoded).not.toContain('secret.jsonl');
  });

  it('does not claim completeness for a bounded loaded snapshot', () => {
    const payload = buildCompactCallsExport([call({})], {
      ...scope,
      source: 'loaded-snapshot',
      matchedCallCount: 1,
      completeResultSet: true,
    });

    expect(payload.scope).toMatchObject({
      source: 'loaded-snapshot',
      matched_call_count: null,
      exported_call_count: 1,
      complete_result_set: false,
      truncated: null,
    });
  });

  it('writes a concise flat CSV with opaque turn groups', () => {
    const csv = buildCompactCallsCsv([call({})]);
    const [header, row] = csv.split('\n');

    expect(header.split(',')).toHaveLength(24);
    expect(header).toContain('plan');
    expect(header).toContain('rate_revision');
    expect(header).toContain('turn_group');
    expect(header).toContain('subagent_type');
    expect(header).not.toContain('session_id');
    expect(header).not.toContain('turn_id');
    expect(header).not.toContain('source_file');
    expect(row).toContain('gpt-5.6-luna');
    expect(row).not.toContain('secret-turn');
  });
});

function call(overrides: Partial<ResearchCallRow>): ResearchCallRow {
  return {
    id: 'secret-record',
    rawTime: '2026-08-01T08:00:00Z',
    eventTimestamp: '2026-08-01T08:00:00Z',
    callStartedAt: '2026-08-01T08:00:00Z',
    time: '08:00',
    thread: 'Tracker work',
    model: 'gpt-5.6-luna',
    effort: 'medium',
    plan: 'prolite',
    rateRevision: '2026-07-14',
    input: 1000,
    output: 100,
    reasoningOutput: 50,
    totalTokens: 1100,
    cachedInput: 700,
    uncachedInput: 300,
    cachedPct: 70,
    cost: 0.01,
    standardCost: 0.01,
    priorityCost: null,
    pricingServiceTier: 'standard',
    billingBasis: 'token_rates',
    costSemantics: 'estimated',
    credits: 5,
    standardUsageCredits: 5,
    fastUsageCredits: null,
    serviceTier: 'standard',
    fast: false,
    serviceTierSource: 'log',
    serviceTierConfidence: 'exact',
    fastProxyCandidate: false,
    usageCreditMultiplier: 1,
    usageCreditMultiplierSource: 'standard',
    usageCreditMultiplierSourceUrl: '',
    usageCreditMultiplierFetchedAt: '',
    usageCreditMultiplierConfidence: 'exact',
    duration: '1m',
    durationSeconds: 60,
    previousCallGap: '5m',
    previousCallEventTimestamp: '2026-08-01T07:55:00Z',
    previousCallGapSeconds: 300,
    initiator: 'user',
    initiatorReason: 'user_message',
    initiatorConfidence: 'high',
    usageCreditConfidence: 'exact',
    usageCreditModel: 'gpt-5.6-luna',
    usageCreditSource: 'OpenAI Codex rate card',
    usageCreditFetchedAt: '2026-08-01T06:43:00Z',
    usageCreditTier: 'standard',
    usageCreditNote: '',
    pricingModel: 'gpt-5.6-luna',
    pricingEstimated: false,
    signal: 'low-cache',
    recommendation: 'Increase cache reuse',
    tags: [],
    sessionId: 'secret-session',
    turnId: 'secret-turn',
    parentSessionId: '',
    parentSessionUpdatedAt: '',
    parentThread: '',
    threadAttachmentLabel: '',
    threadSource: 'subagent',
    subagentType: 'worker',
    agentRole: '',
    agentNickname: '',
    project: 'codex-usage-tracker',
    projectRelativeCwd: 'private/project',
    projectTags: [],
    cwd: 'C:/private/project',
    sourceFile: 'C:/private/secret.jsonl',
    lineNumber: 42,
    gitBranch: 'feature/private',
    gitRemoteLabel: 'private',
    gitRemoteHash: 'secret-hash',
    contextWindowPct: 25,
    modelContextWindow: 200000,
    cumulativeTotalTokens: 100000,
    estimatedCacheSavings: 0.2,
    efficiencyFlags: ['low-cache'],
    ...overrides,
  };
}
