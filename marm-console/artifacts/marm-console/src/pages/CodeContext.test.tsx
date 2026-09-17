import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CodeContextPage } from './CodeContext';
import type { CodeContextResult, CodeContextSymbol } from '@/lib/marm-types';

// The graph pane renders a canvas-backed force simulation; jsdom has no canvas,
// and what this page owns is the adapter, not the renderer.
vi.mock('react-force-graph-2d', () => ({ default: () => null }));

// jsdom has no matchMedia, and the shared GraphViz asks it about reduced
// motion before it draws anything.
globalThis.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: () => {},
  removeListener: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
  dispatchEvent: () => false,
})) as unknown as typeof window.matchMedia;

// jsdom has no ResizeObserver, and the pane measures its container with one.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

const buildState = vi.hoisted(() => ({
  mutate: vi.fn(),
  data: undefined as CodeContextResult | undefined,
  error: null as unknown,
  isPending: false,
}));

const DEFAULT_PROJECTS = [
  {
    name: 'C-work-marm-systems',
    display_name: 'marm-systems',
    root_path: 'C:/work/marm-systems',
    nodes: 4500,
    edges: 23913,
  },
];

const projectState = vi.hoisted(() => ({
  status: 'ready' as string,
  // Mutable so a test can vary the LIST, not only one project's status.
  list: null as Array<Record<string, unknown>> | null,
}));

vi.mock('@/hooks/use-marm-queries', () => ({
  useProjects: () => ({
    data: (projectState.list ?? DEFAULT_PROJECTS).map((p) => ({
      ...p,
      status: projectState.status,
    })),
    isLoading: false,
  }),
  useBuildCodeContext: () => buildState,
}));

function symbol(over: Partial<CodeContextSymbol> = {}): CodeContextSymbol {
  return {
    name: 'rank_memories',
    qualified_name: 'marm.recall.rank_memories',
    label: 'Function',
    file_path: 'marm/recall.py',
    start_line: 10,
    end_line: 11,
    score: 0.5,
    seeded: true,
    truncated: false,
    source: 'def rank_memories():\n    return []',
    provenance: null,
    ...over,
  };
}

const SUCCESS: CodeContextResult = {
  status: 'success',
  project: { name: 'C-work-marm-systems', short_name: 'marm-systems', root_path: 'C:/work/marm-systems' },
  task: 'how does recall rank',
  markdown: '# Code context for: how does recall rank',
  graph_nodes: 34,
  notes: [],
  links: [],
  memories: [{ id: 'm1', content: 'ranking   is personalised   PageRank', similarity: 0.81, context_type: 'decision' }],
  graph_edges: [['marm.recall.rank_memories', 'marm.recall.seed_query', 0.9]],
  symbols: [
    symbol(),
    symbol({
      name: 'seed_query',
      qualified_name: 'marm.recall.seed_query',
      file_path: 'marm/terms.py',
      start_line: 50,
      end_line: 50,
      score: 0.01,
      seeded: false,
      truncated: true,
      source: 'def seed_query():',
      provenance: { hop: 2, strategy: 'heuristic', confidence: 0.28, risk: 'CRITICAL' },
    }),
  ],
};

afterEach(() => {
  projectState.list = null;   // ordering must not leak between tests
  cleanup();
  buildState.mutate = vi.fn();
  buildState.data = undefined;
  buildState.error = null;
  buildState.isPending = false;
  projectState.status = 'ready';
  window.history.replaceState(null, '', '/');
});

/** Open the Symbols pane.
 *
 *  `Answer` is the landing tab now — someone who typed a question wants the
 *  answer first and the evidence under it — so assertions about symbol
 *  rendering have to switch panes. Radix does not mount an inactive one.
 */
