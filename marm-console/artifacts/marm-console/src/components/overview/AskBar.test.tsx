import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AskBar } from './AskBar';

const navigate = vi.hoisted(() => vi.fn());
const projectsState = vi.hoisted(() => ({
  data: [{ name: 'p-one', display_name: 'one' }] as unknown[] | undefined,
}));
vi.mock('wouter', () => ({ useLocation: () => ['/', navigate] }));
vi.mock('@/hooks/use-marm-queries', () => ({ useProjects: () => projectsState }));

afterEach(() => {
  cleanup();
  navigate.mockClear();
  projectsState.data = [{ name: 'p-one', display_name: 'one' }];
});

describe('AskBar', () => {
  it('runs the composition immediately, because the reader typed the question', async () => {
    // The opposite of ComposeAction: there is nothing to review here.
    render(<AskBar />);
    await waitFor(() => expect(screen.getByLabelText('Question')).toBeTruthy());
    await userEvent.type(screen.getByLabelText('Question'), 'how does recall rank');
    await userEvent.click(screen.getByRole('button', { name: /compose/i }));

    const params = new URLSearchParams((navigate.mock.calls[0][0] as string).split('?')[1]);
    expect(params.get('task')).toBe('how does recall rank');
    expect(params.get('run')).toBe('1');
    expect(params.get('project')).toBe('p-one');
  });

  it('will not compose an empty question', async () => {
    render(<AskBar />);
    expect(screen.getByRole('button', { name: /compose/i }).hasAttribute('disabled')).toBe(true);
    expect(navigate).not.toHaveBeenCalled();
  });

  it('stays off the page entirely when nothing is indexed', () => {
    // Overview is dense. A control that cannot do anything should not occupy
    // a row of it.
    projectsState.data = [];
    const { container } = render(<AskBar />);
    expect(container.firstChild).toBeNull();
  });

  it('submits on Enter', async () => {
    render(<AskBar />);
    await waitFor(() => expect(screen.getByLabelText('Question')).toBeTruthy());
    await userEvent.type(screen.getByLabelText('Question'), 'a question{Enter}');
    expect(navigate).toHaveBeenCalledTimes(1);
  });
});
