import { createClient } from 'genlayer-js';

import { CHAIN, SENTINEL_ADDRESS, VAULT_ADDRESS } from './config';
import {
  demoBalance,
  demoReports,
  demoSentinelConfig,
  demoTarget,
  demoVaultConfig,
} from './demo';
import type {
  BalanceInfo,
  ReportsResponse,
  SentinelConfig,
  TargetInfo,
  VaultConfig,
} from './types';

export type Mode = 'live' | 'demo';

type CallArg = string | number | bigint | boolean;

let cachedClient: ReturnType<typeof createClient> | null = null;

/** Read-only client: no account is needed to call view methods. */
function client() {
  if (!cachedClient) cachedClient = createClient({ chain: CHAIN });
  return cachedClient;
}

/**
 * Every view method on both contracts returns a JSON string (the same
 * convention for every read in this project), so a single helper covers
 * all of them.
 */
async function view<T>(
  address: `0x${string}`,
  functionName: string,
  args: CallArg[] = [],
): Promise<T> {
  const raw = await client().readContract({ address, functionName, args });
  return JSON.parse(String(raw)) as T;
}

function requireLive(): { sentinel: `0x${string}`; vault: `0x${string}` } {
  if (!SENTINEL_ADDRESS || !VAULT_ADDRESS) {
    throw new Error(
      'Contract addresses are not configured. Set NEXT_PUBLIC_SENTINEL_ADDRESS and NEXT_PUBLIC_VAULT_ADDRESS.',
    );
  }
  return { sentinel: SENTINEL_ADDRESS, vault: VAULT_ADDRESS };
}

export async function getVaultConfig(mode: Mode): Promise<VaultConfig> {
  if (mode === 'demo') return demoVaultConfig();
  const { vault } = requireLive();
  return view<VaultConfig>(vault, 'get_config');
}

export async function getSentinelConfig(mode: Mode): Promise<SentinelConfig> {
  if (mode === 'demo') return demoSentinelConfig();
  const { sentinel } = requireLive();
  return view<SentinelConfig>(sentinel, 'get_config');
}

export async function getTarget(mode: Mode): Promise<TargetInfo> {
  if (mode === 'demo') return demoTarget();
  const { sentinel, vault } = requireLive();
  return view<TargetInfo>(sentinel, 'get_target', [vault]);
}

export async function getReports(mode: Mode): Promise<ReportsResponse> {
  if (mode === 'demo') return demoReports();
  const { sentinel, vault } = requireLive();
  return view<ReportsResponse>(sentinel, 'get_target_reports', [vault]);
}

export async function getBalance(mode: Mode, account: string): Promise<BalanceInfo> {
  if (mode === 'demo') return demoBalance();
  const { vault } = requireLive();
  return view<BalanceInfo>(vault, 'get_balance_of', [account]);
}
