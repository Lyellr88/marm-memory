import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { LocalLlmStatus } from '@/lib/marm-types';

const mutate = vi.fn();

vi.mock('@/hooks/use-marm-queries', () => ({
  useLlmModels: () => ({ data: undefined }),
  useBrowseLlmModels: () => ({ data: undefined }),
  useUpdateLlmRoots: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateLlmSettings: () => ({ mutate, isPending: false, data: undefined }),
  useLlmServers: () => ({ data: undefined, isFetching: false, refetch: vi.fn() }),
}));

const { AutoApplyToggle, LocalModelPanels } = await import('./LocalModelPanel');

function llm(
  enabled: boolean,
  source: 'override' | 'environment' | 'unknown',
): LocalLlmStatus {
  return {
    configured: true,
    enabled: true,
    endpoint: 'http://127.0.0.1:1234',
    available: true,
    model: 'm',
    model_in_use: 'm',
    preferred_model: null,
    loopback_enforced: true,
    runtime: 'LM Studio',
    runtime_version: null,
    can_switch: true,
    model_path: null,
    context_length: 32768,
    served: [],
    switch_blocked_reason: null,
    analyst_auto_apply: { enabled, source },
  };
}

describe('AutoApplyToggle', () => {
  beforeEach(() => {
    cleanup();
    mutate.mockReset();
  });

  it('saves the switch the operator turns on', async () => {
    render(<AutoApplyToggle llm={llm(false, 'environment')} />);
    const box = screen.getByRole('checkbox', { name: /apply provable results/i });
    expect((box as HTMLInputElement).checked).toBe(false);
    await userEvent.setup().click(box);
    expect(mutate).toHaveBeenCalledWith({ auto_apply: true });
  });

  it('returns to the environment only when a saved choice exists', async () => {
    const { rerender } = render(<AutoApplyToggle llm={llm(false, 'environment')} />);
    expect(screen.queryByRole('button', { name: /use environment/i })).toBeNull();
    rerender(<AutoApplyToggle llm={llm(true, 'override')} />);
    await userEvent.setup().click(screen.getByRole('button', { name: /use environment/i }));
    expect(mutate).toHaveBeenCalledWith({ auto_apply: '' });
  });

  it('says plainly when the saved switch could not be read', () => {
    render(<AutoApplyToggle llm={llm(false, 'unknown')} />);
    expect(screen.getByText(/could not be read/i)).toBeTruthy();
  });

  it('renders nothing for a server without the switch', () => {
    const old = { ...llm(false, 'environment'), analyst_auto_apply: undefined };
    const { container } = render(<AutoApplyToggle llm={old} />);
    expect(container.textContent).toBe('');
  });

  it('is offered with no model configured, since verbatim distill needs none', () => {
    render(<LocalModelPanels llm={{ ...llm(false, 'environment'), configured: false }} />);
    expect(screen.getByRole('checkbox', { name: /apply provable results/i })).toBeTruthy();
  });
});
