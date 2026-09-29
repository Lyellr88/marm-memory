import { act, cleanup, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TerminalBridgeProvider, useTerminalBridge } from './terminal-bridge';

afterEach(cleanup);

const wrapper = ({ children }: { children: ReactNode }) => <TerminalBridgeProvider>{children}</TerminalBridgeProvider>;

describe('terminal bridge', () => {
  it('is unavailable and refuses to send until a dock registers', () => {
    const { result } = renderHook(() => useTerminalBridge(), { wrapper });
    expect(result.current.available).toBe(false);
    expect(result.current.sendToTerminal('marm-memory status')).toBe(false);
  });

  it('passes the exact command to the registered inserter and returns its result', () => {
    const inserter = vi.fn(() => true);
    const { result } = renderHook(() => useTerminalBridge(), { wrapper });

    act(() => result.current.register(inserter));
    expect(result.current.available).toBe(true);
    expect(result.current.sendToTerminal('marm-memory status')).toBe(true);
    expect(inserter).toHaveBeenCalledWith('marm-memory status');

    inserter.mockReturnValueOnce(false);
    expect(result.current.sendToTerminal('marm-memory stop')).toBe(false);
  });

  it('goes back to unavailable when the dock unregisters', () => {
    const inserter = vi.fn(() => true);
    const { result } = renderHook(() => useTerminalBridge(), { wrapper });

    act(() => result.current.register(inserter));
    act(() => result.current.register(null));
    expect(result.current.available).toBe(false);
    expect(result.current.sendToTerminal('marm-memory status')).toBe(false);
    expect(inserter).not.toHaveBeenCalled();
  });

  it('reports unavailable while the dock says the terminal cannot run, even when registered', () => {
    const { result } = renderHook(() => useTerminalBridge(), { wrapper });

    act(() => result.current.register(() => true));
    act(() => result.current.setUnavailable(true));
    expect(result.current.available).toBe(false);
    act(() => result.current.setUnavailable(false));
    expect(result.current.available).toBe(true);
  });
});
