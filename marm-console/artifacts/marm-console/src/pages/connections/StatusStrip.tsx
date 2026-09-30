import type { ReactNode } from 'react';
import { cn } from '@/components/ui/core';
import type { ConnectionsOverview } from '@/lib/marm-types';

function Chip({ dot, children }: { dot?: 'good' | 'warn'; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1.5 text-xs text-muted-foreground">
      {dot && <span className={cn('h-[7px] w-[7px] rounded-full', dot === 'good' ? 'bg-emerald-400 shadow-[0_0_0_3px_rgba(52,211,153,0.12)]' : 'bg-amber-400 shadow-[0_0_0_3px_rgba(251,191,36,0.12)]')} />}
      {children}
    </span>
  );
}

const RUNTIME_LABEL: Record<string, string> = { ready: 'running', starting: 'starting', stopped: 'stopped', stale: 'not responding' };

export function StatusStrip({ overview }: { overview: ConnectionsOverview | undefined }) {
  if (!overview) return <div className="mb-5 h-8" aria-label="Setup status" />;
  const running = overview.runtime.state === 'ready';
  const keyed = /key/i.test(overview.auth.mode);
  return (
    <div className="mb-5 flex flex-wrap gap-2" aria-label="Setup status">
      <Chip dot={running ? 'good' : 'warn'}>Runtime <b className="font-semibold text-foreground">{RUNTIME_LABEL[overview.runtime.state] ?? overview.runtime.state}</b> · {overview.runtime.url}</Chip>
      <Chip dot={keyed ? 'good' : 'warn'}>Auth <b className="font-semibold text-foreground">{keyed ? 'key required' : 'local only'}</b></Chip>
      <Chip>Agents <b className="font-semibold text-foreground">{overview.agents.connected} of {overview.agents.detected} connected</b></Chip>
      <Chip>MARM skill <b className="font-semibold text-foreground">{overview.skills_installed} {overview.skills_installed === 1 ? 'agent' : 'agents'}</b></Chip>
      <Chip>Version <b className="font-semibold text-foreground">{overview.version}</b></Chip>
    </div>
  );
}
