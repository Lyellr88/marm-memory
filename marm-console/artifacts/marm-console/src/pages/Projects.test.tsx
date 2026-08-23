import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ExploreDialog, ProjectsPage } from './Projects';

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
    expect(screen.getByRole('button', { name: 'Explore' })).toBeTruthy();
  });

  it('groups explorer tools into a persistent workspace', async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><ProjectsPage /></QueryClientProvider>);

    await user.click(screen.getByRole('button', { name: 'Explore' }));

    expect(screen.getByText('Code graph explorer')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Investigate' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Runtime traces' })).toBeTruthy();
  });

  it('refreshes open explorer architecture and code structure after indexing completes', async () => {
    const user = userEvent.setup();
    indexState.job = { status: 'running', project: 'marm-systems', phase: 'indexing' };
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    const view = render(<QueryClientProvider client={queryClient}><ProjectsPage /></QueryClientProvider>);

    await user.type(screen.getByLabelText('Repository path'), 'C:/work/marm-systems');
    await user.click(screen.getByRole('button', { name: 'Start moderate index' }));
    await user.click(screen.getByRole('button', { name: 'Explore' }));

    indexState.job = { status: 'success', project: 'marm-systems', phase: 'complete' };
    view.rerender(<QueryClientProvider client={queryClient}><ProjectsPage /></QueryClientProvider>);

    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['projectArchitecture', 'http://127.0.0.1:8002', 'marm-systems'] });
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['projectCodeUnits', 'http://127.0.0.1:8002', 'marm-systems'] });
    });
    expect(screen.getByText('Code graph explorer')).toBeTruthy();
  });

  it('clears decisions while the next project ADR is still loading', async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const firstProject = {
      name: 'marm-systems',
      root_path: 'C:/work/marm-systems',
      nodes: 4500,
      edges: 23913,
      status: 'ready',
    } as const;
    const secondProject = {
      ...firstProject,
      name: 'second-project',
      root_path: 'C:/work/second-project',
    };
    const renderDialog = (project: typeof firstProject | typeof secondProject) => (
      <QueryClientProvider client={queryClient}>
        <ExploreDialog project={project} open onOpenChange={() => {}} />
      </QueryClientProvider>
    );
    const view = render(renderDialog(firstProject));

    await user.click(screen.getByRole('tab', { name: 'Decisions' }));
    await waitFor(() => {
      expect((screen.getByPlaceholderText('# Architecture decisions') as HTMLTextAreaElement).value).toBe('# First project decisions');
    });

    view.rerender(renderDialog(secondProject));
    await user.click(screen.getByRole('tab', { name: 'Decisions' }));

    expect(screen.getByText('Loading decisions…')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Save decisions' }) as HTMLButtonElement).disabled).toBe(true);

    adrState.secondLoading = false;
    view.rerender(renderDialog(secondProject));
    await waitFor(() => {
      expect((screen.getByPlaceholderText('# Architecture decisions') as HTMLTextAreaElement).value).toBe('');
    });
  });

  it('resets mutation observers when switching projects', () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const firstProject = {
      name: 'marm-systems', root_path: 'C:/work/marm-systems', nodes: 4500, edges: 23913, status: 'ready',
    } as const;
    const secondProject = { ...firstProject, name: 'second-project', root_path: 'C:/work/second-project' };
    const renderDialog = (project: typeof firstProject | typeof secondProject) => (
      <QueryClientProvider client={queryClient}>
        <ExploreDialog project={project} open onOpenChange={() => {}} />
      </QueryClientProvider>
    );
    const view = render(renderDialog(firstProject));

    view.rerender(renderDialog(secondProject));

    expect(mutationState.updateAdrReset).toHaveBeenCalledTimes(2);
    expect(mutationState.ingestTraceReset).toHaveBeenCalledTimes(2);
  });

  it('rejects invalid runtime trace counts before submitting', async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const project = {
      name: 'marm-systems', root_path: 'C:/work/marm-systems', nodes: 4500, edges: 23913, status: 'ready',
    } as const;
    render(<QueryClientProvider client={queryClient}><ExploreDialog project={project} open onOpenChange={() => {}} /></QueryClientProvider>);

    await user.click(screen.getByRole('tab', { name: 'Runtime traces' }));
    await user.type(screen.getByPlaceholderText('caller.qualified_name'), 'source.fn');
    await user.type(screen.getByPlaceholderText('callee.qualified_name'), 'target.fn');
    const count = screen.getByPlaceholderText('Count');
    await user.clear(count);
    await user.type(count, '1.5');

    expect(screen.getByText('Count must be a whole number from 1 to 1,000,000.')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Ingest trace' }) as HTMLButtonElement).disabled).toBe(true);
    expect(mutationState.ingestTraceMutate).not.toHaveBeenCalled();
  });
});
