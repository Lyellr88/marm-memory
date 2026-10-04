import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CodeContextPage } from './CodeContext';
import { buildState, openSymbols, resetCodeContextTest, SUCCESS, symbol } from './CodeContext.testkit';

// The graph pane renders a canvas-backed force simulation; jsdom has no canvas,
// and what this page owns is the adapter, not the renderer.
vi.mock('react-force-graph-2d', () => ({ default: () => null }));
vi.mock('@/hooks/use-marm-queries', async () => (await import('./CodeContext.testkit')).queryMocks);

afterEach(resetCodeContextTest);

describe('CodeContextPage', () => {
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
