'use client';

import { useEffect, useState } from 'react';

import { formatGen, shortAddr, timeAgo } from '@/lib/format';
import type { ReportInfo } from '@/lib/types';

interface ReportsTimelineProps {
  reports: ReportInfo[] | undefined;
}

const VERDICT_CLASS: Record<ReportInfo['verdict'], string> = {
  SUPPORTED: 'ok',
  NOT_SUPPORTED: 'danger',
  INCONCLUSIVE: 'warn',
};

const VERDICT_COLOR: Record<ReportInfo['verdict'], string> = {
  SUPPORTED: 'var(--ok)',
  NOT_SUPPORTED: 'var(--danger)',
  INCONCLUSIVE: 'var(--warn)',
};

export function ReportsTimeline({ reports }: ReportsTimelineProps) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 15000);
    return () => clearInterval(id);
  }, []);

  return (
    <section className="card" aria-labelledby="reports-title">
      <h2 className="card-title" id="reports-title">
        <span>Judgment history</span>
        <span className="mono" style={{ textTransform: 'none', letterSpacing: 0 }}>
          newest first
        </span>
      </h2>

      {!reports || reports.length === 0 ? (
        <div className="empty">
          No reports yet. Every halt and every clear ever judged for this vault will appear here, with the
          validators&apos; verdict and reasoning.
        </div>
      ) : (
        <div className="timeline">
          {reports.map((r) => (
            <article key={r.report_id} className={`report ${r.verdict.toLowerCase()}`}>
              <header className="report-head">
                <div className="row">
                  <span className={r.action === 'HALT' ? 'chip danger' : 'chip accent'}>
                    {r.action === 'HALT' ? 'Halt request' : 'Clear request'}
                  </span>
                  <span className={`chip ${VERDICT_CLASS[r.verdict]}`}>{r.verdict.replace('_', ' ')}</span>
                </div>
                <span className="mono" style={{ fontSize: 12, color: 'var(--dim)' }}>
                  #{r.report_id} - {timeAgo(r.decided_epoch, nowMs)}
                </span>
              </header>

              <p className="report-claim">{r.claim}</p>
              {r.reasoning && <p className="report-reasoning">{r.reasoning}</p>}
              {r.fetch_note && <p className="report-reasoning">{r.fetch_note}</p>}

              <div className="report-meta">
                <span className="row" style={{ gap: 8 }}>
                  confidence
                  <span className="meter" aria-hidden="true">
                    <span style={{ width: `${r.confidence}%`, background: VERDICT_COLOR[r.verdict] }} />
                  </span>
                  {r.confidence}%
                </span>
                <span>
                  bond {formatGen(r.bond)} GEN {r.bond_forfeited ? '(forfeited)' : '(credited - pull it with withdraw_credit)'}
                </span>
                <span className="mono">by {shortAddr(r.reporter)}</span>
                <a href={r.evidence_url} target="_blank" rel="noreferrer noopener">
                  evidence
                </a>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
