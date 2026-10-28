/**
 * Simulated demo mode.
 *
 * Everything in this file is an in-memory stand-in for the two contracts so
 * the interface can be explored without a wallet or a network. It is NOT a
 * second implementation of the product: the real judgment is made by
 * GenLayer validators reading evidence with an LLM, which cannot run in a
 * browser tab. Demo mode substitutes a keyword heuristic for that judgment
 * and says so everywhere it shows a result. The UI badges this mode
 * prominently and never enables it silently while real addresses are set.
 */
import { DEMO_ACCOUNT, DEMO_SENTINEL, DEMO_VAULT } from './config';
import type {
  BalanceInfo,
  ReportAction,
  ReportInfo,
  ReportsResponse,
  SentinelConfig,
  TargetInfo,
  Verdict,
  VaultConfig,
} from './types';

const WEI = BigInt(10) ** BigInt(18);
const REPORT_BOND = WEI / BigInt(100); // 0.01 GEN, matches DEFAULT_REPORT_BOND
const COOLDOWN_SECONDS = 300;

interface DemoState {
  registered: boolean;
  halted: boolean;
  name: string;
  scope: string;
  registeredEpoch: number;
  lastActionEpoch: number;
  reportCount: number;
  haltCount: number;
  accrued: bigint;
  vaultBalance: bigint;
  userBalance: bigint;
  totalDeposited: bigint;
  totalWithdrawn: bigint;
  reports: ReportInfo[];
}

const state: DemoState = {
  registered: false,
  halted: false,
  name: '',
  scope: '',
  registeredEpoch: 0,
  lastActionEpoch: 0,
  reportCount: 0,
  haltCount: 0,
  accrued: BigInt(0),
  vaultBalance: BigInt(0),
  userBalance: BigInt(0),
  totalDeposited: BigInt(0),
  totalWithdrawn: BigInt(0),
  reports: [],
};

const nowEpoch = () => Math.floor(Date.now() / 1000);

export interface SimulatedVerdict {
  verdict: Verdict;
  confidence: number;
  reasoning: string;
}

/**
 * Keyword heuristic standing in for the validators' LLM judgment. Clearly
 * not the real thing -- every reasoning string it returns says so.
 */
export function simulateVerdict(action: ReportAction, url: string, claim: string): SimulatedVerdict {
  const text = `${url} ${claim}`.toLowerCase();
  if (!/^https?:\/\//i.test(url.trim()) || claim.trim().length < 8) {
    return {
      verdict: 'INCONCLUSIVE',
      confidence: 0,
      reasoning: '[demo heuristic] Evidence URL or claim too thin to judge either way.',
    };
  }
  const haltWords = /(drain|exploit|attack|hack|stolen|vulnerab|reentran|rug|compromis)/.test(text);
  const clearWords = /(patch|fixed|resolved|post-?mortem|audit|secured|remediat|verified safe)/.test(text);
  if (action === 'HALT') {
    return haltWords
      ? {
          verdict: 'SUPPORTED',
          confidence: 88,
          reasoning: '[demo heuristic] Claim describes an active exploit and cites evidence.',
        }
      : {
          verdict: 'NOT_SUPPORTED',
          confidence: 71,
          reasoning: '[demo heuristic] Nothing in the claim describes an active exploit.',
        };
  }
  return clearWords
    ? {
        verdict: 'SUPPORTED',
        confidence: 84,
        reasoning: '[demo heuristic] Claim cites a patch or post-mortem closing the vector.',
      }
    : {
        verdict: 'NOT_SUPPORTED',
        confidence: 69,
        reasoning: '[demo heuristic] No verifiable sign the issue was actually resolved.',
      };
}

export function demoReset(): void {
  state.registered = false;
  state.halted = false;
  state.name = '';
  state.scope = '';
  state.registeredEpoch = 0;
  state.lastActionEpoch = 0;
  state.reportCount = 0;
  state.haltCount = 0;
  state.accrued = BigInt(0);
  state.vaultBalance = BigInt(0);
  state.userBalance = BigInt(0);
  state.totalDeposited = BigInt(0);
  state.totalWithdrawn = BigInt(0);
  state.reports = [];
}

