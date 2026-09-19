import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ComposeAction, taskForSymbol } from './ComposeAction';

const navigate = vi.hoisted(() => vi.fn());
vi.mock('wouter', () => ({ useLocation: () => ['/explorer', navigate] }));

afterEach(() => {
  cleanup();
  navigate.mockClear();
});

describe('taskForSymbol', () => {
  it('asks a behaviour question rather than passing the bare name', () => {
    // marm_code_context seeds its ranking from the task's words, and a bare
    // symbol name is the input it is documented as worst at.
    expect(taskForSymbol('marm.recall.rank_memories')).toBe('How does rank_memories work?');
  });

  it('drops the qualified path, which is noise to a word-seeded ranker', () => {
    expect(taskForSymbol('crate::nes_ppu::Ppu::cpu_write_register')).toContain(
      'cpu_write_register',
    );
    expect(taskForSymbol('crate::nes_ppu::Ppu::cpu_write_register')).not.toContain('crate');
  });

  it('survives a name with no qualifier at all', () => {
    expect(taskForSymbol('build')).toBe('How does build work?');
  });
});

describe('ComposeAction', () => {
  it('prefills the question but does NOT run it', async () => {
    // The objection to prefilling was that it puts words in the reader's
    // mouth. That is only true if the words are acted on before anyone reads
    // them, so the phrasing lands in the box and the reader presses Compose.
    render(<ComposeAction qualifiedName="marm.recall.rank_memories" project="p1" />);
    await userEvent.click(screen.getByRole('button'));

    expect(navigate).toHaveBeenCalledTimes(1);
    const target = navigate.mock.calls[0][0] as string;
    const params = new URLSearchParams(target.split('?')[1]);
    expect(target.startsWith('/code-context')).toBe(true);
    expect(params.get('task')).toBe('How does rank_memories work?');
    expect(params.get('project')).toBe('p1');
    expect(params.get('run')).toBeNull();
  });

  it('renders nothing without a symbol to ask about', () => {
    const { container } = render(<ComposeAction qualifiedName="" project="p1" />);
    expect(container.firstChild).toBeNull();
  });

  it('omits the project rather than sending an empty one', async () => {
    render(<ComposeAction qualifiedName="build" project={null} />);
    await userEvent.click(screen.getByRole('button'));
    const params = new URLSearchParams((navigate.mock.calls[0][0] as string).split('?')[1]);
    expect(params.has('project')).toBe(false);
  });
});
