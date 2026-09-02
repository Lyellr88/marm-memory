import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Route, Router, Switch } from 'wouter';
import { memoryLocation } from 'wouter/memory-location';
import { ExplorerPage } from './Explorer';

const adrState = vi.hoisted(() => ({
  secondLoading: true,
  secondContent: undefined as string | undefined,
}));

const mutationState = vi.hoisted(() => ({
  searchReset: vi.fn(),
  traceReset: vi.fn(),
  impactReset: vi.fn(),
  updateAdrReset: vi.fn(),
  ingestTraceReset: vi.fn(),
  ingestTraceMutate: vi.fn(),
}));

const projectsState = vi.hoisted(() => ({
  data: [
    { name: 'marm-systems', root_path: 'C:/work/marm-systems', nodes: 4500, edges: 23913, status: 'ready' },
    { name: 'second-project', root_path: 'C:/work/second-project', nodes: 12, edges: 30, status: 'ready' },
  ] as Array<Record<string, unknown>>,
  isLoading: false,
}));

vi.mock('@/hooks/use-marm-queries', () => ({
  useProjects: () => projectsState,
  useSearchProjectCode: () => ({ isPending: false, mutate: vi.fn(), reset: mutationState.searchReset }),
  useTraceProject: () => ({ isPending: false, mutate: vi.fn(), reset: mutationState.traceReset }),
  useProjectImpact: () => ({ isPending: false, mutate: vi.fn(), reset: mutationState.impactReset }),
  useProjectArchitecture: () => ({ data: undefined, isLoading: false }),
  useProjectCodeUnits: () => ({ data: undefined, isLoading: false, isError: false }),
  useProjectCodeUnitEdges: () => ({ data: undefined, isLoading: false, isError: false }),
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
}));

function renderExplorer(path = '/explorer') {
  const { hook, navigate } = memoryLocation({ path, record: true });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // React bails out of reconciliation on an identical element reference, so
  // every rerender needs a fresh tree for the mocked hooks to be re-read.
  const tree = () => (
    <QueryClientProvider client={queryClient}>
      <Router hook={hook}>
        <Switch>
          <Route path="/explorer/:name" component={ExplorerPage} />
          <Route path="/explorer" component={ExplorerPage} />
        </Switch>
      </Router>
    </QueryClientProvider>
  );
  const view = render(tree());
  return { view, navigate, rerender: () => view.rerender(tree()) };
}

describe('ExplorerPage', () => {
  afterEach(() => {
    adrState.secondLoading = true;
    adrState.secondContent = undefined;
    projectsState.data = [
      { name: 'marm-systems', root_path: 'C:/work/marm-systems', nodes: 4500, edges: 23913, status: 'ready' },
      { name: 'second-project', root_path: 'C:/work/second-project', nodes: 12, edges: 30, status: 'ready' },
    ];
    vi.clearAllMocks();
    cleanup();
  });

  it('shows every tool as a tab and drops the redundant Investigate menu', () => {
    renderExplorer();

    expect(screen.getByRole('heading', { name: 'Project Explorer' })).toBeTruthy();
    for (const label of ['Architecture', 'Impact', 'Coverage', 'Decisions', 'Runtime traces']) {
      expect(screen.getByRole('tab', { name: label })).toBeTruthy();
    }
    expect(screen.queryByRole('tab', { name: 'Investigate' })).toBeNull();
    expect(screen.queryByRole('tab', { name: 'Code search' })).toBeNull();
    expect(screen.queryByRole('tab', { name: 'Trace symbol' })).toBeNull();
  });

  it('opens the search & trace palette with Ctrl+K', async () => {
    const user = userEvent.setup();
    renderExplorer();

    expect(screen.queryByRole('dialog', { name: 'Search & trace' })).toBeNull();
    await user.keyboard('{Control>}k{/Control}');
    expect(screen.getByRole('dialog', { name: 'Search & trace' })).toBeTruthy();
  });

  it('selects the project named in the URL rather than the first one', () => {
    renderExplorer('/explorer/second-project');

    expect(screen.getByRole('combobox', { name: 'Project' }).textContent).toContain('second-project');
  });

  it('falls back to the first project when the URL names none', () => {
    renderExplorer();

    expect(screen.getByRole('combobox', { name: 'Project' }).textContent).toContain('marm-systems');
  });

  it('points at Indexed Projects when nothing is indexed', () => {
    projectsState.data = [];
    renderExplorer();

    expect(screen.getByRole('heading', { name: 'No indexed repositories yet' })).toBeTruthy();
    expect(screen.queryByRole('tab', { name: 'Architecture' })).toBeNull();
  });

  it('clears decisions while the next project ADR is still loading', async () => {
    const user = userEvent.setup();
    const { navigate, rerender } = renderExplorer();

    await user.click(screen.getByRole('tab', { name: 'Decisions' }));
    await waitFor(() => {
      expect((screen.getByPlaceholderText('# Architecture decisions') as HTMLTextAreaElement).value).toBe('# First project decisions');
    });

    navigate('/explorer/second-project');
    await waitFor(() => {
      expect(screen.getByText('Loading decisions…')).toBeTruthy();
    });
    expect((screen.getByRole('button', { name: 'Save decisions' }) as HTMLButtonElement).disabled).toBe(true);

    adrState.secondLoading = false;
    rerender();
    await waitFor(() => {
      expect((screen.getByPlaceholderText('# Architecture decisions') as HTMLTextAreaElement).value).toBe('');
    });
  });

  it('resets mutation observers when switching projects', async () => {
    const { navigate } = renderExplorer();

    navigate('/explorer/second-project');

    await waitFor(() => {
      expect(mutationState.updateAdrReset).toHaveBeenCalledTimes(2);
      expect(mutationState.ingestTraceReset).toHaveBeenCalledTimes(2);
    });
  });

  it('rejects invalid runtime trace counts before submitting', async () => {
    const user = userEvent.setup();
    renderExplorer();

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
