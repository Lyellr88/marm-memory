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
  // The "Ask runs on" bar reads this. Returning a llama.cpp shape rather than
  // undefined keeps the bar rendered in these tests, so a change that breaks
  // it fails here instead of only in the browser.
  useRuntimeSettings: () => ({
    data: {
      llm: {
        configured: true,
        enabled: true,
        endpoint: 'http://127.0.0.1:18080',
        available: true,
        model: 'qwen3.6-27b-mtp',
        model_in_use: 'qwen3.6-27b-mtp',
        preferred_model: null,
        loopback_enforced: true,
        runtime: 'llama.cpp',
        runtime_version: null,
        can_switch: false,
        model_path: '/models/Qwen3.6-27B-IQ4_NL.gguf',
        context_length: 65536,
        served: [],
        switch_blocked_reason: null,
      },
      hardware: {
        detected: true,
        platform: 'Linux',
        gpus: [
          {
            index: 0,
            vendor: 'NVIDIA',
            name: 'NVIDIA GeForce RTX 3090',
            memory_total_mb: 24576,
            memory_used_mb: 20296,
            memory_free_mb: 3879,
            utilisation_percent: 11,
            driver: '615.71.09',
            unified: false,
          },
        ],
      },
    },
  }),
  useProjects: () => ({
    data: (projectState.list ?? DEFAULT_PROJECTS).map((p) => ({
      ...p,
      status: projectState.status,
    })),
    isLoading: false,
  }),
  useBuildCodeContext: () => buildState,
  useStreamingAnswer: () => answerState,
}));

