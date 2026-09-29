import type { ReactNode, SelectHTMLAttributes } from 'react';
import { XCircle } from 'lucide-react';
import { cn } from '@/components/ui/core';
import { MarmApiError } from '@/lib/marm-api';

const PILL_TONE = {
  neutral: 'border-border text-muted-foreground',
  good: 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300',
  warn: 'border-amber-400/25 bg-amber-400/10 text-amber-300',
  info: 'border-primary/25 bg-primary/10 text-primary-highlight',
  bad: 'border-destructive/25 bg-destructive/10 text-destructive',
};

export function Pill({ tone = 'neutral', children }: { tone?: keyof typeof PILL_TONE; children: ReactNode }) {
  return <span className={cn('inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold', PILL_TONE[tone])}>{children}</span>;
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (next: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative h-5 w-9 shrink-0 rounded-full border border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-50',
        checked ? 'bg-primary' : 'bg-input',
      )}
    >
      <span className={cn('absolute left-[3px] top-[3px] h-3.5 w-3.5 rounded-full bg-foreground/80 transition-transform', checked && 'translate-x-[14px] bg-primary-foreground')} />
    </button>
  );
}

export function NativeSelect({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn('flex h-9 w-full rounded-md border border-input bg-background/70 px-3 py-1 text-sm hover:border-primary/35 focus-visible:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/15 disabled:cursor-not-allowed disabled:opacity-50', className)}
      {...props}
    />
  );
}

export function mutationMessage(err: unknown) {
  if (err instanceof MarmApiError) return err.message;
  return err instanceof Error ? err.message : 'The request failed.';
}

export function ErrorState({ message }: { message: string }) {
  return <div className="mb-3 rounded-lg border border-destructive/25 bg-destructive/[0.05] p-3 text-xs text-destructive"><XCircle className="mr-2 inline h-3.5 w-3.5" />{message}</div>;
}
