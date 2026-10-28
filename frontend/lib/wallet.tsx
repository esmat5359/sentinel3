'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { createTransactionKit, type TransactionKit } from '@genlayer/transaction-kit';
import { createMockKit } from '@genlayer/transaction-kit-react';

import type { Mode } from './api';
import { CHAIN, DEMO_ACCOUNT, FORCE_DEMO, LIVE_CONFIGURED } from './config';

/** The minimal slice of EIP-1193 this app uses. */
interface Eip1193Provider {
  request(args: { method: string; params?: unknown }): Promise<unknown>;
  on?(event: string, listener: (...args: unknown[]) => void): void;
  removeListener?(event: string, listener: (...args: unknown[]) => void): void;
}

type FeeSuggestionsInput = NonNullable<Parameters<typeof createTransactionKit>[0]['suggestions']>;

interface WalletContextValue {
  mode: Mode;
  setMode: (mode: Mode) => void;
  liveAvailable: boolean;
  account: `0x${string}` | null;
  kit: TransactionKit | null;
  hasProvider: boolean;
  connecting: boolean;
  error: string | null;
  connect: () => Promise<void>;
  disconnect: () => void;
}

const WalletContext = createContext<WalletContextValue | null>(null);

function getProvider(): Eip1193Provider | null {
  if (typeof window === 'undefined') return null;
  const injected = (window as unknown as { ethereum?: Eip1193Provider }).ethereum;
  return injected ?? null;
}

function describeError(error: unknown): string {
  if (error && typeof error === 'object') {
    const e = error as { message?: unknown; code?: unknown };
    if (e.code === 4001) return 'Request rejected in the wallet.';
    if (typeof e.message === 'string' && e.message) return e.message;
  }
  return 'Something went wrong while connecting the wallet.';
}

async function ensureChain(provider: Eip1193Provider): Promise<void> {
  const chainId = `0x${CHAIN.id.toString(16)}`;
  try {
    await provider.request({ method: 'wallet_switchEthereumChain', params: [{ chainId }] });
  } catch (error) {
    const code = (error as { code?: unknown } | null)?.code;
    // 4902: the wallet does not know this chain yet -- add it, which also
    // switches to it.
    if (code === 4902) {
      await provider.request({
        method: 'wallet_addEthereumChain',
        params: [
          {
            chainId,
            chainName: CHAIN.name,
            nativeCurrency: CHAIN.nativeCurrency,
            rpcUrls: CHAIN.rpcUrls.default.http,
          },
        ],
      });
      return;
    }
    throw error;
  }
}

/**
 * Fee suggestions are an optional, measured profile (see the README's
 * "Fee profile" section). When /fee-profile.json is absent the kit simply
 * falls back to network-default allocations, which is the correct and
 * honest behavior -- nothing here ever invents measurements.
 */
async function loadFeeSuggestions(): Promise<FeeSuggestionsInput | undefined> {
  try {
    const response = await fetch('/fee-profile.json', { cache: 'no-store' });
    if (!response.ok) return undefined;
    const parsed = (await response.json()) as FeeSuggestionsInput;
    return parsed;
  } catch {
    return undefined;
  }
}

export function WalletProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<Mode>(FORCE_DEMO || !LIVE_CONFIGURED ? 'demo' : 'live');
  const [account, setAccount] = useState<`0x${string}` | null>(null);
  const [liveKit, setLiveKit] = useState<TransactionKit | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasProvider, setHasProvider] = useState(false);

  useEffect(() => {
    setHasProvider(getProvider() !== null);
  }, []);

  // The mock kit mirrors the real kit's shapes with no network access, which
  // is exactly what a clearly-labelled demo mode needs. The delays make the
  // estimate -> sign -> track phases visible instead of flashing past.
  const demoKit = useMemo(
    () => createMockKit({ delays: { estimate: 500, submit: 900, step: 700 } }),
    [],
  );

  const disconnect = useCallback(() => {
    setAccount(null);
    setLiveKit(null);
  }, []);

  const connect = useCallback(async () => {
    const provider = getProvider();
    if (!provider) {
      setError('No injected wallet found. Install MetaMask (or another EIP-1193 wallet) and reload.');
      return;
    }
    setConnecting(true);
    setError(null);
    try {
      const accounts = (await provider.request({ method: 'eth_requestAccounts' })) as string[];
      if (!accounts[0]) throw new Error('The wallet did not return an account.');
      await ensureChain(provider);
      const connected = accounts[0] as `0x${string}`;
      const suggestions = await loadFeeSuggestions();
      const kit = createTransactionKit({
        chain: CHAIN,
        provider: provider as never,
        account: connected,
        suggestions,
      });
      setAccount(connected);
      setLiveKit(kit);
    } catch (e) {
      setError(describeError(e));
    } finally {
      setConnecting(false);
    }
  }, []);

  // A switched account or chain in the wallet invalidates the kit built for
  // the previous one; drop it and make the user reconnect explicitly.
  useEffect(() => {
    const provider = getProvider();
    if (!provider?.on || !provider.removeListener) return;
    const reset = () => disconnect();
    provider.on('accountsChanged', reset);
    provider.on('chainChanged', reset);
    return () => {
      provider.removeListener?.('accountsChanged', reset);
      provider.removeListener?.('chainChanged', reset);
    };
  }, [disconnect]);

  const setMode = useCallback((next: Mode) => {
    setModeState(next);
    setError(null);
  }, []);

  const value = useMemo<WalletContextValue>(
    () => ({
      mode,
      setMode,
      liveAvailable: LIVE_CONFIGURED,
      account: mode === 'demo' ? DEMO_ACCOUNT : account,
      kit: mode === 'demo' ? demoKit : liveKit,
      hasProvider,
      connecting,
      error,
      connect,
      disconnect,
    }),
    [mode, setMode, account, demoKit, liveKit, hasProvider, connecting, error, connect, disconnect],
  );

  return <WalletContext.Provider value={value}>{children}</WalletContext.Provider>;
}

export function useWallet(): WalletContextValue {
  const ctx = useContext(WalletContext);
  if (!ctx) throw new Error('useWallet must be used inside <WalletProvider>');
  return ctx;
}
