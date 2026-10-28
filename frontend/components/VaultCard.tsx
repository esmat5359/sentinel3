'use client';

import { useState } from 'react';

import { EXPLORER_URL } from '@/lib/config';
import { formatGen, shortAddr } from '@/lib/format';
import type { VaultConfig } from '@/lib/types';

interface VaultCardProps {
  vault: VaultConfig | undefined;
  userBalanceWei: string | undefined;
  demo: boolean;
}

function CopyAddress({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn ghost small mono"
      title="Copy full address"
      onClick={() => {
        void navigator.clipboard?.writeText(value).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        });
      }}
    >
      {copied ? 'copied' : shortAddr(value, 8, 6)}
    </button>
  );
}

export function VaultCard({ vault, userBalanceWei, demo }: VaultCardProps) {
  return (
    <section className="card" aria-labelledby="vault-title">
      <h2 className="card-title" id="vault-title">
        <span>TreasuryVault</span>
        {!demo && (
          <a href={EXPLORER_URL} target="_blank" rel="noreferrer" className="chip accent">
            Explorer
          </a>
        )}
      </h2>

      <div className="stat-grid">
        <div className="stat">
          <div className="stat-label">Held in vault</div>
          <div className="stat-value">
            {formatGen(vault?.on_chain_balance)}
            <small>GEN</small>
          </div>
        </div>
        <div className="stat">
          <div className="stat-label">Your balance</div>
          <div className="stat-value">
            {formatGen(userBalanceWei)}
            <small>GEN</small>
          </div>
        </div>
        <div className="stat">
          <div className="stat-label">Total deposited</div>
          <div className="stat-value">
            {formatGen(vault?.total_deposited)}
            <small>GEN</small>
          </div>
        </div>
        <div className="stat">
          <div className="stat-label">Total withdrawn</div>
          <div className="stat-value">
            {formatGen(vault?.total_withdrawn)}
            <small>GEN</small>
          </div>
        </div>
      </div>

      <dl className="kv">
        <dt>Vault address</dt>
        <dd>{vault ? <CopyAddress value={vault.address} /> : '--'}</dd>
        <dt>Asks SentinelHalt at</dt>
        <dd>{vault ? <CopyAddress value={vault.sentinel} /> : '--'}</dd>
        <dt>Enforcement</dt>
        <dd>
          Live <code>is_halted()</code> read on every deposit and withdrawal -- no cached flag
        </dd>
      </dl>
    </section>
  );
}
