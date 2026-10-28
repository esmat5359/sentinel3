const WEI = BigInt(10) ** BigInt(18);

export function shortAddr(address?: string | null, head = 6, tail = 4): string {
  if (!address) return '--';
  if (address.length <= head + tail + 2) return address;
  return `${address.slice(0, head)}...${address.slice(-tail)}`;
}

/** Wei (as string or bigint) to a trimmed GEN decimal string. */
export function formatGen(wei: string | bigint | undefined | null, maxDecimals = 4): string {
  if (wei === undefined || wei === null || wei === '') return '0';
  let value: bigint;
  try {
    value = typeof wei === 'bigint' ? wei : BigInt(wei);
  } catch {
    return '0';
  }
  const whole = value / WEI;
  const frac = (value % WEI).toString().padStart(18, '0').slice(0, maxDecimals).replace(/0+$/, '');
  return frac ? `${whole}.${frac}` : `${whole}`;
}

/** Decimal GEN string to wei; null when the input is not a valid amount. */
export function parseGen(input: string): bigint | null {
  const match = /^\s*(\d+)(?:\.(\d{1,18}))?\s*$/.exec(input);
  if (!match) return null;
  const whole = BigInt(match[1]);
  const fracDigits = (match[2] ?? '').padEnd(18, '0');
  return whole * WEI + BigInt(fracDigits === '' ? '0' : fracDigits);
}

export function timeAgo(epochSeconds: number | undefined, nowMs: number = Date.now()): string {
  if (!epochSeconds) return 'never';
  const diff = Math.max(0, Math.floor(nowMs / 1000) - epochSeconds);
  if (diff < 5) return 'just now';
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function cooldownRemaining(
  lastActionEpoch: number | undefined,
  cooldownSeconds: number | undefined,
  nowMs: number = Date.now(),
): number {
  if (!lastActionEpoch || !cooldownSeconds) return 0;
  const elapsed = Math.floor(nowMs / 1000) - lastActionEpoch;
  return Math.max(0, cooldownSeconds - elapsed);
}

export function formatDuration(seconds: number): string {
  if (seconds <= 0) return 'ready';
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s === 0 ? `${m}m` : `${m}m ${s}s`;
}
