import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DistillPage } from './Distill';
import type { DistillProposal, DistillResult } from '@/lib/marm-types';

const proposeState = vi.hoisted(() => ({
  mutate: vi.fn(),
  data: undefined as DistillResult | undefined,
  error: null as unknown,
  isPending: false,
}));
const applyState = vi.hoisted(() => ({
  mutate: vi.fn(),
  data: undefined as DistillResult | undefined,
  error: null as unknown,
  isSuccess: false,
}));
const discardState = vi.hoisted(() => ({
  mutate: vi.fn(),
  data: undefined as DistillResult | undefined,
  error: null as unknown,
  isSuccess: false,
}));
const pendingState = vi.hoisted(() => ({
  data: undefined as DistillResult | undefined,
  isLoading: false,
}));

vi.mock('@/hooks/use-marm-queries', () => ({
  useDistillPropose: () => proposeState,
  useDistillApply: () => applyState,
  useDistillDiscard: () => discardState,
  useDistillPending: () => pendingState,
  useSessions: () => ({ data: [{ name: 'review', log_count: 3 }], isLoading: false }),
  useLogs: () => logsState,
}));

const logsState = vi.hoisted(() => ({
  data: { items: [] as Array<Record<string, unknown>>, total: 0, limit: 0, offset: 0 },
  isLoading: false,
}));

function proposal(over: Partial<DistillProposal> = {}): DistillProposal {
  return {
    id: 'p-1',
    content: 'The code-graph daemon reparents to systemd and survives stopping the marm service.',
    score: 1.0,
    reasons: ['names its subject', 'states rather than speculates'],
    verdict: 'new',
    cosine: 0.41,
    staged: true,
    ...over,
  };
}

/** Mirrors react-query: invoke the caller's callbacks so the component can
 *  clear its in-flight state. Without this the card stays disabled after the
 *  first click -- which is the component behaving correctly, not a bug. */
function settlingMock() {
  return vi.fn((_input: unknown, opts?: { onSuccess?: () => void; onSettled?: () => void }) => {
    opts?.onSuccess?.();
    opts?.onSettled?.();
  });
}

beforeEach(() => {
  proposeState.mutate = settlingMock();
  proposeState.data = undefined;
  proposeState.error = null;
  proposeState.isPending = false;
  applyState.mutate = settlingMock();
  applyState.data = undefined;
  applyState.error = null;
  applyState.isSuccess = false;
  discardState.mutate = settlingMock();
  discardState.error = null;
  discardState.isSuccess = false;
  pendingState.data = undefined;
  pendingState.isLoading = false;
  logsState.data = { items: [], total: 0, limit: 0, offset: 0 };
  logsState.isLoading = false;
});

afterEach(cleanup);

