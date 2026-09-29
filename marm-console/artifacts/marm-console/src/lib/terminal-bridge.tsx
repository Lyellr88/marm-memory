import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';

type Inserter = (command: string) => boolean;

interface TerminalBridge {
  available: boolean;
  sendToTerminal: (command: string) => boolean;
  register: (inserter: Inserter | null) => void;
  setUnavailable: (unavailable: boolean) => void;
}

const NOOP_BRIDGE: TerminalBridge = {
  available: false,
  sendToTerminal: () => false,
  register: () => undefined,
  setUnavailable: () => undefined,
};

const TerminalBridgeContext = createContext<TerminalBridge>(NOOP_BRIDGE);

export function TerminalBridgeProvider({ children }: { children: ReactNode }) {
  const inserterRef = useRef<Inserter | null>(null);
  const [registered, setRegistered] = useState(false);
  const [unavailable, setUnavailable] = useState(false);

  const register = useCallback((inserter: Inserter | null) => {
    inserterRef.current = inserter;
    setRegistered(inserter !== null);
  }, []);
  const sendToTerminal = useCallback((command: string) => inserterRef.current?.(command) ?? false, []);

  const value = useMemo(
    () => ({ available: registered && !unavailable, sendToTerminal, register, setUnavailable }),
    [registered, unavailable, sendToTerminal, register],
  );
  return <TerminalBridgeContext.Provider value={value}>{children}</TerminalBridgeContext.Provider>;
}

export function useTerminalBridge() {
  return useContext(TerminalBridgeContext);
}
