import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { createAccount, createClient } from 'genlayer-js';
import { studioDevnet } from 'genlayer-js/chains';

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const DEPLOYMENTS_FILE = resolve(ROOT, 'deploy', 'deployments.json');

/** 0.01 GEN -- matches DEFAULT_REPORT_BOND in SentinelHalt.py */
export const REPORT_BOND = BigInt(10) ** BigInt(16);
/** Seconds between decided actions on one target -- matches the contract default. */
export const ACTION_COOLDOWN_SECONDS = 300;

export interface Deployments {
  network: string;
  chainId: number;
  sentinelHalt: `0x${string}`;
  treasuryVault: `0x${string}`;
  runnerHash: string;
  deployedAt: string;
}

export function readContract(name: string): string {
  return readFileSync(resolve(ROOT, 'contracts', `${name}.py`), 'utf8');
}

/** The GenVM runner a contract pins in its `# { "Depends": ... }` header. */
export function pinnedRunner(source: string): string {
  const match = /"Depends":\s*"py-genlayer:([0-9a-z]+)"/.exec(source);
  return match ? match[1] : '(no Depends header found)';
}

export function readClient(account?: ReturnType<typeof createAccount>) {
  return createClient({ chain: studioDevnet, ...(account ? { account } : {}) });
}

/** The SDK's branded transaction-hash type, derived from the call that consumes it. */
export type TxHash = Parameters<ReturnType<typeof readClient>['waitForTransactionReceipt']>[0]['hash'];

export function requireAccount() {
  const key = process.env.DEPLOYER_PRIVATE_KEY;
  if (!key || !/^0x[0-9a-fA-F]{64}$/.test(key)) {
    throw new Error(
      'Set DEPLOYER_PRIVATE_KEY to a 0x-prefixed 32-byte private key (see deploy/.env.example).',
    );
  }
  return createAccount(key as `0x${string}`);
}
