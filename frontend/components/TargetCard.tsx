'use client';

import { useEffect, useState } from 'react';

import { cooldownRemaining, formatDuration, formatGen, shortAddr, timeAgo } from '@/lib/format';
import type { SentinelConfig, TargetInfo } from '@/lib/types';

interface TargetCardProps {
  target: TargetInfo | undefined;
  config: SentinelConfig | undefined;
}

export function TargetCard({ target, config }: TargetCardProps) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const found = target?.found === true;
  const left = cooldownRemaining(target?.last_action_epoch, config?.action_cooldown_seconds, nowMs);

  return (
    <section className="card" aria-labelledby="sentinel-title">
      <h2 className="card-title" id="sentinel-title">
        <span>SentinelHalt record</span>
        {found && (
          <span className={target?.status === 'HALTED' ? 'chip danger' : 'chip ok'}>
            <span className="dot" />
            {target?.status}
          </span>
        )}
      </h2>

      {!found ? (
        <div className="empty">SentinelHalt has no record of this vault yet.</div>
      ) : (
        <>
          <div className="stat-grid">
            <div className="stat">
              <div className="stat-label">Reports judged</div>
              <div className="stat-value">{target?.report_count ?? 0}</div>
            </div>
            <div className="stat">
              <div className="stat-label">Times halted</div>
              <div className="stat-value">{target?.halt_count ?? 0}</div>
            </div>
            <div className="stat">
              <div className="stat-label">Forfeited bonds</div>
              <div className="stat-value">
                {formatGen(target?.accrued_compensation)}
                <small>GEN</small>
              </div>
            </div>
            <div className="stat">
              <div className="stat-label">Next action in</div>
              <div className="stat-value" style={{ fontSize: 17 }}>
                {formatDuration(left)}
              </div>
            </div>
          </div>
          <dl className="kv">
            <dt>Name</dt>
            <dd>{target?.name}</dd>
            <dt>Scope</dt>
            <dd>{target?.scope}</dd>
            <dt>Registered by</dt>
            <dd className="mono">{shortAddr(target?.registered_by, 8, 6)}</dd>
            <dt>Last decided</dt>
            <dd>{timeAgo(target?.last_action_epoch, nowMs)}</dd>
            <dt>Report bond</dt>
            <dd>{formatGen(config?.report_bond)} GEN (refundable unless judged unsupported)</dd>
          </dl>
        </>
      )}
    </section>
  );
}
