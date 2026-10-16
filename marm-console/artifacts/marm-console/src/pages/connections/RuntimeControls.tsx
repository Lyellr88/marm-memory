import { useState } from 'react';
import { useRuntimeControlJob, useStartRuntime, useStopRuntime, useStartRuntimeRestart } from '@/hooks/use-marm-queries';
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/core';
import type { ConnectionsOverview } from '@/lib/marm-types';
import { ErrorState, mutationMessage } from './controls';
import { LogViewer } from './LogViewer';

export function runtimeControlReason(runtime: ConnectionsOverview['runtime']) {
  if (runtime.controls_allowed === false) return 'Changes are turned off here. The Console must be bound to loopback.';
  if (runtime.state === 'ready' && runtime.managed) return null;
  if (runtime.state === 'starting') return 'The runtime is starting or not responding. Try again shortly.';
  if (runtime.port_owner === 'unknown') return `Could not check port ${runtime.intended_port ?? 8001}. Try again.`;
  if (runtime.port_owner === 'other') return `Port ${runtime.intended_port ?? 8001} is in use by another program.`;
  if (runtime.port_owner === 'marm') return "Running outside MARM's managed runtime. Stop it where you started it.";
  return null;
}

export function RuntimeControls({ overview, compact = false, disabled = false }: { overview: ConnectionsOverview | undefined; compact?: boolean; disabled?: boolean }) {
  const start = useStartRuntime();
  const stop = useStopRuntime();
  const restart = useStartRuntimeRestart();
  const job = useRuntimeControlJob();
  const [confirm, setConfirm] = useState(false);
  const [logs, setLogs] = useState(false);
  const runtime = overview?.runtime;
  if (!runtime) return null;
  const reason = runtimeControlReason(runtime);
  const running = runtime.state === 'ready' && runtime.managed;
  const busy = job.busy || start.isPending || stop.isPending || restart.isPending;
  const error = start.error ?? stop.error ?? restart.error ?? job.error;
  const kind = job.data?.kind ?? job.kind ?? 'start';
  const progress = { start: 'Starting', stop: 'Stopping', restart: 'Restarting' }[kind];
  return (
    <div className={compact ? 'space-y-1' : 'mb-4 space-y-3 border-b border-border/60 pb-4'}>
      <div className="flex flex-wrap items-center gap-2">
        {!running && <Button size="sm" isLoading={busy && !job.saving && kind === 'start'} disabled={disabled || busy || !!reason || !runtime.can_start} onClick={() => start.mutate()}>Start server</Button>}
        {!compact && running && <>
          <Button size="sm" variant="outline" isLoading={busy && !job.saving && kind === 'restart'} disabled={disabled || busy || !!reason} onClick={() => restart.mutate()}>Restart server</Button>
          <Button size="sm" variant="outline" isLoading={busy && !job.saving && kind === 'stop'} disabled={disabled || busy || !!reason} onClick={() => setConfirm(true)}>Stop server</Button>
        </>}
        {!compact && <Button size="sm" variant="ghost" disabled={runtime.controls_allowed === false} onClick={() => setLogs(!logs)}>{logs ? 'Hide logs' : 'View log'}</Button>}
      </div>
      {reason && <p className="text-xs text-muted-foreground">{reason}</p>}
      {busy && <p role="status" className="text-xs text-muted-foreground">{job.saving ? 'Saving settings...' : `${progress} the runtime...`}</p>}
      {job.data?.status === 'error' && <ErrorState message={job.data.detail ?? 'The runtime action failed. View log for details.'} />}
      {job.data?.status === 'done' && <p role="status" className="text-xs text-emerald-300">Runtime {kind === 'stop' ? 'stopped' : kind === 'restart' ? 'restarted' : 'started'} in {(job.data.seconds ?? 0).toFixed(1)} s</p>}
      {error && <ErrorState message={mutationMessage(error)} />}
      {!compact && logs && <LogViewer source="runtime" />}
      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent role="alertdialog">
          <DialogHeader><DialogTitle>Stop the server?</DialogTitle><DialogDescription>Agents lose their connection until the server starts again. The Console stays open.</DialogDescription></DialogHeader>
          <DialogFooter><Button variant="outline" onClick={() => setConfirm(false)}>Cancel</Button><Button variant="destructive" disabled={busy || disabled || !!reason} onClick={() => { setConfirm(false); stop.mutate(); }}>Stop server</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
