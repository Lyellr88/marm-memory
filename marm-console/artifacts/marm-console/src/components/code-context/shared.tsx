import { useCallback, useState } from 'react';
import { Button } from '@/components/ui/core';
import { Check, Copy } from 'lucide-react';

/** Copy to clipboard, surfacing failure rather than swallowing it.
 *
 *  The terminal's useClipboard swallows errors, which is right for a keyboard
 *  shortcut and wrong for a button: the Console is reachable over plain HTTP on
 *  a LAN, where `navigator.clipboard` is undefined, and a button that silently
 *  does nothing is worse than one that says it failed. */
export function useCopy(resetMs = 1500) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');

  const copy = useCallback(
    async (text: string) => {
      try {
        if (!navigator.clipboard) throw new Error('clipboard unavailable');
        await navigator.clipboard.writeText(text);
        setState('copied');
      } catch {
        setState('failed');
      }
      setTimeout(() => setState('idle'), resetMs);
    },
    [resetMs],
  );

  return { state, copy };
}

export function CopyButton({
  value,
  label,
  className,
}: {
  value: string;
  label: string;
  className?: string;
}) {
  const { state, copy } = useCopy();
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className={className}
      title={state === 'failed' ? 'Copy failed' : label}
      aria-label={label}
      onClick={() => void copy(value)}
    >
      {state === 'copied' ? (
        <Check className="h-3.5 w-3.5 text-emerald-400" />
      ) : (
        <Copy className={`h-3.5 w-3.5 ${state === 'failed' ? 'text-destructive' : ''}`} />
      )}
    </Button>
  );
}

/** The house loading box, copied from System.tsx rather than extracted: one
 *  caller, one line, no blast radius. Extract when a third appears. */
export function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex min-h-40 items-center justify-center rounded-xl border border-dashed border-border/80 text-sm text-muted-foreground">
      <svg className="mr-2 h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
      </svg>
      {label}
    </div>
  );
}
