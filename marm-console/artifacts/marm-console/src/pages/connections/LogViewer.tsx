import { Button } from '@/components/ui/core';
import { useRuntimeLogTail } from '@/hooks/use-runtime-logs';
import { ErrorState, Toggle, mutationMessage } from './controls';

export function LogViewer({ source }: { source: 'runtime' | 'docker' }) {
  const log = useRuntimeLogTail(true, source);
  return (
    <section className="mt-3 space-y-2" aria-label={source === 'runtime' ? 'Runtime log viewer' : 'Container log viewer'}>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-xs"><Toggle label="Auto-refresh logs" checked={log.auto} onChange={log.setAuto} />Auto-refresh</label>
        <Button size="sm" variant="outline" disabled={log.loading} onClick={() => void log.refresh()}>Refresh logs</Button>
        <Button size="sm" variant="ghost" onClick={log.clear}>Clear view</Button>
      </div>
      {Boolean(log.error) && <ErrorState message={mutationMessage(log.error)} />}
      {log.rotated && <p role="status" className="text-xs text-muted-foreground">The log was rotated. Showing the current log.</p>}
      <pre aria-label={source === 'runtime' ? 'Runtime logs' : 'Container logs'} tabIndex={0} className="max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-border/60 bg-background/60 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">{log.lines.join('\n') || (log.exists === false ? 'No log yet.' : log.exists === null ? 'Loading...' : 'No log lines yet.')}</pre>
    </section>
  );
}