async function openSymbols() {
  await userEvent.click(screen.getByRole('tab', { name: /ranked symbols/i }));
}

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
      include_graph: true,
      // Asking is on by default on the page: a reader who typed a question
      // wants it answered. The tool's own default stays off, for agents.
      answer: true,
      // The page lays the parts out separately, so it needs the structured
      // fields the markdown duplicates. The server default is 1 for agents.
      detail: 3,
    });
  });

  it('does not submit a task that is only whitespace', async () => {
    const user = userEvent.setup();
    render(<CodeContextPage />);

    await user.type(screen.getByLabelText('Task'), '   ');

    expect(screen.getByRole('button', { name: /compose context/i }).hasAttribute('disabled')).toBe(true);
    expect(buildState.mutate).not.toHaveBeenCalled();
  });

  it('defaults the project to a real one rather than to path resolution', async () => {
    // Omitting project makes the server resolve from the CONSOLE's working
    // directory, which is not an indexed repository. Left blank, the first
    // click returned no_project every time. The trigger shows display_name;
    // the payload carries the key, and that is what proves the fix.
    const user = userEvent.setup();
    render(<CodeContextPage />);

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Project' }).textContent).toContain('marm-systems'),
    );

    await user.type(screen.getByLabelText('Task'), 'anything');
    await user.click(screen.getByRole('button', { name: /compose context/i }));

    await waitFor(() => expect(buildState.mutate).toHaveBeenCalledTimes(1));
    expect(buildState.mutate.mock.calls[0][0].project).toBe('C-work-marm-systems');
  });

  it('says it is working while a composition is in flight', () => {
    // The whole content well used to render blank for the duration.
    buildState.isPending = true;
    render(<CodeContextPage />);

    expect(screen.getByText('Composing code context…')).toBeTruthy();
  });

  it('offers all five panes before a composition exists', () => {
    // The strip used to be hidden until a composition returned, so the page
    // read as a lone text box and the panes looked unbuilt.
    render(<CodeContextPage />);

    const tabs = screen.getAllByRole('tab').map((el) => el.textContent ?? '');
    expect(tabs).toHaveLength(5);
    for (const label of ['Ask', 'Ranked symbols', 'Call graph', 'What memory knows', 'Agent view']) {
      expect(tabs.some((text) => text.includes(label))).toBe(true);
    }
  });

  it('a pane selected before a composition previews what it will show', async () => {
    render(<CodeContextPage />);

    await userEvent.click(screen.getByRole('tab', { name: /call graph/i }));
    expect(screen.getByText(/Compose a task above to fill this pane/)).toBeTruthy();
    expect(
      screen.getByText(/The ranked call neighbourhood the scores were computed over/),
    ).toBeTruthy();
  });

  it('asking works with no composition yet, and needs a task first', async () => {
    // "Compose first, then ask" is an order a reader should not have to learn.
    render(<CodeContextPage />);

    const ask = screen.getByRole('button', { name: /compose and answer/i });
    expect(ask.hasAttribute('disabled')).toBe(true);

    await userEvent.type(screen.getByLabelText('Task'), 'how does recall rank');
    expect(screen.getByRole('button', { name: /compose and answer/i }).hasAttribute('disabled')).toBe(
      false,
    );

    await userEvent.click(screen.getByRole('button', { name: /compose and answer/i }));
    expect(buildState.mutate).toHaveBeenCalledTimes(1);
    expect(buildState.mutate.mock.calls[0][0].answer).toBe(true);
  });

  it('names the panes identically before and after a composition', () => {
    // One strip does both jobs now, so the old empty-state card grid is gone
    // and with it the chance for the two lists to disagree. What is still
    // worth pinning is that composing does not reorder or rename them.
    const labels = ['Ask', 'Ranked symbols', 'Call graph', 'What memory knows', 'Agent view'];
    const { unmount } = render(<CodeContextPage />);
    const before = screen.getAllByRole('tab').map((el) => el.textContent ?? '');
    unmount();

    buildState.data = SUCCESS;
    render(<CodeContextPage />);
    const after = screen.getAllByRole('tab').map((el) => el.textContent ?? '');

    expect(labels.every((label, i) => before[i].includes(label))).toBe(true);
    expect(labels.every((label, i) => after[i].includes(label))).toBe(true);
  });

  it('an example task fills the box without submitting', async () => {
    const user = userEvent.setup();
    render(<CodeContextPage />);

    await user.click(screen.getByRole('button', { name: /how does recall decide/i }));

    expect((screen.getByLabelText('Task') as HTMLTextAreaElement).value).toBe(
      'How does recall decide which memories to return?',
    );
    expect(buildState.mutate).not.toHaveBeenCalled();
  });

  it('warns when the selected project is not finished indexing', () => {
    // A no_project after a long wait is a worse way to learn this.
    projectState.status = 'indexing';
    render(<CodeContextPage />);

    expect(screen.getByText('Index status')).toBeTruthy();
    expect(screen.getByTitle('indexing')).toBeTruthy();
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

  it('summarises the composition in the metric row', () => {
    buildState.data = SUCCESS;
    render(<CodeContextPage />);

    expect(screen.getByTitle('marm-systems')).toBeTruthy();
    expect(screen.getByText('Call neighbourhood')).toBeTruthy();
  });

  it('groups symbols by file, best-ranked file first', async () => {
    buildState.data = SUCCESS;
    render(<CodeContextPage />);
    await openSymbols();

    // marm/recall.py holds the 0.5 symbol; marm/terms.py the 0.01 one.
    const headers = screen.getAllByTitle(/^marm\/(recall|terms)\.py$/);
    expect(headers[0].textContent).toContain('marm/recall.py');
  });

  it('distinguishes a seeded symbol from one reached through the call graph', async () => {
    buildState.data = SUCCESS;
    render(<CodeContextPage />);
    await openSymbols();

    expect(screen.getByText('matched the task')).toBeTruthy();
    expect(screen.getByText('2 hop')).toBeTruthy();
  });

  it('flags a heuristic edge, because it can bind across module boundaries', async () => {
    buildState.data = SUCCESS;
    render(<CodeContextPage />);
    await openSymbols();

    // The page footnote also explains "heuristic", so scope to the badge.
    const badge = screen.getByTitle(/bind across module boundaries/);
    expect(badge.textContent).toContain('heuristic');
    expect(badge.className).toContain('amber');
    expect(screen.getByText('CRITICAL')).toBeTruthy();
  });

  it('numbers source lines from the symbol start, not from one', async () => {
    buildState.data = SUCCESS;
    render(<CodeContextPage />);
    await openSymbols();

    // The seeded symbol starts at line 10 and has two lines.
    expect(screen.getByText('10')).toBeTruthy();
    expect(screen.getByText('11')).toBeTruthy();
  });

  it('filters symbols by name or file', async () => {
    const user = userEvent.setup();
    buildState.data = SUCCESS;
    render(<CodeContextPage />);
    await openSymbols();

    await user.type(screen.getByLabelText('Filter symbols'), 'terms');

    expect(screen.queryByTitle('marm/recall.py')).toBeNull();
    expect(screen.getByTitle('marm/terms.py')).toBeTruthy();
  });

  it('collapses a file group', async () => {
    const user = userEvent.setup();
    buildState.data = SUCCESS;
    render(<CodeContextPage />);
    await openSymbols();

    expect(screen.getByText('def rank_memories():')).toBeTruthy();

    await user.click(screen.getByTitle('marm/recall.py').closest('button')!);

    expect(screen.queryByText('def rank_memories():')).toBeNull();
  });

  it('shows the whole memory record, not only its content', async () => {
    const user = userEvent.setup();
    buildState.data = SUCCESS;
    render(<CodeContextPage />);

    await user.click(screen.getByRole('tab', { name: /what memory knows/i }));

    expect(screen.getByText('ranking is personalised PageRank')).toBeTruthy();
    expect(screen.getByText('0.810')).toBeTruthy();
    expect(screen.getByText('decision')).toBeTruthy();
  });

  it('does not claim memory knows nothing when recall never ran', async () => {
    const user = userEvent.setup();
    buildState.data = { ...SUCCESS, memories: [], links: [], notes: ['memory recall unavailable'] };
    render(<CodeContextPage />);

    await user.click(screen.getByRole('tab', { name: /what memory knows/i }));

    expect(screen.getByText('Memory recall was unavailable')).toBeTruthy();
    expect(screen.queryByText(/records nothing about these symbols/)).toBeNull();
  });

  it('offers to raise the budget when the output was truncated', async () => {
    const user = userEvent.setup();
    buildState.data = { ...SUCCESS, notes: ['output truncated at the character budget'] };
    render(<CodeContextPage />);

    await user.click(screen.getByRole('button', { name: /raise to 24,000/i }));

    await waitFor(() => expect(buildState.mutate).toHaveBeenCalledTimes(1));
    expect(buildState.mutate.mock.calls[0][0].budget).toBe(24000);
  });

  it('prefills and composes from a deep link', async () => {
    window.history.replaceState(null, '', '/?task=how+does+recall+rank&project=C-work-marm-systems&run=1');
    render(<CodeContextPage />);

    expect((screen.getByLabelText('Task') as HTMLTextAreaElement).value).toBe('how does recall rank');
    await waitFor(() => expect(buildState.mutate).toHaveBeenCalledTimes(1));
    expect(buildState.mutate.mock.calls[0][0].task).toBe('how does recall rank');
  });

  it('prefills without composing when the link does not ask it to', () => {
    window.history.replaceState(null, '', '/?task=how+does+recall+rank');
    render(<CodeContextPage />);

    expect((screen.getByLabelText('Task') as HTMLTextAreaElement).value).toBe('how does recall rank');
    expect(buildState.mutate).not.toHaveBeenCalled();
  });

  it('copies the composed markdown', async () => {
    const user = userEvent.setup();
    buildState.data = SUCCESS;
    render(<CodeContextPage />);

    await user.click(screen.getByRole('tab', { name: /agent view/i }));
    await user.click(screen.getByRole('button', { name: /copy the composed markdown/i }));

    await waitFor(async () =>
      expect(await navigator.clipboard.readText()).toBe('# Code context for: how does recall rank'),
    );
  });

  it('draws the call neighbourhood it ranked over', async () => {
    const user = userEvent.setup();
    buildState.data = SUCCESS;
    render(<CodeContextPage />);

    await user.click(screen.getByRole('tab', { name: /call graph/i }));

    // Rendered by the Knowledge Graph's own GraphViz now, so this asserts the
    // adapted data and the legend rather than a bespoke canvas.
    expect(screen.getByText(/1 call edges/)).toBeTruthy();
    expect(screen.getByText('matched the task')).toBeTruthy();
    expect(screen.getByText('reached via the call graph')).toBeTruthy();
  });

});
