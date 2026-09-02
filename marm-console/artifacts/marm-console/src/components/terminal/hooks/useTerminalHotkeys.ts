import { useRef, useCallback, useEffect } from 'react';
import type { Terminal } from '@xterm/xterm';

interface UseTerminalHotkeysOptions {
  onData: (data: string) => void;
  copySelection: (term: Terminal | null) => Promise<boolean>;
  pasteClipboard: (onData: (data: string) => void) => Promise<void>;
  onOpenSearch?: () => void;
}

export function useTerminalHotkeys({ onData, copySelection, pasteClipboard, onOpenSearch }: UseTerminalHotkeysOptions) {
  const onDataRef = useRef(onData);
  const copySelectionRef = useRef(copySelection);
  const pasteClipboardRef = useRef(pasteClipboard);
  const onOpenSearchRef = useRef(onOpenSearch);

  useEffect(() => {
    onDataRef.current = onData;
    copySelectionRef.current = copySelection;
    pasteClipboardRef.current = pasteClipboard;
    onOpenSearchRef.current = onOpenSearch;
  }, [onData, copySelection, pasteClipboard, onOpenSearch]);

  const handleKeyEvent = useCallback(
    (term: Terminal | null) => (event: KeyboardEvent): boolean => {
      if (!term) return true;
      if (event.type !== 'keydown') return true;

      const isModifier = event.ctrlKey || event.metaKey;
      const key = event.key.toLowerCase();
      if (!isModifier) return true;

      if (key === 'c' && !event.shiftKey && term.hasSelection()) {
        void copySelectionRef.current(term);
        return false;
      }
      if (key === 'c' && event.shiftKey) {
        void copySelectionRef.current(term);
        return false;
      }
      if (key === 'enter' && event.ctrlKey) {
        onDataRef.current('\n');
        return false;
      }
      if (key === 'a' && event.shiftKey) {
        term.selectAll();
        return false;
      }
      if (key === 'f' && !event.shiftKey) {
        event.preventDefault();
        event.stopPropagation();
        onOpenSearchRef.current?.();
        return false;
      }
      if (key === 'l' && !event.shiftKey) return true;
      if (key === 'r' && !event.shiftKey) return true;
      if (key === 'insert' && event.shiftKey && !event.ctrlKey) {
        void pasteClipboardRef.current(onDataRef.current);
        return false;
      }

      return true;
    },
    []
  );

  return { handleKeyEvent };
}
