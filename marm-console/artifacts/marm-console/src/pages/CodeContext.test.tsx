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

const projectState = vi.hoisted(() => ({ status: 'ready' as string }));

vi.mock('@/hooks/use-marm-queries', () => ({
  useProjects: () => ({
    data: [
      {
        name: 'C-work-marm-systems',
        display_name: 'marm-systems',
        root_path: 'C:/work/marm-systems',
        nodes: 4500,
        edges: 23913,
        status: projectState.status,
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
  projectState.status = 'ready';
});

describe('CodeContextPage', () => {
  it('sends the trimmed task with the selected project and budget', async () => {
    const user = userEvent.setup();
    render(<CodeContextPage />);

    await user.type(screen.getByLabelText('Task'), '  how does recall rank  ');
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

  it('defaults the project to a real one rather than to path resolution', async () => {
    // Omitting project makes the server resolve from the CONSOLE's working
    // directory, which is wherever the service was started and is not an
    // indexed repository. Left blank, the first click always returned
    // no_project.
    const user = userEvent.setup();
    render(<CodeContextPage />);

    await waitFor(() =>
      expect((screen.getByLabelText('Project') as HTMLSelectElement).value).toBe('C-work-marm-systems'),
    );

    await user.type(screen.getByLabelText('Task'), 'anything');
    await user.click(screen.getByRole('button', { name: /compose context/i }));

    await waitFor(() => expect(buildState.mutate).toHaveBeenCalledTimes(1));
    expect(buildState.mutate.mock.calls[0][0].project).toBe('C-work-marm-systems');
  });

  it('describes every pane before a composition exists', () => {
    // The panes render only once there is a result, so without this the page
    // reads as a single text box and the features look unbuilt.
    render(<CodeContextPage />);

    expect(screen.getByText('What you get back')).toBeTruthy();
    for (const label of ['Ranked symbols', 'What memory knows', 'Agent view']) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    expect(screen.queryByRole('tab')).toBeNull();
  });

  it('names the same panes in the empty state and in the tab strip', () => {
    const { unmount } = render(<CodeContextPage />);
    const empty = ['Ranked symbols', 'What memory knows', 'Agent view']
      .filter((l) => screen.queryByText(l));
    unmount();

    buildState.data = SUCCESS;
    render(<CodeContextPage />);
    const tabs = screen.getAllByRole('tab').map((el) => el.textContent?.trim());

    expect(empty).toEqual(tabs);
  });

  it('an example task fills the box without submitting', async () => {
    const user = userEvent.setup();
    render(<CodeContextPage />);

    const example = screen.getByRole('button', { name: /how does recall decide/i });
    await user.click(example);

    expect((screen.getByLabelText('Task') as HTMLTextAreaElement).value)
      .toBe('How does recall decide which memories to return?');
    expect(buildState.mutate).not.toHaveBeenCalled();
  });

  it('warns when the selected project is not finished indexing', () => {
    // A no_project after a 30s wait is a worse way to learn this.
    projectState.status = 'indexing';
    render(<CodeContextPage />);

    expect(screen.getByText(/index status: indexing/i)).toBeTruthy();
  });
});
