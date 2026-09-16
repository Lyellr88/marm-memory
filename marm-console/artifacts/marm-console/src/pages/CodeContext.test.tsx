import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CodeContextPage } from './CodeContext';
import type { CodeContextResult } from '@/lib/marm-types';

const buildState = vi.hoisted(() => ({
  mutate: vi.fn(),
  data: undefined as CodeContextResult | undefined,
  error: null as unknown,
  isPending: false,
}));

vi.mock('@/hooks/use-marm-queries', () => ({
  useProjects: () => ({
    data: [
      {
        name: 'C-work-marm-systems',
        display_name: 'marm-systems',
        root_path: 'C:/work/marm-systems',
        nodes: 4500,
        edges: 23913,
        status: 'ready',
      },
    ],
    isLoading: false,
  }),
  useBuildCodeContext: () => buildState,
}));

const SUCCESS: CodeContextResult = {
  status: 'success',
  project: { name: 'C-work-marm-systems', short_name: 'marm-systems', root_path: 'C:/work/marm-systems' },
  task: 'how does recall rank',
  markdown: '# Code context for: how does recall rank',
  graph_nodes: 34,
  notes: [],
  links: [],
  memories: [{ content: 'ranking   is personalised   PageRank' }],
  symbols: [
    {
      name: 'rank_memories',
      qualified_name: 'marm.recall.rank_memories',
      label: 'Function',
      file_path: 'marm/recall.py',
      start_line: 10,
      end_line: 40,
      score: 0.07157,
      seeded: true,
      truncated: false,
      source: 'def rank_memories():\n    return []',
    },
    {
      name: 'seed_query',
      qualified_name: 'marm.recall.seed_query',
      label: 'Function',
      file_path: 'marm/recall.py',
      start_line: 50,
      end_line: 60,
      score: 0.01,
      seeded: false,
      truncated: true,
      source: 'def seed_query():',
    },
  ],
};

afterEach(() => {
  cleanup();
  buildState.mutate = vi.fn();
  buildState.data = undefined;
  buildState.error = null;
  buildState.isPending = false;
});

describe('CodeContextPage', () => {
  it('sends the trimmed task with the selected project and budget', async () => {
    const user = userEvent.setup();
    render(<CodeContextPage />);

    await user.type(screen.getByLabelText('Task'), '  how does recall rank  ');
    await user.selectOptions(screen.getByLabelText('Project'), 'C-work-marm-systems');
    await user.click(screen.getByRole('button', { name: /compose context/i }));

    await waitFor(() => expect(buildState.mutate).toHaveBeenCalledTimes(1));
    expect(buildState.mutate).toHaveBeenCalledWith({
      task: 'how does recall rank',
      project: 'C-work-marm-systems',
      budget: 12000,
    });
  });

  it('does not submit a task that is only whitespace', async () => {
    const user = userEvent.setup();
    render(<CodeContextPage />);

    await user.type(screen.getByLabelText('Task'), '   ');

    expect(screen.getByRole('button', { name: /compose context/i }).hasAttribute('disabled')).toBe(true);
    expect(buildState.mutate).not.toHaveBeenCalled();
  });

  it('distinguishes a seeded symbol from one pulled in by the call graph', () => {
    buildState.data = SUCCESS;
    render(<CodeContextPage />);

    expect(screen.getByText('matched the task')).toBeTruthy();
    expect(screen.getByText('via call graph')).toBeTruthy();
    expect(screen.getByText(/truncated to fit the character budget/i)).toBeTruthy();
    // The project selector also renders this label, so scope to the summary.
    expect(screen.getByText('marm-systems', { selector: 'span' })).toBeTruthy();
    expect(screen.getByText('34 nodes')).toBeTruthy();
  });

  it('renders a no_project answer with its hint instead of an error', () => {
    buildState.data = {
      status: 'no_project',
      message: 'no indexed project matches this directory',
      hint: "Call marm_graph_index(action='list') to see indexed projects.",
    };
    render(<CodeContextPage />);

    expect(screen.getByText('no indexed project matches this directory')).toBeTruthy();
    expect(screen.getByText(/see indexed projects/)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('collapses runs of whitespace in a memory so one memory stays one line', async () => {
    const user = userEvent.setup();
    buildState.data = SUCCESS;
    render(<CodeContextPage />);

    await user.click(screen.getByRole('tab', { name: /what memory knows/i }));

    expect(screen.getByText('ranking is personalised PageRank')).toBeTruthy();
  });
});
