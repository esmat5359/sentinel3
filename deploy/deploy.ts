/**
 * Deploy SentinelHalt and TreasuryVault to Studio Devnet.
 *
 *   cp .env.example .env     # add a funded DEPLOYER_PRIVATE_KEY
 *   npm install
 *   npm run deploy
 *
 * Under the v0.6 fee model every deploy carries a fee distribution and a
 * quoted fee value, so each deploy first asks the network for an estimate
 * and attaches exactly that -- nothing is hard-coded.
 */
import { writeFileSync } from 'node:fs';

import { isSuccessful } from 'genlayer-js';

import {
  ACTION_COOLDOWN_SECONDS,
  DEPLOYMENTS_FILE,
  REPORT_BOND,
  pinnedRunner,
  readClient,
  readContract,
  requireAccount,
  type Deployments,
  type TxHash,
} from './shared.js';

async function deploy(
  client: ReturnType<typeof readClient>,
  label: string,
  source: string,
  args: (bigint | number | string)[],
): Promise<`0x${string}`> {
  const quote = await client.estimateTransactionFees();
  console.log(`  ${label}: fee quote ${quote.feeValue} wei`);

  const hash = await client.deployContract({
    code: source,
    args,
    fees: { distribution: quote.distribution, feeValue: quote.feeValue },
  });
  console.log(`  ${label}: submitted ${hash}, waiting for the network to decide...`);

  const receipt = await client.waitForTransactionReceipt({
    hash: hash as unknown as TxHash,
    waitUntil: 'decided',
    interval: 3000,
    retries: 100,
  });
  if (!isSuccessful(receipt)) {
    throw new Error(
      `${label} deployment did not succeed (status ${String(receipt.statusName)}, ` +
        `result ${String(receipt.txExecutionResultName)}). Check the runner hash with ` +
        '`python3 scripts/set_runner_hash.py --show` against what Studio Devnet currently runs.',
    );
  }

  const decoded = receipt.txDataDecoded as { contractAddress?: `0x${string}` } | undefined;
  const address = receipt.recipient ?? decoded?.contractAddress;
  if (!address) throw new Error(`${label}: deployment succeeded but no contract address was returned.`);
  console.log(`  ${label}: deployed at ${address}`);
  return address;
}

async function main() {
  const account = requireAccount();
  const client = readClient(account);

  const sentinelSource = readContract('SentinelHalt');
  const vaultSource = readContract('TreasuryVault');
  const runner = pinnedRunner(sentinelSource);

  console.log(`Deploying from ${account.address} to Studio Devnet`);
  console.log(`Pinned GenVM runner: py-genlayer:${runner}`);

  const sentinelHalt = await deploy(client, 'SentinelHalt', sentinelSource, [
    REPORT_BOND,
    ACTION_COOLDOWN_SECONDS,
  ]);
  const treasuryVault = await deploy(client, 'TreasuryVault', vaultSource, [sentinelHalt]);

  const deployments: Deployments = {
    network: 'studio-devnet',
    chainId: client.chain.id,
    sentinelHalt,
    treasuryVault,
    runnerHash: runner,
    deployedAt: new Date().toISOString(),
  };
  writeFileSync(DEPLOYMENTS_FILE, JSON.stringify(deployments, null, 2) + '\n');

  console.log('\nDone. Put these in frontend/.env.local:\n');
  console.log(`NEXT_PUBLIC_SENTINEL_ADDRESS=${sentinelHalt}`);
  console.log(`NEXT_PUBLIC_VAULT_ADDRESS=${treasuryVault}`);
  console.log(`\nAddresses were also written to ${DEPLOYMENTS_FILE}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
