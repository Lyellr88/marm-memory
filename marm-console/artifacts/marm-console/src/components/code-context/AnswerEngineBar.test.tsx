import { beforeEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { AnswerEngineBar } from './AnswerEngineBar';
import type { HardwareStatus, LocalLlmStatus } from '@/lib/marm-types';

const GPU: HardwareStatus = {
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
};

function llm(over: Partial<LocalLlmStatus> = {}): LocalLlmStatus {
  return {
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
    ...over,
  };
}

describe('AnswerEngineBar', () => {
  // This project does not auto-clean between tests, so without this every
  // render accumulates and a later query matches an earlier test's DOM.
  beforeEach(cleanup);

  it('names the model and the GPU that will answer', () => {
    render(<AnswerEngineBar llm={llm()} hardware={GPU} />);
    expect(screen.getByText('qwen3.6-27b-mtp')).toBeTruthy();
    expect(screen.getByText(/NVIDIA GeForce RTX 3090/)).toBeTruthy();
    // Free VRAM is the number that predicts whether the next model loads.
    expect(screen.getByText(/3\.8 GB free of 24\.0 GB/)).toBeTruthy();
  });

  it('still names the model while generation is switched off', () => {
    // Otherwise a deliberate setting reads as a broken page, and the reader is
    // asked to re-enable something the screen refuses to describe.
    render(<AnswerEngineBar llm={llm({ enabled: false, model_in_use: null, available: false })} hardware={GPU} />);
    expect(screen.getByText(/switched off/i)).toBeTruthy();
    expect(screen.getByText(/only the answer needs a model/i)).toBeTruthy();
  });

  it('says the rest of the page is unaffected when nothing answers', () => {
    render(<AnswerEngineBar llm={llm({ available: false, model_in_use: null })} hardware={GPU} />);
    expect(screen.getByText(/No model answered/i)).toBeTruthy();
    expect(screen.getByText(/Ranking, source and memory are unaffected/i)).toBeTruthy();
  });

  it('renders nothing when no endpoint is configured at all', () => {
    // There is no model, no setting and nothing to fix here -- an empty bar
    // would be a permanent row of nothing on a page that has none elsewhere.
    const { container } = render(<AnswerEngineBar llm={llm({ configured: false })} hardware={GPU} />);
    expect(container.innerHTML).toBe('');
  });

  it('reports unified memory as unified rather than as free VRAM', () => {
    // On Apple Silicon there is no dedicated VRAM, and rendering the machine's
    // whole RAM as though there were tells the reader they have 64 GB to spend.
    render(
      <AnswerEngineBar
        llm={llm()}
        hardware={{
          detected: true,
          platform: 'Darwin',
          gpus: [
            {
              index: 0,
              vendor: 'Apple',
              name: 'Apple M3 Max',
              memory_total_mb: 65536,
              memory_used_mb: null,
              memory_free_mb: null,
              utilisation_percent: null,
              driver: 'Metal',
              unified: true,
            },
          ],
        }}
      />,
    );
    expect(screen.getByText(/64\.0 GB unified/)).toBeTruthy();
    expect(screen.queryByText(/free of/)).toBeNull();
  });

  it('links to the System controls that change the model', () => {
    render(<AnswerEngineBar llm={llm()} hardware={GPU} />);
    const link = screen.getByRole('link', { name: /Model settings in System/i });
    expect(link.getAttribute('href')).toBe('/system?tab=controls');
  });
});
