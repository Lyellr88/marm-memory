import { useState, useEffect, useRef, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useBuildConcepts, useMarmConfig, useFilters, useConceptBuild, useConceptBuilds, useConceptsSummary, useStopConceptBuild, useRetryConceptBuild, useDeleteConceptGraph, useConceptLegacyNames } from '@/hooks/use-marm-queries';
import { Button, Badge, Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Select, SelectTrigger, SelectValue, SelectContent, SelectItem, Label } from '@/components/ui/core';
import { Play, X, Trash2, Square, Database, Network, Waypoints, CircleCheck, CircleAlert, History, CheckCircle2 } from 'lucide-react';
import type { ConceptBuildInput, ConceptBuildRun } from '@/lib/marm-types';
import { RecentRuns, buildScopeLabel } from './RecentRuns';

type BuildConceptsDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: string | null;
  onJobIdChange: (jobId: string | null) => void;
  onComplete: (job: ConceptBuildRun) => void;
};

export function BuildConceptsDialog({
  open,
  onOpenChange,
  jobId,
  onJobIdChange,
  onComplete,
}: BuildConceptsDialogProps) {
  const build = useBuildConcepts();
  const { baseUrl } = useMarmConfig();
  const queryClient = useQueryClient();
  const { data: filters } = useFilters();
  const { data: summary } = useConceptsSummary();
  const { data: jobStatus } = useConceptBuild(jobId || '');
  const { data: buildHistory, isLoading: historyLoading } = useConceptBuilds();
  const stopBuild = useStopConceptBuild();
  const retryBuild = useRetryConceptBuild();
  const deleteGraph = useDeleteConceptGraph();
  const { data: legacyNames } = useConceptLegacyNames();
  const [scope, setScope] = useState<'session' | 'project' | 'all'>('session');
  const [scopeValue, setScopeValue] = useState('');
  const [confirmAll, setConfirmAll] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [resetOpen, setResetOpen] = useState(false);
  const [rebuildAfterReset, setRebuildAfterReset] = useState(false);
  const [lifecycleError, setLifecycleError] = useState('');
  const [runAccents, setRunAccents] = useState<Record<string, 'new' | 'success'>>({});
  const completedJobId = useRef<string | null>(null);
  const wasOpen = useRef(false);
  const observedRunStates = useRef(new Map<string, ConceptBuildRun['status']>());
  const accentResetTimer = useRef<number | null>(null);

  const handleBuild = () => {
    const input: ConceptBuildInput =
      scope === 'session' ? { session_name: scopeValue } :
      scope === 'project' ? { project: scopeValue } :
      { search_all: true };
    build.mutate(input, {
      onSuccess: (res) => onJobIdChange(res.job_id)
    });
  };

  const isRunning = !!jobId && (!jobStatus || jobStatus.status === 'queued' || jobStatus.status === 'running');
  const canSubmit = scope === 'all' ? confirmAll : !!scopeValue;

  useEffect(() => {
    if (!jobStatus || isRunning) return;
    queryClient.invalidateQueries({ queryKey: ['conceptsSummary', baseUrl] });
    queryClient.invalidateQueries({ queryKey: ['conceptLegacyNames', baseUrl] });
    queryClient.invalidateQueries({ queryKey: ['conceptsSearch', baseUrl] });
    queryClient.invalidateQueries({ queryKey: ['conceptsGraph', baseUrl] });
    queryClient.invalidateQueries({ queryKey: ['duplicates', baseUrl] });
    if (completedJobId.current !== jobStatus.id) {
      completedJobId.current = jobStatus.id;
      onComplete(jobStatus);
    }
  }, [baseUrl, isRunning, jobStatus, onComplete, queryClient]);

  useEffect(() => {
    if (open && !wasOpen.current) {
      setLifecycleError('');
    }
    if (!open) {
      setScope('session');
      setScopeValue('');
      setConfirmAll(false);
      setResetOpen(false);
      setRebuildAfterReset(false);
    }
    wasOpen.current = open;
  }, [buildHistory, jobId, open]);

  const historyActiveBuild = buildHistory?.find(
    (buildRun) => buildRun.status === 'queued' || buildRun.status === 'running',
  );
  const activeBuild = isRunning && jobStatus ? jobStatus : historyActiveBuild;
  const hasActiveBuild = isRunning || !!historyActiveBuild;

  useEffect(() => {
    if (!hasActiveBuild) return;
    setNow(Date.now());
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [hasActiveBuild]);

  useEffect(() => {
    if (!buildHistory) return;
    const previousStates = observedRunStates.current;
    const nextStates = new Map(buildHistory.map((buildRun) => [buildRun.id, buildRun.status]));
    const accents: Record<string, 'new' | 'success'> = {};

    if (open && previousStates.size > 0) {
      buildHistory.forEach((buildRun) => {
        const previousStatus = previousStates.get(buildRun.id);
        if (!previousStatus) accents[buildRun.id] = 'new';
        if (previousStatus && previousStatus !== 'success' && buildRun.status === 'success') accents[buildRun.id] = 'success';
      });
    }

    observedRunStates.current = nextStates;
    if (Object.keys(accents).length === 0) return;
    setRunAccents(accents);
    if (accentResetTimer.current) window.clearTimeout(accentResetTimer.current);
    accentResetTimer.current = window.setTimeout(() => setRunAccents({}), 2200);
  }, [buildHistory, open]);

  useEffect(() => () => {
    if (accentResetTimer.current) window.clearTimeout(accentResetTimer.current);
  }, []);

  const elapsedAt = activeBuild?.started_at || activeBuild?.created_at || jobStatus?.started_at || jobStatus?.created_at;
  const elapsedSeconds = elapsedAt
    ? Math.max(0, Math.floor((now - new Date(elapsedAt).getTime()) / 1000))
    : 0;
  const elapsed = `${Math.floor(elapsedSeconds / 60)}:${String(elapsedSeconds % 60).padStart(2, '0')}`;
  const memoriesTotal = activeBuild?.memories_total || jobStatus?.memories_total || 0;
  const memoriesProcessed = activeBuild?.memories_processed || jobStatus?.memories_processed || 0;
  const progress = memoriesTotal > 0
    ? Math.min(100, Math.round((memoriesProcessed / memoriesTotal) * 100))
    : 0;
  const lifecyclePending = stopBuild.isPending || retryBuild.isPending || deleteGraph.isPending;
  const graphStatus = summary?.schema_status === 'rebuild_required'
    ? 'Rebuild needed'
    : summary?.schema_status === 'unavailable'
      ? 'Unavailable'
      : (summary?.entities ?? 0) > 0
        ? 'Current'
        : 'Ready to build';
  const recentSuccessfulBuild = buildHistory?.find((buildRun) => buildRun.status === 'success');

  const showLifecycleError = (error: unknown, fallback: string) => {
    setLifecycleError(error instanceof Error ? error.message : fallback);
  };

  const retryHistoryBuild = (runId: string) => {
    setLifecycleError('');
    retryBuild.mutate(runId, {
      onSuccess: ({ job_id }) => {
        onJobIdChange(job_id);
      },
      onError: (error) => showLifecycleError(error, 'Could not restart this build.'),
    });
  };

  const requestBuildStop = (runId: string) => {
    setLifecycleError('');
    stopBuild.mutate(runId, {
      onError: (error) => showLifecycleError(error, 'Could not stop this build.'),
    });
  };

  const confirmGraphDeletion = () => {
    setLifecycleError('');
    deleteGraph.mutate(undefined, {
      onSuccess: () => {
        onJobIdChange(null);
        setResetOpen(false);
        if (rebuildAfterReset) {
          setRebuildAfterReset(false);
          build.mutate({ search_all: true }, {
            onSuccess: (res) => onJobIdChange(res.job_id),
            onError: (error) => showLifecycleError(error, 'The graph was reset, but the rebuild could not start.'),
          });
        }
      },
      onError: (error) => showLifecycleError(error, 'Could not reset the concept graph.'),
    });
  };

  const handleDialogOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && !isRunning) onJobIdChange(null);
    onOpenChange(nextOpen);
  };

  return (
    <Dialog open={open} onOpenChange={handleDialogOpenChange}>
      <DialogContent className="concept-manager-dialog max-h-[calc(100vh-2rem)] max-w-3xl gap-0 p-0">
        <DialogClose asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="absolute right-5 top-5 z-10 h-8 w-8"
            aria-label="Close concept graph manager"
          >
            <X className="h-4 w-4" />
          </Button>
        </DialogClose>
        <DialogHeader className="concept-manager-header border-b border-border/70 px-6 py-5 pr-16">
          <div className="mb-1 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">
            <Database className="h-3.5 w-3.5" /> Derived knowledge
          </div>
          <DialogTitle>Concept Graph Manager</DialogTitle>
          <DialogDescription>Build, monitor, and maintain the graph extracted from your memories.</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 space-y-5 overflow-y-auto px-6 py-5 [scrollbar-gutter:stable]">
          {lifecycleError && (
            <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              {lifecycleError}
            </div>
          )}

          <section className="graph-metrics-rail grid overflow-hidden rounded-xl border border-card-border border-t-primary/45 bg-card/80 shadow-[0_18px_44px_rgba(0,0,0,0.18)] sm:grid-cols-4">
            <div className="graph-metric metric-enter border-b border-border/70 p-4 sm:border-b-0 sm:border-r" style={{ animationDelay: '0ms' }}>
              <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {graphStatus === 'Current' || graphStatus === 'Ready to build' ? <CircleCheck className="h-3.5 w-3.5 text-primary" /> : <CircleAlert className="h-3.5 w-3.5 text-amber-500" />}
                Graph status
              </div>
              <div className="mt-2 text-sm font-semibold">{graphStatus}</div>
            </div>
            <GraphMetric icon={<Network className="h-3.5 w-3.5" />} label="Entities" value={summary?.entities ?? 0} delay={45} />
            <GraphMetric icon={<Waypoints className="h-3.5 w-3.5" />} label="Relationships" value={summary?.relationships ?? 0} delay={90} />
            <GraphMetric icon={<Database className="h-3.5 w-3.5" />} label="Code links" value={summary?.code_links ?? 0} delay={135} />
          </section>

          {legacyNames && legacyNames.count > 0 && (
            <section role="status" aria-label="Legacy concept names" className="concept-manager-panel flex flex-col gap-4 rounded-xl border border-amber-500/25 bg-amber-500/[0.06] p-5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-sm font-semibold">Some concept names may contain legacy markdown formatting</h2>
                <p className="mt-1 max-w-xl text-sm text-muted-foreground">
                  {legacyNames.count.toLocaleString()} of {legacyNames.checked.toLocaleString()} names predate the extraction cleanup, for example{' '}
                  {legacyNames.sample.slice(0, 3).map((name, index) => (
                    <span key={name}>{index > 0 && ', '}<code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{name}</code></span>
                  ))}
                  . Rebuild the graph to apply the cleanup; your memories are not changed.
                </p>
              </div>
              <Button variant="outline" className="shrink-0" disabled={hasActiveBuild || lifecyclePending} onClick={() => { setRebuildAfterReset(true); setResetOpen(true); }}>
                Rebuild graph
              </Button>
            </section>
          )}

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.08fr)_minmax(17rem,.92fr)]">
            <section className="concept-manager-panel rounded-xl border border-border/80 bg-card/60 p-5">
              <div className="mb-5">
                <h2 className="text-sm font-semibold">Build from memory</h2>
                <p className="mt-1 text-sm text-muted-foreground">Choose one scope. Builds continue safely after you close this manager.</p>
              </div>
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Build scope</Label>
                  <Select value={scope} onValueChange={(value) => { setScope(value as 'session' | 'project' | 'all'); setScopeValue(''); setConfirmAll(false); }}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="session">Session — focused extraction</SelectItem>
                      <SelectItem value="project">Project — related work</SelectItem>
                      <SelectItem value="all">All memory — global extraction</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {scope === 'session' && (
                  <div className="space-y-2">
                    <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Session</Label>
                    <Select value={scopeValue} onValueChange={setScopeValue}>
                      <SelectTrigger><SelectValue placeholder="Choose a session" /></SelectTrigger>
                      <SelectContent>{filters?.sessions.map((session) => <SelectItem key={session} value={session}>{session}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                )}
                {scope === 'project' && (
                  <div className="space-y-2">
                    <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Project</Label>
                    <Select value={scopeValue} onValueChange={setScopeValue}>
                      <SelectTrigger><SelectValue placeholder="Choose a project" /></SelectTrigger>
                      <SelectContent>{filters?.projects.map((project) => <SelectItem key={project} value={project}>{project}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                )}
                {scope === 'all' && (
                  <label className="flex items-start gap-3 rounded-lg border border-amber-500/20 bg-amber-500/10 p-3 text-sm">
                    <input type="checkbox" checked={confirmAll} onChange={(event) => setConfirmAll(event.target.checked)} className="mt-0.5" />
                    <span>Process every memory across every session and project. This may take a while.</span>
                  </label>
                )}
                <Button onClick={handleBuild} isLoading={build.isPending} disabled={!canSubmit || hasActiveBuild} className="w-full">
                  <Play className="mr-2 h-4 w-4" /> Start build
                </Button>
                {hasActiveBuild && <p className="text-xs text-muted-foreground">Finish or stop the active build before starting another one.</p>}
              </div>
            </section>

            <section className={`concept-manager-panel relative overflow-hidden rounded-xl border p-5 ${hasActiveBuild ? 'concept-build-live border-primary/35 bg-primary/5' : 'border-border/80 bg-card/60'}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    {hasActiveBuild ? <span className="status-pulse h-2 w-2 rounded-full bg-primary" /> : recentSuccessfulBuild ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <History className="h-4 w-4 text-muted-foreground" />}
                    {hasActiveBuild ? 'Active build' : recentSuccessfulBuild ? 'Latest build' : 'Build activity'}
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {hasActiveBuild ? 'Progress is saved as each memory is processed.' : recentSuccessfulBuild ? 'The latest extraction completed and is ready to explore.' : 'Your latest and retriable runs are listed below.'}
                  </p>
                </div>
                {hasActiveBuild && <Badge className="uppercase">{activeBuild?.status || 'Starting'}</Badge>}
              </div>
              {hasActiveBuild ? (
                <div className="mt-5 space-y-4">
                  <div className="flex items-end justify-between gap-3">
                    <div>
                      <div className="font-mono text-2xl font-semibold">{memoriesProcessed}<span className="text-base text-muted-foreground"> / {memoriesTotal || '—'}</span></div>
                      <div className="mt-1 text-xs text-muted-foreground">memories processed</div>
                    </div>
                    <div className="text-right text-xs text-muted-foreground">Elapsed<br /><span className="font-mono text-sm text-foreground">{elapsed}</span></div>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="Concept build progress" aria-valuemin={0} aria-valuemax={memoriesTotal || undefined} aria-valuenow={memoriesTotal ? memoriesProcessed : undefined}>
                    <div className="h-full bg-primary transition-all" style={{ width: `${progress}%` }} />
                  </div>
                  {activeBuild?.id && (
                    <Button variant="outline" className="w-full" disabled={lifecyclePending || !!activeBuild.cancel_requested_at} onClick={() => requestBuildStop(activeBuild.id)}>
                      <Square className="mr-2 h-3.5 w-3.5" /> {activeBuild.cancel_requested_at ? 'Stopping safely...' : 'Stop build'}
                    </Button>
                  )}
                  <Button variant="ghost" className="w-full" onClick={() => handleDialogOpenChange(false)}>Run in background</Button>
                </div>
              ) : recentSuccessfulBuild ? (
                <div className={`mt-5 rounded-lg border border-emerald-400/20 bg-emerald-400/[0.045] p-4 ${runAccents[recentSuccessfulBuild.id] === 'success' ? 'concept-run-success' : ''}`}>
                  <div className="flex items-end justify-between gap-3">
                    <div>
                      <div className="font-mono text-2xl font-semibold text-emerald-300">+{recentSuccessfulBuild.entities_extracted}</div>
                      <div className="mt-1 text-xs text-muted-foreground">entities from {buildScopeLabel(recentSuccessfulBuild)}</div>
                    </div>
                    <div className="text-right text-xs text-muted-foreground"><span className="font-mono text-sm text-foreground">+{recentSuccessfulBuild.relationships_created}</span><br />relationships</div>
                  </div>
                  <div className="mt-4 flex items-center gap-2 text-xs text-emerald-200/80"><CheckCircle2 className="h-3.5 w-3.5" /> Graph data updated</div>
                </div>
              ) : (
                <div className="mt-5 rounded-lg border border-dashed border-border/80 bg-background/30 p-4 text-sm text-muted-foreground">
                  A build extracts entities and relationships into derived graph data. It never changes your source memories.
                </div>
              )}
            </section>
          </div>

          <RecentRuns buildHistory={buildHistory} historyLoading={historyLoading} now={now} runAccents={runAccents} lifecyclePending={lifecyclePending} onStop={requestBuildStop} onRetry={retryHistoryBuild} />

          <section className="concept-manager-panel flex flex-col gap-4 rounded-xl border border-destructive/25 bg-destructive/[0.035] p-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-sm font-semibold">Graph maintenance</h2>
              <p className="mt-1 max-w-xl text-sm text-muted-foreground">Run records are kept because their graph output may be shared. Resetting is the safe way to remove all derived graph data; memories and indexed code stay untouched.</p>
              {hasActiveBuild && <p className="mt-2 text-xs text-muted-foreground">Stop the active build and wait for it to finish before resetting the graph.</p>}
            </div>
            <Button variant="destructive" className="shrink-0" disabled={hasActiveBuild || lifecyclePending} onClick={() => setResetOpen(true)}>
              <Trash2 className="mr-2 h-4 w-4" /> Reset graph
            </Button>
          </section>
        </div>
      </DialogContent>

      <Dialog open={resetOpen} onOpenChange={(nextOpen) => { if (deleteGraph.isPending) return; setResetOpen(nextOpen); if (!nextOpen) setRebuildAfterReset(false); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reset the concept graph?</DialogTitle>
            <DialogDescription>This removes the derived concept entities, relationships, code links, and build history. Your memories and indexed code projects are not affected.</DialogDescription>
          </DialogHeader>
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            A timestamped backup is retained. Your duplicate-review choices remain, so future builds continue to respect them.
          </div>
          {rebuildAfterReset && (
            <p className="text-sm text-muted-foreground">Once the reset finishes, Build Concepts runs over all memory to rebuild the graph.</p>
          )}
          <DialogFooter>
            <Button variant="outline" disabled={deleteGraph.isPending} onClick={() => { setResetOpen(false); setRebuildAfterReset(false); }}>Cancel</Button>
            <Button variant="destructive" isLoading={deleteGraph.isPending} onClick={confirmGraphDeletion}>Reset graph</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Dialog>
  );
}

function GraphMetric({ icon, label, value, delay }: { icon: ReactNode; label: string; value: number; delay: number }) {
  return (
    <div className="graph-metric metric-enter border-b border-border/70 p-4 last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0" style={{ animationDelay: `${delay}ms` }}>
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        <span className="text-primary/75">{icon}</span>{label}
      </div>
      <div className="mt-2 font-mono text-lg font-semibold tracking-[-0.04em]">{value.toLocaleString()}</div>
    </div>
  );
}

export { DuplicatesTab } from './DuplicatesTab';
