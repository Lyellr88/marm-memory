import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProjectsPage } from './Projects';

vi.mock('@/hooks/use-marm-queries', () => ({
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
  useIndexProject: () => ({ isPending: false, mutate: vi.fn() }),
  useIndexJob: () => ({ data: undefined }),
  useDeleteProject: () => ({ isPending: false, mutate: vi.fn() }),
  useSearchProjectCode: () => ({ isPending: false, mutate: vi.fn() }),
  useTraceProject: () => ({ isPending: false, mutate: vi.fn() }),
  useProjectImpact: () => ({ isPending: false, mutate: vi.fn() }),
  useProjectArchitecture: () => ({ data: undefined, isLoading: false }),
  useProjectCodeUnits: () => ({ data: undefined, isLoading: false, isError: false }),
  useProjectCoverage: () => ({ data: undefined, isLoading: false, isError: false }),
  useProjectGraphQuery: () => ({ isPending: false, mutate: vi.fn() }),
  useProjectAdr: () => ({ data: undefined, isLoading: false }),
  useUpdateProjectAdr: () => ({ isPending: false, mutate: vi.fn() }),
  useIngestProjectRuntimeTraces: () => ({ isPending: false, mutate: vi.fn() }),
  useMarmConfig: () => ({ baseUrl: 'http://127.0.0.1:8002' }),
}));

describe('ProjectsPage', () => {
  afterEach(() => cleanup());

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
    expect(screen.getByRole('tab', { name: 'Code search' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Runtime traces' })).toBeTruthy();
  });
});
