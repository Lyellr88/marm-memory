import { useCallback } from 'react';
import type { Terminal } from '@xterm/xterm';

export function useClipboard() {
  const copySelection = useCallback(async (term: Terminal | null, clearAfterCopy = true): Promise<boolean> => {
    const selection = term?.getSelection();
    if (!term || !selection) return false;

    try {
      await navigator.clipboard.writeText(selection);
      if (clearAfterCopy) term.clearSelection();
      return true;
    } catch {
      return false;
    }
  }, []);

  const pasteClipboard = useCallback(async (onData: (data: string) => void): Promise<void> => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        const normalized = text.replace(/(?:\r\n|[\r\n])+$/g, '');
        if (normalized) onData(normalized);
      }
    } catch {
      // Ignore clipboard failures and keep terminal usable
    }
  }, []);

  return { copySelection, pasteClipboard };
}
