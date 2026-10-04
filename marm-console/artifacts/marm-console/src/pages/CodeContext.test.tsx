import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CodeContextPage } from './CodeContext';
import { answerState, buildState, projectState, resetCodeContextTest, SUCCESS } from './CodeContext.testkit';

// The graph pane renders a canvas-backed force simulation; jsdom has no canvas,
// and what this page owns is the adapter, not the renderer.
vi.mock('react-force-graph-2d', () => ({ default: () => null }));
vi.mock('@/hooks/use-marm-queries', async () => (await import('./CodeContext.testkit')).queryMocks);

afterEach(resetCodeContextTest);

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
});
