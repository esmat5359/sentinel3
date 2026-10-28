'use client';

import { useQuery } from '@tanstack/react-query';

import { getBalance, getReports, getSentinelConfig, getTarget, getVaultConfig } from '@/lib/api';
import type { DashboardState } from '@/lib/types';
import { useWallet } from '@/lib/wallet';

import { ActionPanel } from './ActionPanel';
import { Header } from './Header';
import { HowItWorks } from './HowItWorks';
import { ReportsTimeline } from './ReportsTimeline';
import { StatusBanner } from './StatusBanner';
import { TargetCard } from './TargetCard';
import { VaultCard } from './VaultCard';

const POLL_MS = 5000;

export function Dashboard() {
  const { mode, account } = useWallet();

  const vaultQ = useQuery({
    queryKey: ['vault', mode],
    queryFn: () => getVaultConfig(mode),
    refetchInterval: POLL_MS,
    retry: 1,
  });
  const targetQ = useQuery({
    queryKey: ['target', mode],
    queryFn: () => getTarget(mode),
    refetchInterval: POLL_MS,
    retry: 1,
  });
  const reportsQ = useQuery({
    queryKey: ['reports', mode],
    queryFn: () => getReports(mode),
    refetchInterval: POLL_MS + 1000,
    retry: 1,
  });
  const configQ = useQuery({
    queryKey: ['sentinel-config', mode],
    queryFn: () => getSentinelConfig(mode),
    refetchInterval: 30000,
    retry: 1,
  });
  const balanceQ = useQuery({
    queryKey: ['balance', mode, account],
    queryFn: () => getBalance(mode, account as string),
    enabled: account !== null,
    refetchInterval: POLL_MS + 1000,
    retry: 1,
  });

  const vault = vaultQ.data;
  const target = targetQ.data;

  let state: DashboardState;
  if (vaultQ.isError || targetQ.isError) state = 'error';
  else if (vaultQ.isPending || targetQ.isPending) state = 'loading';
  else if (!target?.found) state = 'unregistered';
  else state = vault?.halted ? 'halted' : 'operational';

  // Where in the five-step flow the vault currently sits.
  let step = 0;
  if (target?.found) {
    if (vault?.halted) step = 3;
    else if ((target.halt_count ?? 0) > 0) step = 4;
    else step = BigInt(vault?.on_chain_balance ?? '0') > BigInt(0) ? 2 : 1;
  }

  const mismatch = target?.found === true && (target.status === 'HALTED') !== (vault?.halted === true);

  const errorMessage =
    (vaultQ.error as Error | null)?.message ?? (targetQ.error as Error | null)?.message ?? undefined;

  return (
    <>
      <Header />
      <main>
        <div className="shell">
          <div className="hero">
            <h1>
              Contracts that <span className="grad">halt themselves</span>, with no one voting.
            </h1>
            <p>
              Sentinel is an autonomous emergency brake. Anyone can submit evidence of an active exploit; a
              GenLayer validator quorum reads it and reaches consensus. If they agree, every contract
              protected by Sentinel stops - live, on the next call.
            </p>
          </div>

          <div style={{ margin: '26px 0 24px' }}>
            <StatusBanner
              state={state}
              step={step}
              mismatch={mismatch}
              detail={state === 'error' ? errorMessage : undefined}
            />
          </div>

          <div className="layout">
            <div className="stack">
              <VaultCard vault={vault} userBalanceWei={balanceQ.data?.balance} demo={mode === 'demo'} />
              <TargetCard target={target} config={configQ.data} />
              <ReportsTimeline reports={reportsQ.data?.reports} />
            </div>
            <div className="stack">
              <ActionPanel
                vault={vault}
                target={target}
                sentinelConfig={configQ.data}
                userBalanceWei={balanceQ.data?.balance}
              />
              <HowItWorks />
            </div>
          </div>
        </div>
      </main>
      <footer className="footer">
        <div className="shell">
          Sentinel - built for GenLayer&apos;s <strong>Autonomous Protocols</strong> track. An emergency-halt
          module (and a contract that governs another contract) judged by validator consensus, not by a
          vote or an admin key.
        </div>
      </footer>
    </>
  );
}
