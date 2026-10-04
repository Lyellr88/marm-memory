import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CodeContextPage } from './CodeContext';
import { answerState, buildState, resetCodeContextTest, SUCCESS, symbol } from './CodeContext.testkit';

// The graph pane renders a canvas-backed force simulation; jsdom has no canvas,
// and what this page owns is the adapter, not the renderer.
vi.mock('react-force-graph-2d', () => ({ default: () => null }));
vi.mock('@/hooks/use-marm-queries', async () => (await import('./CodeContext.testkit')).queryMocks);

afterEach(resetCodeContextTest);

describe('CodeContextPage', () => {
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
});
