'use client';

import { useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { SubmitInput, TrackedStatus } from '@genlayer/transaction-kit';

import {
  DEMO_SENTINEL,
  DEMO_VAULT,
  SENTINEL_ADDRESS,
  VAULT_ADDRESS,
} from '@/lib/config';
import {
  demoDeposit,
  demoRegister,
  demoReport,
  demoWithdraw,
} from '@/lib/demo';
import { cooldownRemaining, formatDuration, formatGen, parseGen } from '@/lib/format';
import type { ReportAction, SentinelConfig, TargetInfo, VaultConfig } from '@/lib/types';
import { useWallet } from '@/lib/wallet';

import { TxRunner } from './TxRunner';

type TabId = 'register' | 'deposit' | 'withdraw' | 'report' | 'clear';

type Pending =
  | { kind: 'register'; name: string; scope: string }
  | { kind: 'deposit'; wei: bigint }
  | { kind: 'withdraw'; wei: bigint }
  | { kind: 'report'; action: ReportAction; url: string; claim: string };

interface ActionPanelProps {
  vault: VaultConfig | undefined;
  target: TargetInfo | undefined;
  sentinelConfig: SentinelConfig | undefined;
  userBalanceWei: string | undefined;
}

// Mirrors the contract's own floor so the form can say no before the chain does.
const MIN_DEPOSIT_WEI = BigInt(10) ** BigInt(12);

const DEFAULT_SCOPE =
  'A demo vault holding user deposits. Deposits and withdrawals are frozen while SentinelHalt reports it as halted.';

function useNowSeconds(): number {
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    const id = setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

export function ActionPanel({ vault, target, sentinelConfig, userBalanceWei }: ActionPanelProps) {
  const { mode, account } = useWallet();
  const queryClient = useQueryClient();
  const nowSeconds = useNowSeconds();

  const sentinelAddress = mode === 'demo' ? DEMO_SENTINEL : SENTINEL_ADDRESS;
  const vaultAddress = mode === 'demo' ? DEMO_VAULT : VAULT_ADDRESS;

  const registered = target?.found === true;
  const halted = vault?.halted === true;

  const [tab, setTab] = useState<TabId>('register');
  const [pending, setPending] = useState<Pending | null>(null);
  const [runId, setRunId] = useState(0);
  const [settledNote, setSettledNote] = useState<string | null>(null);

  // register form
  const [name, setName] = useState('TreasuryVault');
  const [scope, setScope] = useState(DEFAULT_SCOPE);
  // amount forms
  const [depositAmount, setDepositAmount] = useState('0.05');
  const [withdrawAmount, setWithdrawAmount] = useState('0.01');
  // judgment forms
  const [reportUrl, setReportUrl] = useState('');
  const [reportClaim, setReportClaim] = useState('');
  const [clearUrl, setClearUrl] = useState('');
  const [clearClaim, setClearClaim] = useState('');

  // Land on the most useful tab for where the flow currently is.
  useEffect(() => {
    if (!registered) setTab('register');
    else if (halted) setTab((t) => (t === 'register' || t === 'report' ? 'clear' : t));
    else setTab((t) => (t === 'register' || t === 'clear' ? 'deposit' : t));
  }, [registered, halted]);

  const bondWei = useMemo(() => {
    try {
      return sentinelConfig ? BigInt(sentinelConfig.report_bond) : BigInt(0);
    } catch {
      return BigInt(0);
    }
  }, [sentinelConfig]);

  const cooldownLeft = cooldownRemaining(
    target?.last_action_epoch,
    sentinelConfig?.action_cooldown_seconds,
    nowSeconds * 1000,
  );

  const ready = sentinelAddress !== null && vaultAddress !== null;

  function submitRegister() {
    setSettledNote(null);
    setPending({ kind: 'register', name: name.trim(), scope: scope.trim() });
    setRunId((n) => n + 1);
  }

  function submitDeposit(wei: bigint) {
    setSettledNote(null);
    setPending({ kind: 'deposit', wei });
    setRunId((n) => n + 1);
  }

  function submitWithdraw(wei: bigint) {
    setSettledNote(null);
    setPending({ kind: 'withdraw', wei });
    setRunId((n) => n + 1);
  }

  function submitJudgment(action: ReportAction, url: string, claim: string) {
    setSettledNote(null);
    setPending({ kind: 'report', action, url: url.trim(), claim: claim.trim() });
    setRunId((n) => n + 1);
  }

  const txInput = useMemo<{ tx: SubmitInput; userValue?: bigint } | null>(() => {
    if (!pending || !sentinelAddress || !vaultAddress) return null;
    switch (pending.kind) {
      case 'register':
        return {
          tx: {
            kind: 'write',
            address: sentinelAddress,
            method: 'register_target',
            args: [vaultAddress, pending.name, pending.scope],
          },
        };
      case 'deposit':
        return {
          tx: { kind: 'write', address: vaultAddress, method: 'deposit', args: [] },
          userValue: pending.wei,
        };
      case 'withdraw':
        return {
          tx: { kind: 'write', address: vaultAddress, method: 'withdraw', args: [pending.wei] },
        };
      case 'report':
        return {
          tx: {
            kind: 'write',
            address: sentinelAddress,
            method: pending.action === 'HALT' ? 'report_exploit' : 'clear_halt',
            args: [vaultAddress, pending.url, pending.claim],
          },
          userValue: bondWei,
        };
    }
  }, [pending, sentinelAddress, vaultAddress, bondWei]);

  function onSettled(status: TrackedStatus) {
    if (!pending) return;
    const succeeded = status.successful !== false;
    if (mode === 'demo' && succeeded) {
      switch (pending.kind) {
        case 'register':
          demoRegister(pending.name, pending.scope);
          break;
        case 'deposit':
          demoDeposit(pending.wei);
          break;
        case 'withdraw':
          demoWithdraw(pending.wei);
          break;
        case 'report':
          demoReport(pending.action, pending.url, pending.claim);
          break;
      }
    }
    setSettledNote(
      succeeded
        ? mode === 'demo'
          ? 'Simulated transaction complete. The dashboard now reflects the simulated state.'
          : 'The network has decided this transaction. The dashboard is refreshing from the chain -- if nothing changed, the contract refunded you with a reason; open the transaction in the explorer to read it.'
        : 'The transaction did not succeed. Nothing changed on-chain.',
    );
    void queryClient.invalidateQueries();
    if (mode === 'live') {
      // Reads can lag a block or two behind a just-decided transaction.
      setTimeout(() => void queryClient.invalidateQueries(), 5000);
    }
  }

  function closeRunner() {
    setPending(null);
    setSettledNote(null);
  }

  const depositWei = parseGen(depositAmount);
  const withdrawWei = parseGen(withdrawAmount);
  const depositInvalid = depositWei === null || depositWei < MIN_DEPOSIT_WEI;
  const withdrawInvalid = withdrawWei === null || withdrawWei <= BigInt(0);

  const reportUrlOk = /^https?:\/\//i.test(reportUrl.trim());
  const reportClaimOk = reportClaim.trim().length >= 8;
  const clearUrlOk = /^https?:\/\//i.test(clearUrl.trim());
  const clearClaimOk = clearClaim.trim().length >= 8;

  const demoFrozen = mode === 'demo' && halted;

  const tabs: { id: TabId; label: string }[] = [
    { id: 'register', label: 'Register' },
    { id: 'deposit', label: 'Deposit' },
    { id: 'withdraw', label: 'Withdraw' },
    { id: 'report', label: 'Report' },
    { id: 'clear', label: 'Clear' },
  ];

  return (
    <section className="card" aria-labelledby="actions-title">
      <h2 className="card-title" id="actions-title">
        <span>Actions</span>
        <span className="mono" style={{ textTransform: 'none', letterSpacing: 0 }}>
          {account ? 'signing as ' + account.slice(0, 6) + '...' + account.slice(-4) : 'no wallet'}
        </span>
      </h2>

      {!ready && (
        <div className="notice warn">
          <span>
            <strong>Contracts not configured.</strong> Set <code>NEXT_PUBLIC_SENTINEL_ADDRESS</code>{' '}
            and <code>NEXT_PUBLIC_VAULT_ADDRESS</code>, or switch to the simulated demo.
          </span>
        </div>
      )}

      <div className="tabs" role="tablist" aria-label="Choose an action">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={tab === t.id ? 'tab active' : 'tab'}
            onClick={() => {
              setTab(t.id);
              closeRunner();
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {pending && txInput ? (
        <>
          <TxRunner
            key={runId}
            tx={txInput.tx}
            userValue={txInput.userValue}
            onSettled={onSettled}
            onClose={closeRunner}
          />
          {settledNote && (
            <div className="notice ok" style={{ marginTop: 14 }}>
              <span>{settledNote}</span>
            </div>
          )}
        </>
      ) : (
        <>
          {tab === 'register' && (
            <div role="tabpanel">
              {registered ? (
                <div className="notice ok">
                  <span>
                    <strong>Already registered.</strong> SentinelHalt is tracking this vault. Move on to
                    funding it, or file a report.
                  </span>
                </div>
              ) : (
                <div className="notice">
                  <span>
                    One-time setup. Registering creates an entry SentinelHalt can answer questions about;
                    it grants SentinelHalt no control over the vault. The vault protects itself by asking
                    SentinelHalt on every call.
                  </span>
                </div>
              )}
              <div className="field">
                <label htmlFor="reg-name">Name</label>
                <input
                  id="reg-name"
                  className="input"
                  value={name}
                  maxLength={80}
                  onChange={(e) => setName(e.target.value)}
                  disabled={registered}
                />
              </div>
              <div className="field">
                <label htmlFor="reg-scope">What it does</label>
                <textarea
                  id="reg-scope"
                  className="textarea"
                  value={scope}
                  maxLength={600}
                  onChange={(e) => setScope(e.target.value)}
                  disabled={registered}
                />
                <span className="hint">
                  Shown to the validators as context when they judge whether evidence is about this
                  contract.
                </span>
              </div>
              <button
                type="button"
                className="btn primary"
                disabled={!ready || registered || name.trim().length === 0 || scope.trim().length === 0}
                onClick={submitRegister}
              >
                Prepare registration
              </button>
            </div>
          )}

          {tab === 'deposit' && (
            <div role="tabpanel">
              {halted && (
                <div className="notice danger">
                  <span>
                    <strong>The vault is halted.</strong>{' '}
                    {demoFrozen
                      ? 'The simulated vault refuses deposits while halted. In live mode you can still submit one and watch the contract reject it on-chain.'
                      : 'You can still submit a deposit to watch the contract reject it on-chain -- the vault refunds the full amount.'}
                  </span>
                </div>
              )}
              <div className="field">
                <label htmlFor="dep-amount">Amount (GEN)</label>
                <input
                  id="dep-amount"
                  className={depositInvalid ? 'input invalid' : 'input'}
                  inputMode="decimal"
                  value={depositAmount}
                  onChange={(e) => setDepositAmount(e.target.value)}
                />
                <span className="hint">
                  Sent with the call as GEN. Minimum {formatGen(MIN_DEPOSIT_WEI, 6)} GEN. Network fees are
                  quoted separately in the next step.
                </span>
              </div>
              <button
                type="button"
                className="btn primary"
                disabled={!ready || depositInvalid || demoFrozen}
                onClick={() => depositWei !== null && submitDeposit(depositWei)}
              >
                Prepare deposit
              </button>
            </div>
          )}

          {tab === 'withdraw' && (
            <div role="tabpanel">
              {halted && (
                <div className="notice danger">
                  <span>
                    <strong>Withdrawals are frozen.</strong>{' '}
                    {demoFrozen
                      ? 'In live mode, submit one anyway to watch the contract revert it -- that revert is the enforcement.'
                      : 'Submit one anyway: the transaction will fail on-chain, which is the enforcement working.'}
                  </span>
                </div>
              )}
              <div className="field">
                <label htmlFor="wd-amount">Amount (GEN)</label>
                <input
                  id="wd-amount"
                  className={withdrawInvalid ? 'input invalid' : 'input'}
                  inputMode="decimal"
                  value={withdrawAmount}
                  onChange={(e) => setWithdrawAmount(e.target.value)}
                />
                <span className="hint">
                  Your vault balance: {formatGen(userBalanceWei)} GEN{' '}
                  <button
                    type="button"
                    className="btn ghost small"
                    onClick={() => setWithdrawAmount(formatGen(userBalanceWei, 18))}
                  >
                    Max
                  </button>
                </span>
              </div>
              <button
                type="button"
                className="btn primary"
                disabled={!ready || withdrawInvalid || demoFrozen}
                onClick={() => withdrawWei !== null && submitWithdraw(withdrawWei)}
              >
                Prepare withdrawal
              </button>
            </div>
          )}

          {tab === 'report' && (
            <div role="tabpanel">
              {!registered && (
                <div className="notice warn">
                  <span>Register the vault first -- reports are filed against a registered target.</span>
                </div>
              )}
              {registered && halted && (
                <div className="notice">
                  <span>
                    Already halted. To bring the vault back, use <strong>Clear halt</strong>.
                  </span>
                </div>
              )}
              {cooldownLeft > 0 && (
                <div className="notice warn">
                  <span>
                    A decided action on this vault is cooling down:{' '}
                    <strong>{formatDuration(cooldownLeft)}</strong> left. This stops anyone from cheaply
                    spamming the validators.
                  </span>
                </div>
              )}
              {mode === 'demo' && (
                <div className="notice">
                  <span>
                    Demo mode judges with a keyword heuristic, not validators. Mention words like{' '}
                    <em>drain</em> or <em>exploit</em> in the claim to see a SUPPORTED verdict.
                  </span>
                </div>
              )}
              <div className="field">
                <label htmlFor="rep-url">Evidence URL</label>
                <input
                  id="rep-url"
                  className="input"
                  placeholder="https://explorer.example.com/tx/0x..."
                  value={reportUrl}
                  onChange={(e) => setReportUrl(e.target.value)}
                />
                <span className="hint">
                  A public page the validators will fetch and read for themselves: a block-explorer
                  transaction, a security write-up, a PoC.
                </span>
              </div>
              <div className="field">
                <label htmlFor="rep-claim">Your claim</label>
                <textarea
                  id="rep-claim"
                  className="textarea"
                  placeholder="What is happening, and why does this page show it?"
                  value={reportClaim}
                  maxLength={500}
                  onChange={(e) => setReportClaim(e.target.value)}
                />
              </div>
              <div className="notice">
                <span>
                  A refundable bond of <strong>{formatGen(bondWei)} GEN</strong> rides with the report. It
                  comes back if the claim is supported or the evidence cannot be judged, and goes to the
                  vault&apos;s maintainer if validators find the claim unsupported.
                </span>
              </div>
              <button
                type="button"
                className="btn danger"
                disabled={
                  !ready || !registered || halted || cooldownLeft > 0 || !reportUrlOk || !reportClaimOk
                }
                onClick={() => submitJudgment('HALT', reportUrl, reportClaim)}
              >
                Prepare report
              </button>
            </div>
          )}

          {tab === 'clear' && (
            <div role="tabpanel">
              {!halted && (
                <div className="notice">
                  <span>The vault is not halted, so there is nothing to clear.</span>
                </div>
              )}
              {halted && (
                <div className="notice warn">
                  <span>
                    <strong>Clearing is judged exactly like halting.</strong> If a maintainer could simply
                    declare a compromised contract fixed, a compromised maintainer would. The validators
                    have to agree the issue is actually resolved.
                  </span>
                </div>
              )}
              {cooldownLeft > 0 && (
                <div className="notice warn">
                  <span>
                    Cooling down: <strong>{formatDuration(cooldownLeft)}</strong> left before the next
                    decided action on this vault.
                  </span>
                </div>
              )}
              <div className="field">
                <label htmlFor="clr-url">Evidence URL</label>
                <input
                  id="clr-url"
                  className="input"
                  placeholder="https://example.com/post-mortem"
                  value={clearUrl}
                  onChange={(e) => setClearUrl(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="clr-claim">Your claim</label>
                <textarea
                  id="clr-claim"
                  className="textarea"
                  placeholder="What was fixed, and how does the page verify it?"
                  value={clearClaim}
                  maxLength={500}
                  onChange={(e) => setClearClaim(e.target.value)}
                />
              </div>
              <button
                type="button"
                className="btn primary"
                disabled={
                  !ready || !halted || cooldownLeft > 0 || !clearUrlOk || !clearClaimOk
                }
                onClick={() => submitJudgment('CLEAR', clearUrl, clearClaim)}
              >
                Prepare clear request
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
