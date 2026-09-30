import { useState, type ReactNode } from 'react';
import { Send } from 'lucide-react';
import { Button, Input, cn } from '@/components/ui/core';
import { CopyButton } from '@/components/code-context/shared';
import { useTerminalBridge } from '@/lib/terminal-bridge';
import { NativeSelect } from './controls';

export function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn('flex min-w-[9rem] flex-1 flex-col gap-1.5 text-xs font-medium text-muted-foreground', className)}>
      {label}
      {children}
    </label>
  );
}

export function SelectField({ label, value, onChange, options }: { label: string; value: string; onChange: (next: string) => void; options: Array<{ value: string; label: string }> }) {
  return (
    <Field label={label}>
      <NativeSelect value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </NativeSelect>
    </Field>
  );
}

export function SearchBox({ value, onChange, label }: { value: string; onChange: (next: string) => void; label: string }) {
  return <Input aria-label={label} placeholder={label} value={value} onChange={(event) => onChange(event.target.value)} className="max-w-xs" />;
}

export function CodeBlock({ text, label }: { text: string; label: string }) {
  return (
    <div className="relative rounded-lg border border-border/70 bg-background/60">
      <CopyButton value={text} label={`Copy ${label}`} className="absolute right-1.5 top-1.5 h-7 w-7" />
      <pre className="overflow-x-auto p-3 pr-11 font-mono text-xs leading-relaxed">{text}</pre>
    </div>
  );
}

export function SendToTerminal({ command }: { command: string }) {
  const { available, sendToTerminal } = useTerminalBridge();
  const [sent, setSent] = useState<'idle' | 'sent' | 'failed'>('idle');
  const unavailable = <span className="text-xs text-amber-300">Terminal unavailable. Copy the command instead.</span>;
  if (!available) return unavailable;
  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setSent(sendToTerminal(command) ? 'sent' : 'failed')}
      >
        <Send className="mr-1.5 h-3.5 w-3.5" />
        {sent === 'sent' ? 'Sent to terminal' : 'Send to terminal'}
      </Button>
      {sent === 'failed' && unavailable}
    </>
  );
}
