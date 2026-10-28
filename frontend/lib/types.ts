export type Verdict = 'SUPPORTED' | 'NOT_SUPPORTED' | 'INCONCLUSIVE';
export type ReportAction = 'HALT' | 'CLEAR';
export type TargetStatus = 'SAFE' | 'HALTED';

/** Mirrors SentinelHalt.get_config() */
export interface SentinelConfig {
  owner: string;
  paused: boolean;
  report_bond: string;
  min_report_bond: string;
  max_report_bond: string;
  action_cooldown_seconds: number;
  max_targets: number;
}

/** Mirrors SentinelHalt.get_target() */
export interface TargetInfo {
  found: boolean;
  address?: string;
  name?: string;
  scope?: string;
  status?: TargetStatus;
  registered_by?: string;
  registered_epoch?: number;
  last_action_epoch?: number;
  report_count?: number;
  halt_count?: number;
  accrued_compensation?: string;
  withdrawn_compensation?: string;
  available_compensation?: string;
}

/** Mirrors one entry of SentinelHalt.get_target_reports() */
export interface ReportInfo {
  report_id: number;
  target: string;
  action: ReportAction;
  reporter: string;
  evidence_url: string;
  claim: string;
  bond: string;
  verdict: Verdict;
  confidence: number;
  reasoning: string;
  fetch_note: string;
  bond_forfeited: boolean;
  submitted_epoch: number;
  decided_epoch: number;
}

export interface ReportsResponse {
  target: string;
  count: number;
  reports: ReportInfo[];
}

/** Mirrors TreasuryVault.get_config() */
export interface VaultConfig {
  owner: string;
  sentinel: string;
  address: string;
  halted: boolean;
  total_deposited: string;
  total_withdrawn: string;
  on_chain_balance: string;
}

/** Mirrors TreasuryVault.get_balance_of() */
export interface BalanceInfo {
  address: string;
  balance: string;
}

export type DashboardState = 'loading' | 'error' | 'unregistered' | 'operational' | 'halted';
