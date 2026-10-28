'use client';

import { GenLayerTransactionPanel } from '@genlayer/transaction-kit-react';
import type { SubmitInput, TrackedStatus } from '@genlayer/transaction-kit';

import { PANEL_NETWORK } from '@/lib/config';
import { useWallet } from '@/lib/wallet';

interface TxRunnerProps {
  tx: SubmitInput;
  /** GEN (in wei) sent with the call -- the bond for report/clear, the amount for a deposit. */
  userValue?: bigint;
  onSettled: (status: TrackedStatus) => void;
  onClose: () => void;
}

/**
 * Thin wrapper around @genlayer/transaction-kit-react's panel, which owns
 * the whole fee-aware lifecycle: quote, review, sign, and track the
 * transaction until the network has decided it. Nothing about fees or
 * signing is reimplemented here.
 */
export function TxRunner({ tx, userValue, onSettled, onClose }: TxRunnerProps) {
  const { kit } = useWallet();

  if (!kit) {
    return (
      <div className="notice warn">
        <span>
          <strong>Wallet not connected.</strong> Connect a wallet to prepare this transaction.
        </span>
      </div>
    );
  }

  return (
    <div className="tx-shell">
      <GenLayerTransactionPanel
        kit={kit}
        tx={tx}
        userValue={userValue}
        network={PANEL_NETWORK}
        theme="dark"
        trackUntil="decided"
        onDone={onSettled}
      />
      <div className="row" style={{ marginTop: 14 }}>
        <button type="button" className="btn ghost small" onClick={onClose}>
          Back to form
        </button>
      </div>
    </div>
  );
}
