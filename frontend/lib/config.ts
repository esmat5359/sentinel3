import { studioDevnet } from 'genlayer-js/chains';

const ADDRESS_RE = /^0x[0-9a-fA-F]{40}$/;

function parseAddress(value: string | undefined): `0x${string}` | null {
  if (!value) return null;
  const trimmed = value.trim();
  return ADDRESS_RE.test(trimmed) ? (trimmed as `0x${string}`) : null;
}

/**
 * Studio Devnet -- the environment the hackathon brief calls "Studio Next"
 * (chain id 61997). genlayer-js ships this chain definition, so the RPC
 * URL and chain id always match what the SDK itself expects.
 */
export const CHAIN = studioDevnet;

// NEXT_PUBLIC_* values are inlined by Next.js at build time, which only
// works when they are referenced as literal `process.env.NAME` accesses.
export const SENTINEL_ADDRESS = parseAddress(process.env.NEXT_PUBLIC_SENTINEL_ADDRESS);
export const VAULT_ADDRESS = parseAddress(process.env.NEXT_PUBLIC_VAULT_ADDRESS);

export const LIVE_CONFIGURED = SENTINEL_ADDRESS !== null && VAULT_ADDRESS !== null;
export const FORCE_DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === 'true';

export const EXPLORER_URL = 'https://explorer-studio-dev.genlayer.com/';

/** Network label the transaction panel expects. */
export const PANEL_NETWORK = 'studio-dev';

/** Valid-shaped placeholders used only by the simulated demo mode. */
export const DEMO_ACCOUNT = '0x000000000000000000000000000000000000dEaD' as const;
export const DEMO_SENTINEL = '0x5E271e1000000000000000000000000000000001' as const;
export const DEMO_VAULT = '0x7AE1B10000000000000000000000000000000002' as const;
