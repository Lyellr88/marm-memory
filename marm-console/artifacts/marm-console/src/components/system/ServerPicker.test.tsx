import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import type { LlmServersResponse, LocalLlmStatus } from '@/lib/marm-types';

const state: { servers: LlmServersResponse } = {
  servers: {
    servers: [],
    configured: 'http://127.0.0.1:18080',
    configured_reachable: false,
    scanned_ports: [1234, 11434, 8000, 8080, 18080],
    scan_seconds: 0.006,
  },
};

vi.mock('@/hooks/use-marm-queries', () => ({
  useLlmServers: () => ({ data: state.servers, isFetching: false, refetch: vi.fn() }),
  useUpdateLlmSettings: () => ({ mutate: vi.fn(), isPending: false, data: undefined }),
}));

const { ServerPicker } = await import('./ServerPicker');

function llm(over: Partial<LocalLlmStatus> = {}): LocalLlmStatus {
  return {
    configured: true,
    enabled: true,
    endpoint: 'http://127.0.0.1:18080',
    available: false,
    model: null,
    model_in_use: null,
    preferred_model: null,
    loopback_enforced: true,
    runtime: null,
    runtime_version: null,
    can_switch: false,
    model_path: null,
    context_length: null,
    served: [],
    switch_blocked_reason: null,
    ...over,
  };
}

describe('ServerPicker', () => {
  beforeEach(cleanup);

  it('says the configured endpoint is dead, which is the useful part', () => {
    state.servers = { ...state.servers, servers: [], configured_reachable: false };
    render(<ServerPicker llm={llm()} />);
    expect(screen.getByText(/Nothing is answering at/i)).toBeTruthy();
    expect(screen.getByText(/http:\/\/127\.0\.0\.1:18080/)).toBeTruthy();
    // Nothing else found, so it must not imply there is something to pick.
    expect(screen.getByText(/Start a local model server/i)).toBeTruthy();
  });

  it('points at a live server when the configured one is dead', () => {
    state.servers = {
      ...state.servers,
      configured_reachable: false,
      servers: [
        {
          url: 'http://127.0.0.1:1234',
          port: 1234,
          expected: 'LM Studio',
          runtime: 'LM Studio',
          version: null,
          can_switch: true,
          model_count: 7,
          models: ['gpt-oss-20b', 'qwen3-14b'],
          model_path: null,
          context_length: 131072,
        },
      ],
    };
    render(<ServerPicker llm={llm()} />);
    expect(screen.getByText(/another local server is running/i)).toBeTruthy();
    expect(screen.getByText('LM Studio')).toBeTruthy();
    expect(screen.getByText(/7 models/)).toBeTruthy();
  });

  it('reports what answered, not what the port usually belongs to', () => {
    // Anyone may run llama.cpp on 1234; saying "LM Studio" because of the port
    // number would be asserting something nothing checked.
    state.servers = {
      ...state.servers,
      configured_reachable: true,
      servers: [
        {
          url: 'http://127.0.0.1:1234',
          port: 1234,
          expected: 'LM Studio',
          runtime: 'llama.cpp',
          version: null,
          can_switch: false,
          model_count: 1,
          models: ['qwen3.6-27b'],
          model_path: '/models/q.gguf',
          context_length: 65536,
        },
      ],
    };
    render(<ServerPicker llm={llm({ endpoint: 'http://127.0.0.1:1234' })} />);
    expect(screen.getByText('llama.cpp')).toBeTruthy();
    expect(screen.getByText(/port usually LM Studio/i)).toBeTruthy();
    expect(screen.getByText('one model')).toBeTruthy();
  });

  it('states that nothing here reaches the network', () => {
    render(<ServerPicker llm={llm()} />);
    expect(screen.getByText(/nothing here reaches the network/i)).toBeTruthy();
  });
});
