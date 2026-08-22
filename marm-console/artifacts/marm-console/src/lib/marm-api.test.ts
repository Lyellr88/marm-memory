import { afterEach, describe, expect, it, vi } from 'vitest';
import { createMarmClient } from './marm-api';

describe('MARM API client timeouts', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('keeps the timeout active while a successful response body is stalled', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => {
      const signal = init?.signal;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => new Promise((_, reject) => {
          signal?.addEventListener('abort', () => {
            reject(new DOMException('The operation was aborted.', 'AbortError'));
          });
        }),
      } as Response);
    }));
    const client = createMarmClient({ baseUrl: 'http://127.0.0.1:8002', apiKey: null });
    const result = client.getOverview();
    const assertion = expect(result).rejects.toMatchObject({
      status: 0,
      message: 'Request to MARM server timed out after 30s',
    });

    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(30_000);

    await assertion;
  });
});
