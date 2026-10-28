/**
 * Read-only sanity check of a deployment -- no private key needed.
 *
 *   npm run check                      # uses deploy/deployments.json
 *   SENTINEL=0x... VAULT=0x... npm run check
 *
 * Reads both contracts through their public JSON views and confirms the
 * vault is pointed at the SentinelHalt you expect, which is the single most
 * common wiring mistake.
 */
import { existsSync, readFileSync } from 'node:fs';

import { DEPLOYMENTS_FILE, readClient, type Deployments } from './shared.js';

function addresses(): { sentinel: `0x${string}`; vault: `0x${string}` } {
  const sentinel = process.env.SENTINEL as `0x${string}` | undefined;
  const vault = process.env.VAULT as `0x${string}` | undefined;
  if (sentinel && vault) return { sentinel, vault };
  if (!existsSync(DEPLOYMENTS_FILE)) {
    throw new Error('No deployments.json found. Run `npm run deploy` first, or set SENTINEL and VAULT.');
  }
  const saved = JSON.parse(readFileSync(DEPLOYMENTS_FILE, 'utf8')) as Deployments;
  return { sentinel: saved.sentinelHalt, vault: saved.treasuryVault };
}

async function main() {
  const { sentinel, vault } = addresses();
  const client = readClient();

  const read = async (address: `0x${string}`, functionName: string, args: string[] = []) =>
    JSON.parse(String(await client.readContract({ address, functionName, args })));

  const sentinelConfig = await read(sentinel, 'get_config');
  const sentinelStats = await read(sentinel, 'get_stats');
  const vaultConfig = await read(vault, 'get_config');
  const target = await read(sentinel, 'get_target', [vault]);

  console.log('SentinelHalt', sentinel);
  console.log('  report bond      :', sentinelConfig.report_bond, 'wei');
  console.log('  cooldown         :', sentinelConfig.action_cooldown_seconds, 's');
  console.log('  paused           :', sentinelConfig.paused);
  console.log('  targets/reports  :', sentinelStats.targets, '/', sentinelStats.reports);
  console.log('TreasuryVault', vault);
  console.log('  asks SentinelHalt:', vaultConfig.sentinel);
  console.log('  halted (live)    :', vaultConfig.halted);
  console.log('  registered       :', target.found, target.found ? `(${target.status})` : '');

  if (String(vaultConfig.sentinel).toLowerCase() !== sentinel.toLowerCase()) {
    console.error('\nWARNING: the vault is pointed at a different SentinelHalt than the one checked.');
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
