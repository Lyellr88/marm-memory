import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

const BASE_URL_STORAGE_KEY = 'marm-console:base-url';

export const DEFAULT_BASE_URL =
  typeof window !== 'undefined' && window.location.port === '8002'
    ? window.location.origin
    : 'http://127.0.0.1:8002';

interface ConnectionContextValue {
  baseUrl: string;
  apiKey: string | null;
  setBaseUrl: (url: string) => void;
  setApiKey: (key: string | null) => void;
  clearApiKey: () => void;
}

const ConnectionContext = createContext<ConnectionContextValue | null>(null);

function readStoredBaseUrl(): string {
  if (typeof window === 'undefined') return DEFAULT_BASE_URL;
  return window.localStorage.getItem(BASE_URL_STORAGE_KEY) ?? DEFAULT_BASE_URL;
}

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const [baseUrl, setBaseUrlState] = useState<string>(readStoredBaseUrl);
  // The bearer token lives only in React state — never persisted to
  // web storage, so it can't outlive the tab or leak to other scripts.
  const [apiKey, setApiKeyState] = useState<string | null>(null);

  const setBaseUrl = useCallback((url: string) => {
    const trimmed = url.trim().replace(/\/+$/, '');
    setBaseUrlState(trimmed);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(BASE_URL_STORAGE_KEY, trimmed);
    }
  }, []);

  const setApiKey = useCallback((key: string | null) => {
    setApiKeyState(key);
  }, []);

  const clearApiKey = useCallback(() => setApiKey(null), [setApiKey]);

  const value = useMemo(
    () => ({ baseUrl, apiKey, setBaseUrl, setApiKey, clearApiKey }),
    [baseUrl, apiKey, setBaseUrl, setApiKey, clearApiKey],
  );

  return (
    <ConnectionContext.Provider value={value}>
      {children}
    </ConnectionContext.Provider>
  );
}

export function useConnection(): ConnectionContextValue {
  const ctx = useContext(ConnectionContext);
  if (!ctx) {
    throw new Error('useConnection must be used within a ConnectionProvider');
  }
  return ctx;
}