const answerState = vi.hoisted(() => ({
  status: 'idle' as 'idle' | 'streaming' | 'done' | 'error',
  text: '',
  citations: [] as unknown[],
  model: undefined as string | undefined,
  start: vi.fn(),
  reset: vi.fn(),
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
  answerState.status = 'idle';
  answerState.text = '';
  answerState.citations = [];
  answerState.model = undefined;
  answerState.start = vi.fn();
  answerState.reset = vi.fn();
  for (const key of ['grounding', 'unresolved', 'hint', 'packet', 'verification', 'modelInfo', 'analyst']) {
    delete (answerState as Record<string, unknown>)[key];
  }
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
    expect(buildState.mutate.mock.calls[0][0]).toEqual({
      task: 'how does recall rank',
      project: 'C-work-marm-systems',
      budget: 12000,
      include_graph: true,
      // The answer arrives on its own stream now, so the JSON body never waits
      // for generation. Retrieval lands in ~380 ms; generation takes seconds.
      answer: false,
      // The page lays the parts out separately, so it needs the structured
      // fields the markdown duplicates. The server default is 1 for agents.
      detail: 3,
    });
  });

  it('does not ask the model unless the reader opts in', async () => {
    // Generation is opt-in: composing context must not also start a model.
    const user = userEvent.setup();
    render(<CodeContextPage />);

    const box = screen.getByRole('checkbox', { name: /answer it too/i });
    expect((box as HTMLInputElement).checked).toBe(false);

    await user.type(screen.getByLabelText('Task'), 'how does recall rank');
    await user.click(screen.getByRole('button', { name: /compose context/i }));

    expect(answerState.start).not.toHaveBeenCalled();
    expect(buildState.mutate).toHaveBeenCalledTimes(1);
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

  it('renders an answer as it streams, before it is finished', () => {
    // The whole point: 8.6 s of nothing reads as a hung page. Partial text on
    // screen reads as a working one.
    answerState.status = 'streaming';
    answerState.text = 'The PPU triggers an NMI when';
    render(<CodeContextPage />);

    expect(screen.getByText(/The PPU triggers an NMI when/)).toBeTruthy();
  });

  it('does not call an answer grounded while it is still arriving', () => {
    // Grounding is decided on the finished text; a marker may still be arriving.
    answerState.status = 'streaming';
    answerState.text = 'rank_memories sorts by';
    render(<CodeContextPage />);

    expect(screen.getByText('answering…')).toBeTruthy();
    expect(screen.queryByText('grounded answer')).toBeNull();
  });

  it('calls a finished answer grounded only when the server verified it', () => {
    answerState.status = 'done';
    answerState.text = 'It sorts [rank_memories].';
    (answerState as Record<string, unknown>).grounding = 'ok';
    render(<CodeContextPage />);

    expect(screen.getByText('grounded answer')).toBeTruthy();
    delete (answerState as Record<string, unknown>).grounding;
  });

  it('labels an unverified streamed answer and says why', () => {
    answerState.status = 'done';
    answerState.text = 'It calls [persist_all_rows].';
    Object.assign(answerState as Record<string, unknown>, {
      grounding: 'unverified',
      unresolved: ['persist_all_rows'],
      hint: 'The answer cites persist_all_rows, which the composed context does not contain.',
    });
    render(<CodeContextPage />);

    expect(screen.queryByText('grounded answer')).toBeNull();
    expect(screen.getByText(/^unverified$/i)).toBeTruthy();
    expect(screen.getByText(/which the composed context does not contain/)).toBeTruthy();
    // The text is still shown -- it is labelled, not hidden.
    expect(screen.getByText(/It calls/)).toBeTruthy();
    for (const key of ['grounding', 'unresolved', 'hint']) {
      delete (answerState as Record<string, unknown>)[key];
    }
  });

  it('links every name in a bracket that cites more than one symbol', () => {
    answerState.status = 'done';
    answerState.text = 'It ranks, then seeds [rank_memories, `seed_query`; invented_thing].';
    answerState.citations = [
      { name: 'rank_memories', qualified_name: 'marm.recall.rank_memories', file_path: 'marm/recall.py', start_line: 10 },
      { name: 'seed_query', qualified_name: 'marm.recall.seed_query', file_path: 'marm/terms.py', start_line: 50 },
    ];
    Object.assign(answerState as Record<string, unknown>, { grounding: 'unverified', unresolved: ['invented_thing'] });
    render(<CodeContextPage />);

    expect(screen.getByRole('button', { name: 'rank_memories' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'seed_query' })).toBeTruthy();
    // Unresolved stays plain text: a link that goes nowhere looks like evidence.
    expect(screen.queryByRole('button', { name: 'invented_thing' })).toBeNull();
    expect(screen.getByText(/invented_thing/)).toBeTruthy();
    for (const key of ['grounding', 'unresolved']) delete (answerState as Record<string, unknown>)[key];
  });

  it('labels an unverified JSON answer the same way', () => {
    buildState.data = {
      ...SUCCESS,
      answer: 'It sorts, somehow.',
      answer_status: 'unverified',
      answer_citations: [],
      answer_hint: 'No citation in the answer resolves to a symbol in the composed context.',
    };
    render(<CodeContextPage />);

    expect(screen.queryByText('grounded answer')).toBeNull();
    expect(screen.getByText(/^unverified$/i)).toBeTruthy();
    expect(screen.getByText(/No citation in the answer resolves/)).toBeTruthy();
  });

  it('a streaming answer does not wait for the composition', () => {
    // There is no `result` at all here -- retrieval has not returned yet and
    // the answer is already on screen.
    answerState.status = 'streaming';
    answerState.text = 'partial';
    buildState.data = undefined;
    render(<CodeContextPage />);

    expect(screen.getByText(/partial/)).toBeTruthy();
  });

  it('a failed stream says so without discarding the rest of the page', () => {
    answerState.status = 'error';
    answerState.text = '';
    (answerState as Record<string, unknown>).message = 'No local model is reachable.';
    buildState.data = SUCCESS;
    render(<CodeContextPage />);

    expect(screen.getByText('No local model is reachable.')).toBeTruthy();
    expect(screen.getByText(/ranked symbols, their source and/)).toBeTruthy();
    delete (answerState as Record<string, unknown>).message;
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
    // One request: the stream composes, sends that composition, then answers
    // from it. A separate compose would be a second retrieval the answer was
    // not written from.
    expect(buildState.mutate).not.toHaveBeenCalled();
    expect(answerState.start).toHaveBeenCalledTimes(1);
    expect(answerState.start.mock.calls[0][0]).toMatchObject({
      task: 'how does recall rank',
      include_graph: true,
      detail: 3,
    });
  });

  it('renders the panes from the composition the answer was written from', async () => {
    const user = userEvent.setup();
    render(<CodeContextPage />);
    await user.type(screen.getByLabelText('Task'), 'how does recall rank');
    await user.click(screen.getByRole('checkbox', { name: /answer it too/i }));
    await user.click(screen.getByRole('button', { name: /compose context/i }));
    expect(buildState.mutate).not.toHaveBeenCalled();

    // A stale JSON composition must not be what the panes show.
    buildState.data = { ...SUCCESS, symbols: [symbol({ name: 'stale_symbol' })] };
    (answerState as Record<string, unknown>).context = SUCCESS;
    answerState.status = 'streaming';
    await user.click(screen.getByRole('tab', { name: /ranked symbols/i }));

    expect(screen.getAllByText('rank_memories').length).toBeGreaterThan(0);
    expect(screen.queryByText('stale_symbol')).toBeNull();
    delete (answerState as Record<string, unknown>).context;
  });

  it('shows a composition the stream could not produce as the usual notice', async () => {
    const user = userEvent.setup();
    render(<CodeContextPage />);
    await user.type(screen.getByLabelText('Task'), 'how does recall rank');
    await user.click(screen.getByRole('checkbox', { name: /answer it too/i }));
    await user.click(screen.getByRole('button', { name: /compose context/i }));

    (answerState as Record<string, unknown>).context = {
      status: 'no_project',
      message: 'no indexed project matches',
      hint: 'Call marm_graph_index(action=list) to see indexed projects.',
    };
    answerState.status = 'done';
    await user.click(screen.getByRole('tab', { name: /ranked symbols/i }));

    expect(screen.getByText(/no indexed project matches/)).toBeTruthy();
    delete (answerState as Record<string, unknown>).context;
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

  it('raises the budget the result was composed under, not the edited box', async () => {
    // The box stays editable after the result renders, so reading it here
    // would let a lowered number turn "Raise to" into a cut -- the label
    // promising more while the request asks for less.
    const user = userEvent.setup();
    buildState.mutate = vi.fn((_vars, options?: { onSuccess?: () => void }) => {
      buildState.data = { ...SUCCESS, notes: ['output truncated at the character budget'] };
      options?.onSuccess?.();
    });
    render(<CodeContextPage />);

    await user.type(screen.getByLabelText('Task'), 'how does recall rank');
    await user.click(screen.getByRole('button', { name: /compose context/i }));
    await screen.findByRole('button', { name: /raise to 24,000/i });

    const box = screen.getByLabelText('Source budget');
    await user.clear(box);
    await user.type(box, '500');

    expect(screen.getByText(/truncated at 12,000 characters/)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /raise to 24,000/i }));

    await waitFor(() => expect(buildState.mutate).toHaveBeenCalledTimes(2));
    expect(buildState.mutate.mock.calls[1][0].budget).toBe(24000);
  });

  it('offers no raise once the result was composed at the maximum', async () => {
    // Reading the edited box here would bring the control back at the ceiling,
    // where there is nothing left to raise to.
    const user = userEvent.setup();
    window.history.replaceState(null, '', '/?budget=100000');
    buildState.mutate = vi.fn((_vars, options?: { onSuccess?: () => void }) => {
      buildState.data = { ...SUCCESS, notes: ['output truncated at the character budget'] };
      options?.onSuccess?.();
    });
    render(<CodeContextPage />);

    await user.type(screen.getByLabelText('Task'), 'how does recall rank');
    await user.click(screen.getByRole('button', { name: /compose context/i }));
    await screen.findByText(/truncated at 100,000 characters/);

    const box = screen.getByLabelText('Source budget');
    await user.clear(box);
    await user.type(box, '500');

    expect(screen.queryByRole('button', { name: /raise to/i })).toBeNull();
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


  describe('the local evidence analyst', () => {
    const PACKET = {
      packet_id: 'pkt-7c1e',
      project: 'marm-systems',
      task: 'how does recall rank',
      symbols: [
        { handle: 'S1', qualified_name: 'marm.recall.rank_memories', name: 'rank_memories', file_path: 'marm/recall.py', start_line: 10, end_line: 11 },
      ],
      memories: [{ handle: 'M1', memory_id: 'm1', content: 'ranking is personalised PageRank' }],
    };
    const VERIFIED = {
      state: 'verified', score: 1, citation_coverage: 1, source_span_support: 1,
      graph_memory_consistency: 1, claims: 1, cited_claims: 1, failures: [], hard_failures: [], abstained: false,
    };

    function finished(over: Record<string, unknown>) {
      answerState.status = 'done';
      Object.assign(answerState as Record<string, unknown>, over);
    }

    it('labels a rejected answer as rejected, never grounded, and says why', () => {
      finished({
        grounding: 'rejected',
        hint: 'The answer cites persist_all, which the evidence packet does not contain.',
        verification: { ...VERIFIED, state: 'rejected', score: 0, hard_failures: ['reference not in packet: [persist_all]'] },
      });
      answerState.text = 'It calls [persist_all].';
      render(<CodeContextPage />);

      expect(screen.getByText('rejected answer')).toBeTruthy();
      expect(screen.queryByText('grounded answer')).toBeNull();
      expect(screen.getAllByText(/persist_all/).length).toBeGreaterThan(0);
      expect(screen.getByText('Rejected')).toBeTruthy();
    });

    it('shows how a finished answer was verified', () => {
      finished({ grounding: 'ok', verification: VERIFIED });
      answerState.text = 'It sorts [S1].';
      render(<CodeContextPage />);

      expect(screen.getByText('Verified')).toBeTruthy();
      expect(screen.getByText('citation coverage')).toBeTruthy();
    });

    it('links a cited handle while the answer is still arriving', () => {
      answerState.status = 'streaming';
      answerState.text = 'It sorts [S1] by score';
      (answerState as Record<string, unknown>).packet = PACKET;
      render(<CodeContextPage />);

      expect(screen.getByRole('button', { name: 'rank_memories' })).toBeTruthy();
    });

    it('links a cited handle once the server has resolved it', () => {
      finished({ grounding: 'ok' });
      answerState.text = 'It sorts [S1].';
      answerState.citations = [
        { handle: 'S1', kind: 'symbol', name: 'rank_memories', qualified_name: 'marm.recall.rank_memories', file_path: 'marm/recall.py', start_line: 10 },
      ];
      render(<CodeContextPage />);

      expect(screen.getByRole('button', { name: 'rank_memories' })).toBeTruthy();
    });

    it('lists a cited memory without pretending it is a file', () => {
      finished({ grounding: 'ok' });
      answerState.text = 'It ranks by PageRank [M1].';
      answerState.citations = [{ handle: 'M1', kind: 'memory', name: 'M1', memory_id: 'm1' }];
      (answerState as Record<string, unknown>).packet = PACKET;
      render(<CodeContextPage />);

      expect(screen.queryByText(/:undefined/)).toBeNull();
      // Linked inline and listed under the answer; never as a source file.
      expect(screen.getAllByRole('button', { name: /M1/ }).length).toBeGreaterThan(0);
      expect(screen.queryByText('Sources it used')).toBeNull();
    });

    it('shows which model answered, how long it took, and from which packet', () => {
      finished({
        grounding: 'ok',
        verification: VERIFIED,
        packet: PACKET,
        modelInfo: { id: 'local-model', endpoint_source: 'discovery', max_tokens: 900, elapsed_ms: 2240, stopped: null },
      });
      answerState.text = 'It sorts [S1].';
      render(<CodeContextPage />);

      expect(screen.getByText(/pkt-7c1e/)).toBeTruthy();
      expect(screen.getByText(/2\.2 s/)).toBeTruthy();
    });

    it('says when the answer was cut off by its time budget', () => {
      finished({
        grounding: 'unverified',
        modelInfo: { id: 'm', endpoint_source: null, max_tokens: 900, elapsed_ms: 90000, stopped: 'deadline' },
      });
      answerState.text = 'It sorts';
      render(<CodeContextPage />);

      expect(screen.getByText(/time budget/i)).toBeTruthy();
    });

    it('defaults the analyst to read-only and sends that mode with an answer', async () => {
      const user = userEvent.setup();
      render(<CodeContextPage />);

      const mode = screen.getByRole('combobox', { name: /analyst/i }) as HTMLSelectElement;
      expect(mode.value).toBe('read_only');
      expect(mode.disabled).toBe(true);

      await user.click(screen.getByRole('checkbox', { name: /answer it too/i }));
      expect(mode.disabled).toBe(false);
      await user.selectOptions(mode, 'manual_review');
      await user.type(screen.getByLabelText('Task'), 'how does recall rank');
      await user.click(screen.getByRole('button', { name: /compose context/i }));

      await waitFor(() => expect(answerState.start).toHaveBeenCalledTimes(1));
      expect(answerState.start.mock.calls[0][0]).toMatchObject({ analyst_mode: 'manual_review' });
    });

    it('points to the Distill queue when conclusions were staged', () => {
      finished({
        grounding: 'ok',
        analyst: { mode: 'manual_review', staged: ['a', 'b'], skipped: [], decisions: [] },
      });
      answerState.text = 'It sorts [S1].';
      render(<CodeContextPage />);

      const link = screen.getByRole('link', { name: /2 conclusions staged for review/i });
      expect(link.getAttribute('href')).toContain('/distill');
    });

    it('says what guardrails decided, applied or not', () => {
      finished({
        grounding: 'ok',
        analyst: {
          mode: 'guardrails',
          staged: ['a'],
          skipped: [],
          decisions: [{ proposal_id: 'a', applied: false, decision: { apply: false, checks: {}, reason: 'review required: automatic apply is off (MARM_ANALYST_AUTO_APPLY is not 1)' } }],
        },
      });
      answerState.text = 'It sorts [S1].';
      render(<CodeContextPage />);

      expect(screen.getByText(/automatic apply is off/)).toBeTruthy();
    });
  });
});
