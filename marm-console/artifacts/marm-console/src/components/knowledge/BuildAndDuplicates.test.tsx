import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BuildConceptsDialog } from './BuildAndDuplicates';

const retryBuild = vi.fn();
const deleteGraph = vi.fn();
const startBuild = vi.fn();
let legacyNames = { count: 0, checked: 0, sample: [] as string[] };

vi.mock('@/hooks/use-marm-queries', () => ({
  useBuildConcepts: () => ({ isPending: false, mutate: startBuild }),
  useConceptLegacyNames: () => ({ data: legacyNames }),
  useMarmConfig: () => ({ baseUrl: '/api' }),
  useFilters: () => ({ data: { sessions: [], projects: [] } }),
  useConceptsSummary: () => ({ data: { entities: 4, relationships: 2, code_links: 1, schema_status: 'current' } }),
  useConceptBuild: () => ({ data: undefined }),
  useConceptBuilds: () => ({
    data: [{
      id: 'cancelled-run',
      scope_type: 'project',
      scope_value: 'marm',
      status: 'cancelled',
      created_at: '2026-08-21T12:00:00+00:00',
      started_at: '2026-08-21T12:00:00+00:00',
      memories_processed: 3,
      memories_total: 5,
      entities_extracted: 2,
      relationships_created: 1,
      code_links_created: 0,
      duration_ms: 1000,
      error_code: 'cancelled_by_user',
    }],
    isLoading: false,
  }),
  useStopConceptBuild: () => ({ isPending: false, mutate: vi.fn() }),
  useRetryConceptBuild: () => ({ isPending: false, mutate: retryBuild }),
  useDeleteConceptGraph: () => ({ isPending: false, mutate: deleteGraph }),
  useConceptDuplicates: () => ({ data: { items: [], total: 0 }, isLoading: false }),
  useConcept: () => ({ data: undefined }),
  useDismissConceptDuplicate: () => ({ isPending: false, mutate: vi.fn() }),
  useMergeConceptDuplicate: () => ({ isPending: false, mutate: vi.fn() }),
  useRemoveConceptEntity: () => ({ isPending: false, mutate: vi.fn() }),
}));

afterEach(() => {
  cleanup();
  retryBuild.mockClear();
  deleteGraph.mockReset();
  startBuild.mockClear();
  legacyNames = { count: 0, checked: 0, sample: [] };
});

describe('BuildConceptsDialog', () => {
  it('keeps build controls and recent runs together, with a nested reset confirmation', async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <BuildConceptsDialog
          open
          onOpenChange={vi.fn()}
          jobId={null}
          onJobIdChange={vi.fn()}
          onComplete={vi.fn()}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByRole('heading', { name: 'Build from memory' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Recent runs' })).toBeTruthy();
    expect(screen.getByText('Stopped by user; partial scoped extraction remains.')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(retryBuild).toHaveBeenCalledWith('cancelled-run', expect.any(Object));

    await user.click(screen.getByRole('button', { name: 'Reset graph' }));
    const confirmation = screen.getByRole('dialog', { name: 'Reset the concept graph?' });
    await user.click(within(confirmation).getByRole('button', { name: 'Reset graph' }));
    expect(deleteGraph).toHaveBeenCalledWith(undefined, expect.any(Object));
  });

  function renderDialog() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <BuildConceptsDialog open onOpenChange={vi.fn()} jobId={null} onJobIdChange={vi.fn()} onComplete={vi.fn()} />
      </QueryClientProvider>,
    );
  }

  it('shows no legacy-name notice for a clean graph', () => {
    renderDialog();
    expect(screen.queryByRole('status', { name: 'Legacy concept names' })).toBeNull();
  });

  it('advises a rebuild and runs it as a reset followed by the global build', async () => {
    const user = userEvent.setup();
    legacyNames = { count: 2, checked: 10, sample: ['**apply**', '`claim()`'] };
    deleteGraph.mockImplementation((_input, options) => options?.onSuccess?.());
    renderDialog();

    const notice = screen.getByRole('status', { name: 'Legacy concept names' });
    expect(within(notice).getByText('**apply**')).toBeTruthy();
    await user.click(within(notice).getByRole('button', { name: 'Rebuild graph' }));

    const confirmation = screen.getByRole('dialog', { name: 'Reset the concept graph?' });
    expect(within(confirmation).getByText(/Build Concepts runs over all memory/)).toBeTruthy();
    expect(startBuild).not.toHaveBeenCalled();
    await user.click(within(confirmation).getByRole('button', { name: 'Reset graph' }));

    expect(deleteGraph).toHaveBeenCalledTimes(1);
    expect(startBuild).toHaveBeenCalledWith({ search_all: true }, expect.any(Object));
  });

  it('forgets a cancelled rebuild, so a later plain reset does not rebuild', async () => {
    const user = userEvent.setup();
    legacyNames = { count: 1, checked: 3, sample: ['**apply**'] };
    deleteGraph.mockImplementation((_input, options) => options?.onSuccess?.());
    renderDialog();

    await user.click(screen.getByRole('button', { name: 'Rebuild graph' }));
    await user.click(within(screen.getByRole('dialog', { name: 'Reset the concept graph?' })).getByRole('button', { name: 'Cancel' }));
    await user.click(screen.getAllByRole('button', { name: 'Reset graph' })[0]);
    await user.click(within(screen.getByRole('dialog', { name: 'Reset the concept graph?' })).getByRole('button', { name: 'Reset graph' }));

    expect(deleteGraph).toHaveBeenCalledTimes(1);
    expect(startBuild).not.toHaveBeenCalled();
  });
});