describe('DistillPage', () => {
  it('cannot submit an empty paste', async () => {
    render(<DistillPage />);
    await userEvent.click(screen.getByRole('button', { name: /paste text/i }));
    const button = screen.getByRole('button', { name: /^distill$/i });
    // The session defaults to a real one, so text is the only thing missing.
    expect(button.hasAttribute('disabled')).toBe(true);

    await userEvent.type(screen.getByLabelText('Conversation'), 'some text');
    expect(button.hasAttribute('disabled')).toBe(false);
  });

  it('cannot submit a session that has no logs', () => {
    // Nothing to distil is not an error, but it is not a submit either.
    render(<DistillPage />);
    expect(
      screen.getByRole('button', { name: /^distill$/i }).hasAttribute('disabled'),
    ).toBe(true);
    expect(screen.getByText(/has no log entries/i)).toBeTruthy();
  });

  it('offers a session\u2019s own logs instead of asking for a paste', () => {
    // The transcript is already in MARM. Asking a user to copy it back out of
    // the tool that stored it is work the page can do itself.
    render(<DistillPage />);
    expect(screen.getByRole('button', { name: /from its logs/i })).toBeTruthy();
    expect(screen.queryByLabelText('Conversation')).toBeNull();
  });

  it('distils a session\u2019s log entries without a paste', async () => {
    logsState.data = {
      items: [
        { topic: 'cutover', summary: null, entry: 'The daemon reparents to systemd.' },
      ],
      total: 1,
      limit: 200,
      offset: 0,
    };
    render(<DistillPage />);
    // The session defaults to a real one, so there is nothing to pick. Radix
    // Select does not open reliably under jsdom anyway, which is why the
    // Explorer tests assert on the closed trigger too.
    expect(screen.getByRole('combobox', { name: 'Session' }).textContent).toContain('review');
    await userEvent.click(screen.getByRole('button', { name: /^distill$/i }));

    expect(proposeState.mutate).toHaveBeenCalledTimes(1);
    const [payload] = proposeState.mutate.mock.calls[0];
    expect(payload.session_name).toBe('review');
    expect(payload.text).toContain('reparents to systemd');
    expect(payload.project).toBeNull();
  });

  it('selects sentences unless the operator asks for generation', async () => {
    // A running model must not silently change what a distillation produces.
    logsState.data = {
      items: [{ topic: 't', summary: null, entry: 'The daemon reparents to systemd.' }],
      total: 1,
      limit: 200,
      offset: 0,
    };
    render(<DistillPage />);
    const box = screen.getByRole('checkbox', { name: /write facts with the local model/i });
    expect((box as HTMLInputElement).checked).toBe(false);

    await userEvent.click(screen.getByRole('button', { name: /^distill$/i }));
    expect(proposeState.mutate.mock.calls[0][0].use_llm).toBe(false);

    await userEvent.click(box);
    await userEvent.click(screen.getByRole('button', { name: /^distill$/i }));
    expect(proposeState.mutate.mock.calls[1][0].use_llm).toBe(true);
  });

  it('does not report the model as unreachable when generation was not asked for', async () => {
    logsState.data = {
      items: [{ topic: 't', summary: null, entry: 'The daemon reparents to systemd.' }],
      total: 1,
      limit: 200,
      offset: 0,
    };
    render(<DistillPage />);
    await userEvent.click(screen.getByRole('button', { name: /^distill$/i }));
    expect(proposeState.mutate).toHaveBeenCalledTimes(1);
    proposeState.data = { status: 'success', proposals: [], extracted: 0, staged: 0, mode: 'selected' };
    await userEvent.click(screen.getByRole('checkbox', { name: /write facts with the local model/i }));

    expect(screen.queryByText(/no local model/i)).toBeNull();
    expect(screen.getByText(/generation was not requested/i)).toBeTruthy();
  });

  it('reports the model as unreachable when generation was asked for and did not happen', async () => {
    logsState.data = {
      items: [{ topic: 't', summary: null, entry: 'The daemon reparents to systemd.' }],
      total: 1,
      limit: 200,
      offset: 0,
    };
    render(<DistillPage />);
    await userEvent.click(screen.getByRole('checkbox', { name: /write facts with the local model/i }));
    await userEvent.click(screen.getByRole('button', { name: /^distill$/i }));
    expect(proposeState.mutate).toHaveBeenCalledTimes(1);
    proposeState.data = { status: 'success', proposals: [], extracted: 0, staged: 0, mode: 'selected' };
    await userEvent.click(screen.getByRole('checkbox', { name: /write facts with the local model/i }));

    expect(screen.getAllByText(/no local model/i).length).toBeGreaterThan(0);
  });

  it('shows the review queue on arrival, without needing a distillation first', () => {
    pendingState.data = { status: 'success', pending: [proposal()], count: 1 };
    render(<DistillPage />);

    // The queue is the landing tab precisely so an agent's own staged
    // proposals are visible without pasting anything.
    expect(screen.getByText(/reparents to systemd/)).toBeTruthy();
  });

  it('applies and discards by id', async () => {
    pendingState.data = { status: 'success', pending: [proposal()], count: 1 };
    render(<DistillPage />);

    await userEvent.click(screen.getByRole('button', { name: /keep it/i }));
    expect(applyState.mutate).toHaveBeenCalledWith('p-1', expect.anything());

    await userEvent.click(screen.getByRole('button', { name: /discard/i }));
    expect(discardState.mutate).toHaveBeenCalledWith('p-1', expect.anything());
  });

  it('warns that a discard is permanent', () => {
    pendingState.data = { status: 'success', pending: [proposal()], count: 1 };
    render(<DistillPage />);
    expect(screen.getByText(/will not be proposed again/i)).toBeTruthy();
  });

  it('offers no decision on a proposal that was never staged', async () => {
    // A duplicate carries no id, so apply/discard would be actions that cannot
    // run. It renders as a record instead.
    proposeState.data = {
      status: 'success',
      extracted: 1,
      staged: 0,
      proposals: [
        proposal({
          id: undefined,
          verdict: 'duplicate',
          cosine: 0.97,
          staged: false,
          neighbour: 'the stored version',
          note: 'already recorded; not staged',
        }),
      ],
    };
    render(<DistillPage />);

    // Radix does not mount an inactive panel, and setting `data` directly does
    // not run the mutation's onSuccess that would switch tabs.
    const runTab = screen.getByRole('tab', { name: /last run/i });
    await userEvent.click(runTab);
    const panel = await waitFor(() => {
      const found = document.getElementById(runTab.getAttribute('aria-controls') ?? '');
      if (!found) throw new Error('the Last run panel did not mount');
      return found;
    });
    const scope = within(panel);
    expect(scope.queryByRole('button', { name: /keep it/i })).toBeNull();
    expect(scope.getByText('already recorded; not staged')).toBeTruthy();
  });

  it('shows a near match beside the memory it resembles', () => {
    pendingState.data = {
      status: 'success',
      count: 1,
      pending: [
        proposal({
          verdict: 'near',
          cosine: 0.87,
          neighbour: 'The daemon survives a stop of the marm service.',
        }),
      ],
    };
    render(<DistillPage />);

    expect(screen.getByText('Closest existing memory')).toBeTruthy();
    expect(screen.getByText('The daemon survives a stop of the marm service.')).toBeTruthy();
    expect(screen.getByText(/0\.870/)).toBeTruthy();
  });

  it('shows the reasons a proposal scored, not just the total', () => {
    pendingState.data = { status: 'success', pending: [proposal()], count: 1 };
    render(<DistillPage />);

    expect(screen.getByText('names its subject')).toBeTruthy();
    expect(screen.getByText('states rather than speculates')).toBeTruthy();
    expect(screen.getByText('+1.00')).toBeTruthy();
  });

  it('treats "nothing durable" as a result, not an error', async () => {
    proposeState.data = {
      status: 'success',
      extracted: 0,
      staged: 0,
      proposals: [],
      note: 'Nothing in this text reads like a durable fact.',
    };
    render(<DistillPage />);

    await userEvent.click(screen.getByRole('tab', { name: /last run/i }));
    await waitFor(() =>
      expect(screen.getByText(/nothing in that text read as a durable fact/i)).toBeTruthy(),
    );
    expect(screen.getByText(/Nothing in this text reads like a durable fact\./)).toBeTruthy();
  });

  it('has an empty queue state that names where proposals come from', () => {
    pendingState.data = { status: 'success', pending: [], count: 0 };
    render(<DistillPage />);
    expect(screen.getByText('Nothing is waiting for review')).toBeTruthy();
    // Scoped: the page header names the tool too, so an unscoped query is
    // ambiguous and would pass on the wrong element.
    expect(screen.getByText(/when an agent runs marm_distill/)).toBeTruthy();
  });

  it('surfaces a failed apply as an error', () => {
    applyState.error = new Error('boom');
    pendingState.data = { status: 'success', pending: [proposal()], count: 1 };
    render(<DistillPage />);
    expect(screen.getByText(/the distil request failed/i)).toBeTruthy();
  });

  it('confirms a successful apply with the memory it wrote', () => {
    applyState.isSuccess = true;
    applyState.data = { status: 'success', memory_id: 'mem-42' };
    render(<DistillPage />);
    expect(screen.getByText(/written to memory as mem-42/i)).toBeTruthy();
  });
});
