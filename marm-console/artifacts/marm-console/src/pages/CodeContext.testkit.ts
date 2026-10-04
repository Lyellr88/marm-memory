import { cleanup, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import type { CodeContextResult, CodeContextSymbol } from '@/lib/marm-types';

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

export const buildState = {
  mutate: vi.fn(),
  data: undefined as CodeContextResult | undefined,
  error: null as unknown,
  isPending: false,
};

const DEFAULT_PROJECTS = [
  {
    name: 'C-work-marm-systems',
    display_name: 'marm-systems',
    root_path: 'C:/work/marm-systems',
    nodes: 4500,
    edges: 23913,
  },
];

export const projectState = {
  status: 'ready' as string,
  // Mutable so a test can vary the LIST, not only one project's status.
  list: null as Array<Record<string, unknown>> | null,
};

export const answerState = {
  status: 'idle' as 'idle' | 'streaming' | 'done' | 'error',
  text: '',
  citations: [] as unknown[],
  model: undefined as string | undefined,
  start: vi.fn(),
  reset: vi.fn(),
};

export const queryMocks = {
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
};

export function symbol(over: Partial<CodeContextSymbol> = {}): CodeContextSymbol {
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

export const SUCCESS: CodeContextResult = {
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

export function resetCodeContextTest() {
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
  for (const key of ['grounding', 'unresolved', 'hint', 'packet', 'verification', 'modelInfo', 'items', 'disagreements', 'analyst', 'message', 'context']) {
    delete (answerState as Record<string, unknown>)[key];
  }
  projectState.status = 'ready';
  window.history.replaceState(null, '', '/');
}

/** Open the Symbols pane.
 *
 *  `Answer` is the landing tab now — someone who typed a question wants the
 *  answer first and the evidence under it — so assertions about symbol
 *  rendering have to switch panes. Radix does not mount an inactive one.
 */
export async function openSymbols() {
  await userEvent.click(screen.getByRole('tab', { name: /ranked symbols/i }));
}
