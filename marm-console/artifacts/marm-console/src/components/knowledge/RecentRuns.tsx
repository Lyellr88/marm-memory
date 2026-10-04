import { Button, Badge } from '@/components/ui/core';
import { Square, RotateCcw } from 'lucide-react';
import type { ConceptBuildRun } from '@/lib/marm-types';

export function buildScopeLabel(buildRun: ConceptBuildRun) {
  if (buildRun.scope_type === 'all') return 'All memory';
  return `${buildRun.scope_type === 'session' ? 'Session' : 'Project'} · ${buildRun.scope_value || 'Unknown'}`;
}

type RecentRunsProps = {
  buildHistory: ConceptBuildRun[] | undefined;
  historyLoading: boolean;
  now: number;
  runAccents: Record<string, 'new' | 'success'>;
  lifecyclePending: boolean;
  onStop: (runId: string) => void;
  onRetry: (runId: string) => void;
};

export function RecentRuns({ buildHistory, historyLoading, now, runAccents, lifecyclePending, onStop, onRetry }: RecentRunsProps) {
  return (
    <section className="concept-manager-panel rounded-xl border border-border/80 bg-card/60">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold">Recent runs</h2>
          <p className="mt-1 text-sm text-muted-foreground">Persistent run records, with actions available when they are safe.</p>
        </div>
        <Badge variant="outline" className="font-mono">{buildHistory?.length ?? 0} recorded</Badge>
      </div>
      <div className="max-h-[20rem] space-y-2 overflow-y-auto p-3 [scrollbar-gutter:stable]" role="region" aria-label="Recent concept graph runs" tabIndex={0}>
        {historyLoading ? (
          <div className="py-10 text-center text-sm text-muted-foreground">Loading recent runs...</div>
        ) : buildHistory?.length ? buildHistory.map((buildRun) => {
          const active = buildRun.status === 'queued' || buildRun.status === 'running';
          const retryable = buildRun.status === 'error' || buildRun.status === 'degraded' || buildRun.status === 'cancelled';
          const scopeLabel = buildScopeLabel(buildRun);
          const started = buildRun.started_at || buildRun.created_at;
          const duration = buildRun.duration_ms != null ? `${Math.max(1, Math.round(buildRun.duration_ms / 1000))}s` : active && started ? `${Math.max(0, Math.floor((now - new Date(started).getTime()) / 1000))}s elapsed` : '—';
          const statusVariant = buildRun.status === 'error' ? 'destructive' : buildRun.status === 'degraded' ? 'outline' : 'default';
          return (
            <article key={buildRun.id} className={`concept-run-card rounded-lg border p-4 ${active ? 'border-primary/35 bg-primary/5' : 'border-border/80 bg-background/25'} ${runAccents[buildRun.id] === 'new' ? 'concept-run-new' : ''} ${runAccents[buildRun.id] === 'success' ? 'concept-run-success' : ''}`}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold">{scopeLabel}</div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-xs text-muted-foreground">
                    <span>{buildRun.memories_processed} / {buildRun.memories_total || '—'} memories</span>
                    <span>{duration}</span>
                  </div>
                </div>
                <Badge variant={statusVariant} className="shrink-0 uppercase">{buildRun.status}</Badge>
              </div>
              {buildRun.error_code && <p className="mt-3 text-xs text-muted-foreground">{buildRun.error_code === 'cancelled_by_user' ? 'Stopped by user; partial scoped extraction remains.' : buildRun.error_code}</p>}
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-3">
                <span className="text-xs text-muted-foreground">{buildRun.entities_extracted} entities · {buildRun.relationships_created} relationships · {buildRun.code_links_created} code links</span>
                {active ? (
                  <Button variant="outline" size="sm" disabled={lifecyclePending || !!buildRun.cancel_requested_at} onClick={() => onStop(buildRun.id)}>
                    <Square className="mr-2 h-3.5 w-3.5" /> {buildRun.cancel_requested_at ? 'Stopping...' : 'Stop'}
                  </Button>
                ) : retryable ? (
                  <Button variant="outline" size="sm" disabled={lifecyclePending} onClick={() => onRetry(buildRun.id)}>
                    <RotateCcw className="mr-2 h-3.5 w-3.5" /> Try again
                  </Button>
                ) : null}
              </div>
            </article>
          );
        }) : (
          <div className="rounded-lg border border-dashed border-border/80 py-10 text-center text-sm text-muted-foreground">No builds yet. Start with a session, project, or all memory.</div>
        )}
      </div>
    </section>
  );
}
