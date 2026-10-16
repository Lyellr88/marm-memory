import { useCallback, useEffect, useRef, useState } from 'react';
import { useMarmConfig } from './marm-query-core';
import type { RuntimeLogTail } from '@/lib/marm-types';

export function boundedLogLines(lines: string[]) {
  const result: string[] = [];
  let bytes = 0;
  const encoder = new TextEncoder();
  for (let i = lines.length - 1; i >= 0 && result.length < 2000; i--) {
    const line = lines[i].slice(0, 4000);
    const size = encoder.encode(line + '\n').length;
    if (bytes + size > 256 * 1024) break;
    result.push(line);
    bytes += size;
  }
  return result.reverse();
}

export function useRuntimeLogTail(enabled: boolean, source: 'runtime' | 'docker' = 'runtime') {
  const { baseUrl, client } = useMarmConfig();
  const [lines, setLines] = useState<string[]>([]);
  const [auto, setAuto] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [exists, setExists] = useState<boolean | null>(null);
  const [rotated, setRotated] = useState(false);
  const cursor = useRef<string | null>(null);
  const generation = useRef(0);
  const pending = useRef(false);
  const skipSnapshot = useRef(false);
  const refreshQueued = useRef(false);
  const latestRefresh = useRef<(() => Promise<void>) | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled || pending.current) return;
    const version = generation.current;
    pending.current = true;
    setLoading(true);
    try {
      const response = source === 'runtime' ? await client.getRuntimeLogTail(cursor.current) : await client.getDockerLogs(200);
      if (version !== generation.current) return;
      setError(null);
      if ('cursor' in response) {
        const tail = response as RuntimeLogTail;
        cursor.current = tail.cursor;
        setExists(tail.exists);
        setRotated((was) => was || tail.rotated);
        if (skipSnapshot.current) {
          skipSnapshot.current = false;
        } else {
          setLines((previous) => boundedLogLines(tail.rotated || !tail.exists ? tail.lines : [...previous, ...tail.lines]));
        }
      } else {
        setExists(true);
        setLines(boundedLogLines(response.lines));
      }
    } catch (err) {
      if (version === generation.current) setError(err);
    } finally {
      pending.current = false;
      setLoading(false);
      if (refreshQueued.current) {
        refreshQueued.current = false;
        void latestRefresh.current?.();
      }
    }
  }, [client, source, enabled]);
  latestRefresh.current = refresh;

  useEffect(() => {
    generation.current++;
    cursor.current = null;
    skipSnapshot.current = false;
    refreshQueued.current = pending.current;
    setLines([]);
    setExists(null);
    setRotated(false);
    setError(null);
    return () => { generation.current++; refreshQueued.current = false; };
  }, [source, baseUrl, enabled]);

  useEffect(() => { if (enabled && document.visibilityState === 'visible') void refresh(); }, [enabled, refresh]);

  useEffect(() => {
    const poll = () => { if (document.visibilityState === 'visible') void refresh(); };
    const timer = enabled && auto ? window.setInterval(poll, 2000) : null;
    const onVisible = () => { if (auto) poll(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      if (timer !== null) window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [enabled, auto, refresh]);

  function clear() {
    generation.current++;
    setLines([]);
    setRotated(false);
    if (source === 'runtime') {
      cursor.current = null;
      skipSnapshot.current = true;
      if (pending.current) refreshQueued.current = true;
      else void refresh();
    }
  }
  return { lines, auto, setAuto, loading, error, exists, rotated, refresh, clear };
}