// -- mutations (applied after the mock transaction panel finishes) ---------

export function demoRegister(name: string, scope: string): void {
  if (state.registered) return;
  state.registered = true;
  state.name = name;
  state.scope = scope;
  state.registeredEpoch = nowEpoch();
}

export function demoDeposit(wei: bigint): void {
  if (state.halted || wei <= BigInt(0)) return;
  state.vaultBalance += wei;
  state.userBalance += wei;
  state.totalDeposited += wei;
}

export function demoWithdraw(wei: bigint): void {
  if (state.halted || wei <= BigInt(0) || wei > state.userBalance) return;
  state.vaultBalance -= wei;
  state.userBalance -= wei;
  state.totalWithdrawn += wei;
}

export function demoReport(action: ReportAction, url: string, claim: string): SimulatedVerdict | null {
  if (!state.registered) return null;
  if (action === 'HALT' && state.halted) return null;
  if (action === 'CLEAR' && !state.halted) return null;
  const sim = simulateVerdict(action, url, claim);
  const now = nowEpoch();
  state.reportCount += 1;
  state.lastActionEpoch = now;
  let forfeited = false;
  if (sim.verdict === 'SUPPORTED') {
    if (action === 'HALT') {
      state.halted = true;
      state.haltCount += 1;
    } else {
      state.halted = false;
    }
  } else if (sim.verdict === 'NOT_SUPPORTED') {
    forfeited = true;
    state.accrued += REPORT_BOND;
  }
  state.reports.push({
    report_id: state.reportCount,
    target: DEMO_VAULT,
    action,
    reporter: DEMO_ACCOUNT,
    evidence_url: url,
    claim,
    bond: REPORT_BOND.toString(),
    verdict: sim.verdict,
    confidence: sim.confidence,
    reasoning: sim.reasoning,
    fetch_note: '',
    bond_forfeited: forfeited,
    submitted_epoch: now,
    decided_epoch: now,
  });
  return sim;
}

// -- reads (same shapes the real contracts' JSON views return) -------------

export function demoSentinelConfig(): SentinelConfig {
  return {
    owner: DEMO_ACCOUNT,
    paused: false,
    report_bond: REPORT_BOND.toString(),
    min_report_bond: (WEI / BigInt(10000)).toString(),
    max_report_bond: WEI.toString(),
    action_cooldown_seconds: COOLDOWN_SECONDS,
    max_targets: 2000,
  };
}

export function demoTarget(): TargetInfo {
  if (!state.registered) return { found: false };
  return {
    found: true,
    address: DEMO_VAULT,
    name: state.name,
    scope: state.scope,
    status: state.halted ? 'HALTED' : 'SAFE',
    registered_by: DEMO_ACCOUNT,
    registered_epoch: state.registeredEpoch,
    last_action_epoch: state.lastActionEpoch,
    report_count: state.reportCount,
    halt_count: state.haltCount,
    accrued_compensation: state.accrued.toString(),
    withdrawn_compensation: '0',
    available_compensation: state.accrued.toString(),
  };
}

export function demoReports(): ReportsResponse {
  const newestFirst = [...state.reports].reverse();
  return { target: DEMO_VAULT, count: newestFirst.length, reports: newestFirst };
}

export function demoVaultConfig(): VaultConfig {
  return {
    owner: DEMO_ACCOUNT,
    sentinel: DEMO_SENTINEL,
    address: DEMO_VAULT,
    halted: state.halted,
    total_deposited: state.totalDeposited.toString(),
    total_withdrawn: state.totalWithdrawn.toString(),
    on_chain_balance: state.vaultBalance.toString(),
  };
}

export function demoBalance(): BalanceInfo {
  return { address: DEMO_ACCOUNT, balance: state.userBalance.toString() };
}
