import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { boundedLogLines, useRuntimeLogTail } from './use-runtime-logs';

const state = vi.hoisted(() => ({ client: { getRuntimeLogTail: vi.fn(), getDockerLogs: vi.fn() } }));
vi.mock('./marm-query-core', () => ({ useMarmConfig: () => ({ baseUrl: 'local', client: state.client }) }));

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  state.client.getRuntimeLogTail.mockResolvedValue({ lines: ['first'], cursor: 'a', exists: true, rotated: false });
  state.client.getDockerLogs.mockResolvedValue({ lines: ['docker'] });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

it('appends increments using the cursor and replaces a rotated log', async () => {
  const { result } = renderHook(() => useRuntimeLogTail(true));
  await waitFor(() => expect(result.current.lines).toEqual(['first']));
  state.client.getRuntimeLogTail.mockResolvedValueOnce({ lines: ['second'], cursor: 'b', exists: true, rotated: false });
  await act(() => result.current.refresh());
  expect(state.client.getRuntimeLogTail).toHaveBeenLastCalledWith('a');
  expect(result.current.lines).toEqual(['first', 'second']);
  state.client.getRuntimeLogTail.mockResolvedValueOnce({ lines: ['new file'], cursor: 'c', exists: true, rotated: true });
  await act(() => result.current.refresh());
  expect(result.current.lines).toEqual(['new file']);
  expect(result.current.rotated).toBe(true);
});

it('replaces Docker snapshots instead of duplicating them', async () => {
  const { result } = renderHook(() => useRuntimeLogTail(true, 'docker'));
  await waitFor(() => expect(result.current.lines).toEqual(['docker']));
  await act(() => result.current.refresh());
  expect(result.current.lines).toEqual(['docker']);
});

it('has one request in flight and discards a response after clear', async () => {
  let resolve!: (value: unknown) => void;
  const { result } = renderHook(() => useRuntimeLogTail(true));
  await waitFor(() => expect(result.current.lines).toEqual(['first']));
  state.client.getRuntimeLogTail.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  state.client.getRuntimeLogTail.mockResolvedValueOnce({ lines: ['old'], cursor: 'baseline', exists: true, rotated: false });
  let pending!: Promise<void>;
  act(() => { pending = result.current.refresh(); });
  await act(() => result.current.refresh());
  expect(state.client.getRuntimeLogTail).toHaveBeenCalledTimes(2);
  act(() => result.current.clear());
  await act(async () => { resolve({ lines: ['old'], cursor: 'old', exists: true, rotated: false }); await pending; });
  expect(state.client.getRuntimeLogTail).toHaveBeenLastCalledWith(null);
  expect(result.current.lines).toEqual([]);
  state.client.getRuntimeLogTail.mockResolvedValueOnce({ lines: ['after clear'], cursor: 'new', exists: true, rotated: false });
  await act(() => result.current.refresh());
  expect(state.client.getRuntimeLogTail).toHaveBeenLastCalledWith('baseline');
  expect(result.current.lines).toEqual(['after clear']);
});

it('discards a response when the source changes', async () => {
  let resolve!: (value: unknown) => void;
  state.client.getRuntimeLogTail.mockReturnValue(new Promise((done) => { resolve = done; }));
  const { result, rerender } = renderHook(({ source }) => useRuntimeLogTail(true, source), { initialProps: { source: 'runtime' as 'runtime' | 'docker' } });
  act(() => result.current.setAuto(false));
  rerender({ source: 'docker' });
  await act(async () => resolve({ lines: ['wrong source'], cursor: 'old', exists: true, rotated: false }));
  expect(result.current.lines).toEqual(['docker']);
  expect(state.client.getDockerLogs).toHaveBeenCalledTimes(1);
});

it('polls only when open, visible, and auto-refresh is enabled', async () => {
  vi.useFakeTimers();
  const { result, rerender } = renderHook(({ enabled }) => useRuntimeLogTail(enabled), { initialProps: { enabled: false } });
  await act(async () => vi.advanceTimersByTimeAsync(4000));
  expect(state.client.getRuntimeLogTail).not.toHaveBeenCalled();
  rerender({ enabled: true });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  expect(state.client.getRuntimeLogTail).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(state.client.getRuntimeLogTail).toHaveBeenCalledTimes(2);
  act(() => result.current.setAuto(false));
  await act(async () => vi.advanceTimersByTimeAsync(4000));
  expect(state.client.getRuntimeLogTail).toHaveBeenCalledTimes(2);
  act(() => result.current.setAuto(true));
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
  await act(async () => vi.advanceTimersByTimeAsync(4000));
  expect(state.client.getRuntimeLogTail).toHaveBeenCalledTimes(2);
});

it('bounds both line count and UTF-8 bytes, retaining the newest lines', () => {
  expect(boundedLogLines(Array.from({ length: 3000 }, (_, i) => String(i)))).toHaveLength(2000);
  const bounded = boundedLogLines(Array(2000).fill('界'.repeat(4000)));
  expect(new TextEncoder().encode(bounded.join('\n')).length).toBeLessThanOrEqual(256 * 1024);
});
