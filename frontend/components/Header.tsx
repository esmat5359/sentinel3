'use client';

import { CHAIN } from '@/lib/config';
import { shortAddr } from '@/lib/format';
import { useWallet } from '@/lib/wallet';

export function Header() {
  const { mode, setMode, liveAvailable, account, hasProvider, connecting, error, connect, disconnect } =
    useWallet();

  return (
    <>
      {mode === 'demo' && (
        <div className="demo-ribbon" role="status">
          SIMULATED DEMO - no blockchain, no wallet. Verdicts come from a keyword heuristic, not from
          validators. Set the contract addresses to use the live network.
        </div>
      )}
      <header className="topbar">
        <div className="shell topbar-inner">
          <div className="brand">
            <div className="brand-mark" aria-hidden="true">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#7cc4ff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 3 4 6v5.5c0 4.7 3.2 8.4 8 9.5 4.8-1.1 8-4.8 8-9.5V6l-8-3Z" />
                <path d="M12 8.5v4" />
                <path d="M12 15.5h.01" />
              </svg>
            </div>
            <div>
              <div className="brand-name">Sentinel</div>
              <div className="brand-sub">Autonomous halt for GenLayer</div>
            </div>
          </div>

          <div className="topbar-actions">
            <span className="chip accent" title={`Chain id ${CHAIN.id}`}>
              <span className="dot" />
              {CHAIN.name}
            </span>

            {liveAvailable ? (
              <div className="row" role="group" aria-label="Data source" style={{ gap: 4 }}>
                <button
                  type="button"
                  className={mode === 'live' ? 'btn small primary' : 'btn small ghost'}
                  onClick={() => setMode('live')}
                >
                  Live
                </button>
                <button
                  type="button"
                  className={mode === 'demo' ? 'btn small primary' : 'btn small ghost'}
                  onClick={() => setMode('demo')}
                >
                  Demo
                </button>
              </div>
            ) : (
              <span className="chip warn" title="Set NEXT_PUBLIC_SENTINEL_ADDRESS and NEXT_PUBLIC_VAULT_ADDRESS">
                Demo only - addresses not set
              </span>
            )}

            {mode === 'live' &&
              (account ? (
                <>
                  <span className="chip ok mono">
                    <span className="dot" />
                    {shortAddr(account)}
                  </span>
                  <button type="button" className="btn small ghost" onClick={disconnect}>
                    Disconnect
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="btn small primary"
                  onClick={() => void connect()}
                  disabled={connecting}
                >
                  {connecting ? 'Connecting...' : hasProvider ? 'Connect wallet' : 'Install a wallet'}
                </button>
              ))}
          </div>
        </div>
        {error && (
          <div className="shell" style={{ paddingBottom: 12 }}>
            <div className="notice danger" style={{ marginBottom: 0 }} role="alert">
              <span>{error}</span>
            </div>
          </div>
        )}
      </header>
    </>
  );
}
