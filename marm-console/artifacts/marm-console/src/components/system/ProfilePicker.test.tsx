import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { AnswerProfile, LocalLlmStatus } from '@/lib/marm-types';

const mutate = vi.fn();

vi.mock('@/hooks/use-marm-queries', () => ({
  useLlmModels: () => ({ data: undefined }),
  useBrowseLlmModels: () => ({ data: undefined }),
  useUpdateLlmRoots: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateLlmSettings: () => ({ mutate, isPending: false, data: undefined }),
}));

const { ProfilePicker } = await import('./LocalModelPanel');

const SMALL: AnswerProfile = {
  name: 'small',
  context_chars: 6000,
  max_symbols: 12,
  max_memories: 4,
  output_tokens: 1024,
  reasoning_tokens: 0,
  max_tokens: 1024,
  time_s: 60,
  structured: true,
  batch: false,
};
const LARGE: AnswerProfile = {
  ...SMALL,
  name: 'large',
  output_tokens: 4096,
  reasoning_tokens: 8192,
  max_tokens: 12288,
  batch: true,
};

function llm(source: 'runtime' | 'environment' | 'default', active = SMALL): LocalLlmStatus {
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
    analyst_profile: {
      name: active.name,
      source,
      profiles: { general: { ...SMALL, name: 'general' }, small: SMALL, large: LARGE },
      active,
    },
  };
}

describe('ProfilePicker', () => {
  beforeEach(() => {
    cleanup();
    mutate.mockReset();
  });

  it('shows the limits the active profile holds the model to', () => {
    render(<ProfilePicker llm={llm('environment')} />);
    expect(screen.getByText(/reads ≤ 6,000 chars/)).toBeTruthy();
    expect(screen.getByText(/≤ 1,024 tokens per call/)).toBeTruthy();
    expect(screen.getByText(/environment/)).toBeTruthy();
  });

  it('splits a reasoning allowance out of the cap', () => {
    render(<ProfilePicker llm={llm('runtime', LARGE)} />);
    expect(screen.getByText(/4,096 answer \+ 8,192 reasoning/)).toBeTruthy();
  });

  it('returns to the environment only when a saved choice exists', async () => {
    const { rerender } = render(<ProfilePicker llm={llm('environment')} />);
    expect(screen.queryByRole('button', { name: /use environment/i })).toBeNull();
    rerender(<ProfilePicker llm={llm('runtime')} />);
    await userEvent.setup().click(screen.getByRole('button', { name: /use environment/i }));
    expect(mutate).toHaveBeenCalledWith({ profile: '' });
  });

  it('renders nothing for a server that predates profiles', () => {
    const old = { ...llm('default'), analyst_profile: undefined };
    const { container } = render(<ProfilePicker llm={old} />);
    expect(container.textContent).toBe('');
  });
});
