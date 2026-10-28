import type { DashboardState } from '@/lib/types';

interface StatusBannerProps {
  state: DashboardState;
  /** Index of the current step in the five-step flow (0-4). */
  step: number;
  detail?: string;
  /** True when the vault's live answer and SentinelHalt's own record disagree. */
  mismatch?: boolean;
}

const STEPS = ['Register', 'Fund', 'Report', 'Halted', 'Cleared'];

const COPY: Record<DashboardState, { headline: string; detail: string }> = {
  loading: {
    headline: 'Reading the chain...',
    detail: 'Asking both contracts for their current state.',
  },
  error: {
    headline: 'Could not read the contracts',
    detail: 'Check the addresses, the network, and your connection.',
  },
  unregistered: {
    headline: 'Vault not registered yet',
    detail: 'Register it with SentinelHalt to put it under autonomous protection.',
  },
  operational: {
    headline: 'Vault operational',
    detail: 'Deposits and withdrawals are open. Every call re-checks SentinelHalt live.',
  },
  halted: {
    headline: 'Vault halted by consensus',
    detail:
      'Validators agreed an exploit is active. Deposits and withdrawals are frozen until a clear request is judged supported.',
  },
};

export function StatusBanner({ state, step, detail, mismatch }: StatusBannerProps) {
  const copy = COPY[state];
  return (
    <section className={`status ${state}`} aria-live="polite" aria-label="Vault status">
      <div className="status-row">
        <div className="beacon" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            {state === 'halted' ? (
              <>
                <path d="M12 3 2.5 20h19L12 3Z" />
                <path d="M12 10v4.5" />
                <path d="M12 17.5h.01" />
              </>
            ) : state === 'operational' ? (
              <>
                <path d="M12 3 4 6v5.5c0 4.7 3.2 8.4 8 9.5 4.8-1.1 8-4.8 8-9.5V6l-8-3Z" />
                <path d="m8.8 12.2 2.4 2.4 4.2-4.6" />
              </>
            ) : (
              <>
                <circle cx="12" cy="12" r="8.5" />
                <path d="M12 7.5v5l3 1.8" />
              </>
            )}
          </svg>
        </div>
        <div>
          <h2 className="status-headline">{copy.headline}</h2>
          <p className="status-detail">{detail ?? copy.detail}</p>
        </div>
      </div>

      {mismatch && (
        <div className="notice warn" style={{ marginTop: 18, marginBottom: 0 }}>
          <span>
            <strong>Heads up:</strong> SentinelHalt&apos;s record and the vault&apos;s live answer disagree.
            The vault may be pointed at a different SentinelHalt than the one configured here.
          </span>
        </div>
      )}

      <ol className="stepper" aria-label="Protection flow" style={{ listStyle: 'none', padding: 0 }}>
        {STEPS.map((label, i) => (
          <li
            key={label}
            className={i < step ? 'step done' : i === step ? 'step active' : 'step'}
            aria-current={i === step ? 'step' : undefined}
          >
            {label}
          </li>
        ))}
      </ol>
    </section>
  );
}
