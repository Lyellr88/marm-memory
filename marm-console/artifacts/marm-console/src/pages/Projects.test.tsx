import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProjectsPage } from './Projects';

const adrState = vi.hoisted(() => ({
  secondLoading: true,
  secondContent: undefined as string | undefined,
}));

const mutationState = vi.hoisted(() => ({
  searchReset: vi.fn(),
  traceReset: vi.fn(),
  impactReset: vi.fn(),
  graphQueryReset: vi.fn(),
  updateAdrReset: vi.fn(),
  ingestTraceReset: vi.fn(),
  ingestTraceMutate: vi.fn(),
}));

const indexState = vi.hoisted(() => ({
  job: undefined as { status: string; project: string; phase: string } | undefined,
  mutate: vi.fn(),
}));

vi.mock('@/hooks/use-marm-queries', () => ({
  queryKeys: {
    projectArchitecture: (baseUrl: string, project: string) => ['projectArchitecture', baseUrl, project],
    projectCodeUnits: (baseUrl: string, project: string) => ['projectCodeUnits', baseUrl, project],
  },
  useProjects: () => ({
    data: [{
      name: 'marm-systems',
      root_path: 'C:/work/marm-systems',
      nodes: 4500,
      edges: 23913,
      status: 'ready',
    }],
    isLoading: false,
  }),
  useIndexProject: () => ({
    isPending: false,
    mutate: (input: unknown, options: { onSuccess?: (result: { job_id: string }) => void }) => {
      indexState.mutate(input);
      options.onSuccess?.({ job_id: 'index-job' });
    },
  }),
  useIndexJob: (jobId: string) => ({ data: jobId ? indexState.job : undefined, error: null, isError: false, refetch: vi.fn() }),
  useDeleteProject: () => ({ isPending: false, mutate: vi.fn() }),
  useSearchProjectCode: () => ({ isPending: false, mutate: vi.fn(), reset: mutationState.searchReset }),
  useTraceProject: () => ({ isPending: false, mutate: vi.fn(), reset: mutationState.traceReset }),
  useProjectImpact: () => ({ isPending: false, mutate: vi.fn(), reset: mutationState.impactReset }),
  useProjectArchitecture: () => ({ data: undefined, isLoading: false }),
  useProjectCodeUnits: () => ({ data: undefined, isLoading: false, isError: false }),
  useProjectCoverage: () => ({ data: undefined, isLoading: false, isError: false }),
  useProjectAdr: (project: string) => ({
    data: project === 'marm-systems'
      ? { content: '# First project decisions' }
      : adrState.secondContent === undefined
        ? undefined
        : { content: adrState.secondContent },
    isLoading: project === 'second-project' && adrState.secondLoading,
  }),
  useUpdateProjectAdr: () => ({ isPending: false, mutate: vi.fn(), reset: mutationState.updateAdrReset }),
  useIngestProjectRuntimeTraces: () => ({ isPending: false, mutate: mutationState.ingestTraceMutate, reset: mutationState.ingestTraceReset }),
  useMarmConfig: () => ({ baseUrl: 'http://127.0.0.1:8002' }),
}));

describe('ProjectsPage', () => {
  afterEach(() => {
    adrState.secondLoading = true;
    adrState.secondContent = undefined;
    indexState.job = undefined;
    vi.clearAllMocks();
    cleanup();
  });

  it('keeps repository indexing on the page alongside project intelligence', () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><ProjectsPage /></QueryClientProvider>);

    expect(screen.getByRole('heading', { name: 'Indexed Projects' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Index a repository' })).toBeTruthy();
    expect(screen.getByLabelText('Repository path')).toBeTruthy();
    expect(screen.getByText('Graph nodes')).toBeTruthy();
    expect(screen.getByText('marm-systems')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Open in explorer' })).toBeTruthy();
  });

  it('refreshes architecture and code structure after indexing completes', async () => {
    const user = userEvent.setup();
    indexState.job = { status: 'running', project: 'marm-systems', phase: 'indexing' };
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    const view = render(<QueryClientProvider client={queryClient}><ProjectsPage /></QueryClientProvider>);

    await user.type(screen.getByLabelText('Repository path'), 'C:/work/marm-systems');
    await user.click(screen.getByRole('button', { name: 'Start moderate index' }));

    indexState.job = { status: 'success', project: 'marm-systems', phase: 'complete' };
    view.rerender(<QueryClientProvider client={queryClient}><ProjectsPage /></QueryClientProvider>);

    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['projectArchitecture', 'http://127.0.0.1:8002', 'marm-systems'] });
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['projectCodeUnits', 'http://127.0.0.1:8002', 'marm-systems'] });
    });
  });

});
