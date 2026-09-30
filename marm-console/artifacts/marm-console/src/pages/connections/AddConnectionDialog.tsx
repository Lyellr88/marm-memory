import { useState } from 'react';
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, Label } from '@/components/ui/core';
import { CopyButton } from '@/components/code-context/shared';
import type { ConnectionsOverview } from '@/lib/marm-types';
import { NativeSelect } from './controls';

const SUPPORT_EMAIL = 'support@marmemory.com';
const TRANSPORTS = ['HTTP', 'STDIO', 'Not sure'];

function buildEmail(tool: string, transport: string, overview: ConnectionsOverview | undefined) {
  const name = tool.trim() || 'your tool';
  const subject = `Connection request: ${name}`;
  const runtime = overview
    ? `${overview.runtime.managed ? 'managed' : 'not managed'}, ${overview.runtime.state}, ${overview.runtime.url}`
    : 'unknown';
  const body = [
    `Tool: ${name}`,
    `Connects over: ${transport}`,
    `MARM version: ${overview?.version ?? 'unknown'}`,
    `System: ${overview?.os ?? 'unknown'}`,
    `Runtime: ${runtime}`,
  ].join('\n');
  return { subject, body, href: `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}` };
}

export function AddConnectionDialog({ open, onOpenChange, overview }: { open: boolean; onOpenChange: (open: boolean) => void; overview: ConnectionsOverview | undefined }) {
  const [tool, setTool] = useState('');
  const [transport, setTransport] = useState(TRANSPORTS[0]);
  const email = buildEmail(tool, transport, overview);
  const ready = tool.trim().length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a connection</DialogTitle>
          <DialogDescription>This opens an email to {SUPPORT_EMAIL} with your details filled in. Your API key is never included.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="add-tool">Tool name</Label>
            <Input id="add-tool" value={tool} onChange={(event) => setTool(event.target.value)} placeholder="e.g. Zed, JetBrains AI" />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="add-transport">How it connects</Label>
            <NativeSelect id="add-transport" value={transport} onChange={(event) => setTransport(event.target.value)}>
              {TRANSPORTS.map((option) => <option key={option} value={option}>{option}</option>)}
            </NativeSelect>
          </div>
        </div>
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-border/60 bg-background/60 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">{`To: ${SUPPORT_EMAIL}\nSubject: ${email.subject}\n\n${email.body}`}</pre>
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <span>Prefer your own mail app? Write to</span>
          <span className="select-all font-mono text-foreground">{SUPPORT_EMAIL}</span>
          <CopyButton value={SUPPORT_EMAIL} label="Copy email address" />
        </div>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          {ready
            ? <a href={email.href} className="inline-flex h-9 items-center justify-center rounded-md border border-primary/70 bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">Open email</a>
            : <Button disabled>Open email</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
