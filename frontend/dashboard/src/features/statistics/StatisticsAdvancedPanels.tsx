import type {
  StatisticsCohortRow,
  StatisticsGroupRow,
  StatisticsPayload,
} from '../../api/statistics';
import { Surface } from '../../design';
import styles from './StatisticsPage.module.css';

export function StatisticsAdvancedPanels({ payload }: { payload: StatisticsPayload }) {
  const activity = payload.activity;
  const cohorts = payload.cohorts;
  const attribution = payload.attribution;
  const breakdowns = payload.breakdowns ?? {};

  return (
    <>
      <section className={styles.grid}>
        <Surface>
          <h2>Longest uninterrupted periods</h2>
          <p className={styles.note}>
            Sessions use measured call duration plus capped idle gaps, not occupied clock buckets.
          </p>
          {(activity?.longest_work_periods ?? []).slice(0, 6).map(period => (
            <div className={styles.listRow} key={`${period.start_at}-${period.end_at}`}>
              <span>{new Date(period.start_at).toLocaleString()}</span>
              <strong>
                {duration(period.active_seconds)} active · {integer(period.turns)} turns ·{' '}
                {integer(period.calls)} calls
              </strong>
            </div>
          ))}
        </Surface>
        <Surface>
          <h2>Attribution concentration</h2>
          <dl className={styles.definitionList}>
            {Object.entries(attribution?.concentration ?? {}).map(([key, value]) => (
              <div key={key}>
                <dt>{label(key)}</dt>
                <dd>{percent(value)}</dd>
              </div>
            ))}
          </dl>
        </Surface>
      </section>

      {(cohorts?.plan_rate_rows.length ?? 0) > 0 ? (
        <Surface>
          <h2>Plan and rate periods</h2>
          <p className={styles.note}>
            Consecutive calls are segmented whenever the observed plan or timestamp-selected
            credit-rate revision changes.
          </p>
          <CohortTable rows={cohorts?.plan_rate_rows ?? []} />
        </Surface>
      ) : null}

      {(cohorts?.breakpoint_rows.length ?? 0) > 0 ? (
        <Surface>
          <h2>Before and after comparison</h2>
          <p className={styles.note}>
            Split at {cohorts?.comparison_at
              ? new Date(cohorts.comparison_at).toLocaleString()
              : 'the selected breakpoint'}.
          </p>
          <CohortTable rows={cohorts?.breakpoint_rows ?? []} />
        </Surface>
      ) : null}

      <section className={styles.grid}>
        <Surface>
          <h2>User versus subagent</h2>
          <GroupTable rows={breakdowns.initiator_kind ?? []} />
        </Surface>
        <Surface>
          <h2>Model × effort</h2>
          <GroupTable rows={breakdowns.model_effort ?? []} />
        </Surface>
        <Surface>
          <h2>Standard versus Fast</h2>
          <GroupTable rows={breakdowns.fast_mode ?? []} />
        </Surface>
        <Surface>
          <h2>Service tier</h2>
          <GroupTable rows={breakdowns.service_tier ?? []} />
        </Surface>
      </section>

      <section className={styles.grid}>
        <Surface>
          <h2>Initiator × model</h2>
          <GroupTable rows={breakdowns.initiator_model ?? []} />
        </Surface>
        <Surface>
          <h2>Initiator × active hour</h2>
          <GroupTable rows={breakdowns.initiator_active_hour ?? []} />
        </Surface>
      </section>

      <section className={styles.grid}>
        <Surface>
          <h2>Top projects</h2>
          <AttributionTable rows={attribution?.projects ?? []} />
        </Surface>
        <Surface>
          <h2>Top threads</h2>
          <AttributionTable rows={attribution?.threads ?? []} showProject />
        </Surface>
      </section>
    </>
  );
}

function CohortTable({ rows }: { rows: StatisticsCohortRow[] }) {
  return (
    <div className={styles.analysisTableWrap}>
      <table className={styles.analysisTable}>
        <thead>
          <tr>
            <th>Period</th>
            <th>Calls/day</th>
            <th>Active min/day</th>
            <th>Turns/day</th>
            <th>Credits/day</th>
            <th>Credits/call</th>
            <th>Credits/turn</th>
            <th>Credits/active h</th>
            <th>Weekly meter/day</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.label}-${row.since}-${index}`}>
              <td>
                <strong>{row.label}</strong>
                <small>
                  {date(row.since)} – {date(row.until)}
                </small>
              </td>
              <td>{number(row.calls_per_day)}</td>
              <td>{number(row.active_minutes_per_day)}</td>
              <td>{number(row.turns_per_day)}</td>
              <td>{number(row.credits_per_day)}</td>
              <td>{number(row.credits_per_call)}</td>
              <td>{number(row.credits_per_turn)}</td>
              <td>{number(row.credits_per_active_hour)}</td>
              <td>{percentPoints(row.secondary_meter_burn_percent_per_day)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GroupTable({ rows }: { rows: StatisticsGroupRow[] }) {
  return (
    <div className={styles.analysisTableWrap}>
      <table className={styles.analysisTable}>
        <thead>
          <tr>
            <th>Group</th>
            <th>Calls</th>
            <th>Credits</th>
            <th>Active min</th>
            <th>Turns</th>
            <th>Credits/active h</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr key={row.label}>
              <td><strong>{row.label}</strong></td>
              <td>{integer(row.calls)}</td>
              <td>{number(row.known_credits)}</td>
              <td>{number(row.active_minutes)}</td>
              <td>{integer(row.turns)}</td>
              <td>{number(row.credits_per_active_hour)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AttributionTable({
  rows,
  showProject = false,
}: {
  rows: StatisticsGroupRow[];
  showProject?: boolean;
}) {
  return (
    <div className={styles.analysisTableWrap}>
      <table className={styles.analysisTable}>
        <thead>
          <tr>
            <th>{showProject ? 'Thread' : 'Project'}</th>
            <th>Calls</th>
            <th>Credit share</th>
            <th>Active min</th>
            <th>Credits/active h</th>
            <th>Model mix</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.project ?? ''}-${row.label}-${index}`}>
              <td>
                <strong>{row.thread ?? row.label}</strong>
                {showProject && row.project ? <small>{row.project}</small> : null}
              </td>
              <td>{integer(row.calls)}</td>
              <td>{percent(row.credit_share)}</td>
              <td>{number(row.active_minutes)}</td>
              <td>{number(row.credits_per_active_hour)}</td>
              <td>{mix(row.model_mix)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function mix(rows: StatisticsGroupRow['model_mix']): string {
  return (rows ?? []).slice(0, 3).map(row => `${row.label} ${percent(row.share)}`).join(' · ') || '—';
}

function date(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString();
}

function duration(seconds: unknown): string {
  const value = finite(seconds);
  if (value === null) return '—';
  const hours = Math.floor(value / 3600);
  const minutes = Math.round((value % 3600) / 60);
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function number(value: unknown): string {
  const parsed = finite(value);
  return parsed === null
    ? '—'
    : parsed.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function integer(value: unknown): string {
  const parsed = finite(value);
  return parsed === null ? '—' : Math.round(parsed).toLocaleString();
}

function percent(value: unknown): string {
  const parsed = finite(value);
  return parsed === null ? '—' : `${(parsed * 100).toFixed(1)}%`;
}

function percentPoints(value: unknown): string {
  const parsed = finite(value);
  return parsed === null ? '—' : `${parsed.toFixed(2)} pp`;
}

function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function label(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, character => character.toUpperCase());
}
