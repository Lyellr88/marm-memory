import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { useRuntimeControlJob, useStartRuntime } from './use-runtime-queries';

const state = vi.hoisted(() => ({ client: { startRuntime: vi.fn(), stopRuntime: vi.fn(), startRuntimeRestart: vi.fn(), getRuntimeRestartJob: vi.fn() } }));
vi.mock('./marm-query-core', async (original) => ({ ...(await original<object>()), useMarmConfig: () => ({ baseUrl: 'local', client: state.client }) }));
afterEach(cleanup);

it('shares the mutation, job id, and completion across two observers', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidated = vi.spyOn(qc, 'invalidateQueries');
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  let accept!: (value: { job_id: string }) => void;
  state.client.startRuntime.mockReturnValue(new Promise((resolve) => { accept = resolve; }));
  state.client.getRuntimeRestartJob.mockResolvedValue({ kind: 'start', status: 'done' });
  const primary = renderHook(() => ({ action: useStartRuntime(), job: useRuntimeControlJob() }), { wrapper });
  const secondary = renderHook(() => useRuntimeControlJob(), { wrapper });
  act(() => primary.result.current.action.mutate());
  await waitFor(() => expect(secondary.result.current.busy).toBe(true));
  await act(async () => accept({ job_id: 'shared' }));
  await waitFor(() => expect(secondary.result.current.data?.status).toBe('done'));
  expect(primary.result.current.job.jobId).toBe('shared');
  expect(secondary.result.current.jobId).toBe('shared');
  expect(secondary.result.current.busy).toBe(false);
  expect(invalidated).toHaveBeenCalledWith({ queryKey: ['connections-overview', 'local'] });
  qc.clear();
});
