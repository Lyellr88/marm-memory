import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoriesTab } from './MemoriesTab';

const memoriesState = vi.hoisted(() => ({
  data: { items: [] as unknown[], total: 0, limit: 25, offset: 0 },
  isLoading: false,
  isFetching: false,
  lastParams: undefined as Record<string, unknown> | undefined,
}));
const overviewState = vi.hoisted(() => ({ data: { memory: { active_memories: 440 } } }));
const noop = vi.hoisted(() => () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }));

vi.mock('@/hooks/use-marm-queries', () => ({
  useMemories: (params: Record<string, unknown>) => {
    memoriesState.lastParams = params;
    return memoriesState;
  },
  useFilters: () => ({
    data: {
      sessions: ['s1'],
      projects: ['claude-width-extension', 'RustIRC'],
      platforms: [],
      context_types: [],
    },
  }),
  useOverview: () => overviewState,
  useCreateMemory: noop,
  useUpdateMemory: noop,
  useDeleteMemory: noop,
  useBulkDeleteMemories: noop,
}));

beforeEach(() => {
  memoriesState.data = { items: [], total: 273, limit: 25, offset: 0 };
  memoriesState.lastParams = undefined;
  overviewState.data = { memory: { active_memories: 440 } };
});
afterEach(cleanup);

describe('MemoriesTab project scope', () => {
  it('loads one project rather than the whole store by default', async () => {
    // Listing every project was the old behaviour. One project is a bounded
    // page of rows; the store is the thing that grows.
    render(<MemoriesTab />);
    await waitFor(() =>
      expect(memoriesState.lastParams?.project).toBe('claude-width-extension'),
    );
  });

  it('says what the scope leaves out, and offers the way out', async () => {
    // Showing less is fine. Showing less without saying so is not.
    render(<MemoriesTab />);
    await waitFor(() => expect(screen.getByText(/273 of 440 stored memories/)).toBeTruthy());
    expect(screen.getByRole('button', { name: /show all projects/i })).toBeTruthy();
  });

  it('all projects is available, and drops the scope when chosen', async () => {
    render(<MemoriesTab />);
    await waitFor(() => expect(memoriesState.lastParams?.project).toBeTruthy());

    await userEvent.click(screen.getByRole('button', { name: /show all projects/i }));
    await waitFor(() => expect(memoriesState.lastParams?.project).toBeUndefined());
  });

  it('does not re-apply a default scope after all projects is chosen', async () => {
    // The effect that picks a default must not fight the user's choice.
    render(<MemoriesTab />);
    await waitFor(() => expect(memoriesState.lastParams?.project).toBeTruthy());
    await userEvent.click(screen.getByRole('button', { name: /show all projects/i }));

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(memoriesState.lastParams?.project).toBeUndefined();
  });

  it('says nothing about scope when the scope holds everything', async () => {
    memoriesState.data = { items: [], total: 440, limit: 25, offset: 0 };
    render(<MemoriesTab />);
    await waitFor(() => expect(memoriesState.lastParams?.project).toBeTruthy());
    expect(screen.queryByText(/stored memories/)).toBeNull();
  });
});
