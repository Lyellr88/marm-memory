import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BuildConceptsDialog } from './BuildAndDuplicates';

const retryBuild = vi.fn();
const deleteGraph = vi.fn();

vi.mock('@/hooks/use-marm-queries', () => ({
  useBuildConcepts: () => ({ isPending: false, mutate: vi.fn() }),
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
  deleteGraph.mockClear();
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
});
