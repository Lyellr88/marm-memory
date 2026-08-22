import { useState, useEffect, useRef, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useBuildConcepts, useMarmConfig, useFilters, useConceptBuild, useConceptBuilds, useConceptsSummary, useStopConceptBuild, useRetryConceptBuild, useDeleteConceptGraph, useConceptDuplicates, useConcept, useDismissConceptDuplicate, useMergeConceptDuplicate, useRemoveConceptEntity } from '@/hooks/use-marm-queries';
import { Card, CardContent, CardHeader, CardTitle, CardDescription, Button, Badge, Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Table, TableHeader, TableRow, TableHead, TableBody, TableCell, Select, SelectTrigger, SelectValue, SelectContent, SelectItem, Label } from '@/components/ui/core';
import { Play, X, Eye, Merge, ShieldX, Trash2, ChevronLeft, ChevronRight, Square, RotateCcw, Database, Network, Waypoints, CircleCheck, CircleAlert, History, CheckCircle2 } from 'lucide-react';
import type { ConceptBuildInput, ConceptBuildRun, ConceptDetail, DuplicateCandidate } from '@/lib/marm-types';

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
  const [scope, setScope] = useState<'session' | 'project' | 'all'>('session');
  const [scopeValue, setScopeValue] = useState('');
  const [confirmAll, setConfirmAll] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [resetOpen, setResetOpen] = useState(false);
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
                        <Button variant="outline" size="sm" disabled={lifecyclePending || !!buildRun.cancel_requested_at} onClick={() => requestBuildStop(buildRun.id)}>
                          <Square className="mr-2 h-3.5 w-3.5" /> {buildRun.cancel_requested_at ? 'Stopping...' : 'Stop'}
                        </Button>
                      ) : retryable ? (
                        <Button variant="outline" size="sm" disabled={lifecyclePending} onClick={() => retryHistoryBuild(buildRun.id)}>
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

      <Dialog open={resetOpen} onOpenChange={(nextOpen) => !deleteGraph.isPending && setResetOpen(nextOpen)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reset the concept graph?</DialogTitle>
            <DialogDescription>This removes the derived concept entities, relationships, code links, and build history. Your memories and indexed code projects are not affected.</DialogDescription>
          </DialogHeader>
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            A timestamped backup is retained. Your duplicate-review choices remain, so future builds continue to respect them.
          </div>
          <DialogFooter>
            <Button variant="outline" disabled={deleteGraph.isPending} onClick={() => setResetOpen(false)}>Cancel</Button>
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

function buildScopeLabel(buildRun: ConceptBuildRun) {
  if (buildRun.scope_type === 'all') return 'All memory';
  return `${buildRun.scope_type === 'session' ? 'Session' : 'Project'} · ${buildRun.scope_value || 'Unknown'}`;
}

export function DuplicatesTab() {
  const pageSize = 100;
  const [page, setPage] = useState(0);
  const { data, isLoading, isFetching } = useConceptDuplicates({ offset: page * pageSize, limit: pageSize });
  const [selected, setSelected] = useState<DuplicateCandidate | null>(null);
  const tableScrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!data || page === 0 || page * pageSize < data.total) return;
    setPage(Math.max(0, Math.ceil(data.total / pageSize) - 1));
  }, [data, page]);

  const changePage = (nextPage: number) => {
    setPage(nextPage);
    if (tableScrollRef.current) tableScrollRef.current.scrollTop = 0;
  };

  const rangeStart = data && data.total > 0 ? data.offset + 1 : 0;
  const rangeEnd = data ? data.offset + data.items.length : 0;

  return (
    <div className="h-full flex flex-col pb-4">
      <Card className="flex-1 flex flex-col overflow-hidden">
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div className="space-y-1.5">
            <CardTitle>Potential Duplicates</CardTitle>
            <CardDescription>Compare similar concepts, merge true duplicates, or teach future builds to keep them separate.</CardDescription>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            <Badge variant="outline" className="font-mono">
              {data?.total ?? 0} found
            </Badge>
            <Badge variant="outline" className="font-mono text-amber-500">
              ≥{Math.round((data?.threshold ?? 0.88) * 100)}% similarity
            </Badge>
          </div>
        </CardHeader>
        <div ref={tableScrollRef} className="flex-1 overflow-auto p-0">
          <Table>
            <TableHeader className="sticky top-0 bg-muted/80 backdrop-blur">
              <TableRow>
                <TableHead>Entity A</TableHead>
                <TableHead>Entity B</TableHead>
                <TableHead className="text-right">Similarity</TableHead>
                <TableHead className="w-28 text-right">Review</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground h-24">Loading duplicates...</TableCell></TableRow>
              ) : data?.items.length === 0 ? (
                <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground h-24">No duplicate candidates found.</TableCell></TableRow>
              ) : (
                data?.items.map((dup) => (
                  <TableRow key={`${dup.entity_a.id}:${dup.entity_b.id}`}>
                    <TableCell>
                      <div className="font-mono text-sm">{dup.entity_a.name}</div>
                      <Badge variant="outline" className="text-[10px] mt-1">{dup.entity_a.type}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="font-mono text-sm">{dup.entity_b.name}</div>
                      <Badge variant="outline" className="text-[10px] mt-1">{dup.entity_b.type}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <span className="font-mono text-sm text-amber-500">{(dup.similarity * 100).toFixed(1)}%</span>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="outline" size="sm" onClick={() => setSelected(dup)}>
                        <Eye className="mr-2 h-3.5 w-3.5" /> Review
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
        {data && (
          <div className="flex flex-col gap-3 border-t border-border/70 px-4 py-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <span>
              Showing pairs {rangeStart}–{rangeEnd} of {data.total} from {data.scanned_entities} embedded concepts
              {data.scanned_entities === data.scan_limit ? ` (scan capped at ${data.scan_limit})` : ''}.
            </span>
            <div className="flex shrink-0 items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 0 || isFetching}
                onClick={() => changePage(page - 1)}
                aria-label="Previous duplicate pairs"
              >
                <ChevronLeft className="mr-1 h-4 w-4" /> Previous
              </Button>
              <span className="min-w-16 text-center font-mono text-foreground">
                Page {Math.floor(data.offset / data.result_limit) + 1}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={!data.has_more || isFetching}
                onClick={() => changePage(page + 1)}
                aria-label="Next duplicate pairs"
              >
                Next <ChevronRight className="ml-1 h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </Card>
      <DuplicateReviewDialog candidate={selected} onOpenChange={(open) => !open && setSelected(null)} />
    </div>
  );
}

type ReviewAction =
  | { kind: 'merge'; keep: 'a' | 'b' }
  | { kind: 'remove'; entity: 'a' | 'b' };

function DuplicateReviewDialog({
  candidate,
  onOpenChange,
}: {
  candidate: DuplicateCandidate | null;
  onOpenChange: (open: boolean) => void;
}) {
  const entityA = useConcept(candidate?.entity_a.id || 0);
  const entityB = useConcept(candidate?.entity_b.id || 0);
  const dismiss = useDismissConceptDuplicate();
  const merge = useMergeConceptDuplicate();
  const remove = useRemoveConceptEntity();
  const [confirmation, setConfirmation] = useState<ReviewAction | null>(null);
  const [error, setError] = useState('');
  const pending = dismiss.isPending || merge.isPending || remove.isPending;

  useEffect(() => {
    setConfirmation(null);
    setError('');
  }, [candidate]);

  if (!candidate) return null;

  const pair = {
    entity_a_id: candidate.entity_a.id,
    entity_b_id: candidate.entity_b.id,
  };

  const closeAfter = async (operation: Promise<unknown>) => {
    setError('');
    try {
      await operation;
      setConfirmation(null);
      onOpenChange(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The review action failed.');
    }
  };

  const confirmAction = () => {
    if (!confirmation) return;
    if (confirmation.kind === 'merge') {
      void closeAfter(merge.mutateAsync({ ...pair, keep: confirmation.keep }));
      return;
    }
    const entityId = confirmation.entity === 'a' ? pair.entity_a_id : pair.entity_b_id;
    void closeAfter(remove.mutateAsync(entityId));
  };

  const confirmationName = confirmation?.kind === 'remove'
    ? (confirmation.entity === 'a' ? candidate.entity_a.name : candidate.entity_b.name)
    : confirmation?.kind === 'merge'
      ? (confirmation.keep === 'a' ? candidate.entity_a.name : candidate.entity_b.name)
      : '';

  return (
    <>
      <Dialog open onOpenChange={onOpenChange}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>Review Potential Duplicate</DialogTitle>
            <DialogDescription>
              {(candidate.similarity * 100).toFixed(1)}% name similarity in the same graph scope. Compare provenance before changing the graph.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 md:grid-cols-2">
            <ConceptCompareCard label="Concept A" entity={candidate.entity_a} detail={entityA.data} loading={entityA.isLoading} />
            <ConceptCompareCard label="Concept B" entity={candidate.entity_b} detail={entityB.data} loading={entityB.isLoading} />
          </div>
          {error && (
            <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
          <div className="rounded-lg border border-border/80 bg-muted/20 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <Merge className="h-4 w-4 text-primary" /> Merge concepts
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <Button variant="outline" disabled={pending} onClick={() => setConfirmation({ kind: 'merge', keep: 'a' })}>
                Keep “{candidate.entity_a.name}”
              </Button>
              <Button variant="outline" disabled={pending} onClick={() => setConfirmation({ kind: 'merge', keep: 'b' })}>
                Keep “{candidate.entity_b.name}”
              </Button>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">Sources, relationships, and code links move to the name you keep. Future builds reuse that choice.</p>
          </div>
          <DialogFooter className="flex-col gap-2 sm:flex-row sm:justify-between">
            <div className="flex flex-wrap gap-2">
              <Button variant="ghost" disabled={pending} onClick={() => void closeAfter(dismiss.mutateAsync(pair))}>
                <ShieldX className="mr-2 h-4 w-4" /> Not a duplicate
              </Button>
              <Button variant="ghost" className="text-destructive hover:text-destructive" disabled={pending} onClick={() => setConfirmation({ kind: 'remove', entity: 'a' })}>
                <Trash2 className="mr-2 h-4 w-4" /> Remove A
              </Button>
              <Button variant="ghost" className="text-destructive hover:text-destructive" disabled={pending} onClick={() => setConfirmation({ kind: 'remove', entity: 'b' })}>
                <Trash2 className="mr-2 h-4 w-4" /> Remove B
              </Button>
            </div>
            <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmation !== null} onOpenChange={(open) => !open && setConfirmation(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{confirmation?.kind === 'merge' ? 'Confirm merge' : 'Remove concept from graph?'}</DialogTitle>
            <DialogDescription>
              {confirmation?.kind === 'merge'
                ? `This keeps “${confirmationName}” as the canonical concept and removes the other graph node.`
                : `This removes “${confirmationName}” and suppresses it in this exact scope so automatic builds do not add it back.`}
            </DialogDescription>
          </DialogHeader>
          {confirmation?.kind === 'remove' && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              This is destructive graph cleanup. It does not delete the source memories.
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" disabled={pending} onClick={() => setConfirmation(null)}>Cancel</Button>
            <Button variant={confirmation?.kind === 'remove' ? 'destructive' : 'default'} isLoading={pending} onClick={confirmAction}>
              {confirmation?.kind === 'merge' ? 'Merge concepts' : 'Remove concept'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function ConceptCompareCard({ label, entity, detail, loading }: {
  label: string;
  entity: DuplicateCandidate['entity_a'];
  detail: ConceptDetail | undefined;
  loading: boolean;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-border/80 bg-card/70 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{label}</span>
        <Badge variant="outline">{entity.type}</Badge>
      </div>
      <div className="truncate font-mono text-base font-semibold" title={entity.name}>{entity.name}</div>
      <div className="mt-2 flex gap-4 text-xs text-muted-foreground">
        <span>{entity.mention_count} mentions</span>
        <span>{entity.degree} links</span>
      </div>
      <div className="mt-4 space-y-2">
        <div className="flex items-center justify-between gap-3 text-xs font-medium text-muted-foreground">
          <span>Source memories</span>
          {detail?.source_memories.length ? <span>{detail.source_memories.length} attached</span> : null}
        </div>
        {loading ? (
          <div className="flex h-48 items-center justify-center rounded border border-border/60 bg-background/40 text-xs text-muted-foreground">Loading provenance...</div>
        ) : detail?.source_memories.length ? (
          <div
            className="h-48 space-y-2 overflow-y-auto rounded border border-border/60 bg-background/30 p-2 pr-1 [scrollbar-gutter:stable] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
            role="region"
            aria-label={`${label} source memories`}
            tabIndex={0}
          >
            {detail.source_memories.map((memory, index) => (
              <article key={String(memory.id)} className="rounded border border-border/60 bg-background/70 p-3 text-xs leading-relaxed">
                <div className="mb-2 flex items-center justify-between gap-3 font-mono text-[10px] text-muted-foreground">
                  <span>Memory {index + 1}</span>
                  <span>{memory.session_name}</span>
                </div>
                <p className="whitespace-pre-wrap break-words text-foreground">{memory.content}</p>
              </article>
            ))}
          </div>
        ) : (
          <div className="flex h-48 items-center justify-center rounded border border-border/60 bg-background/40 text-xs text-muted-foreground">No source memories available.</div>
        )}
      </div>
    </div>
  );
}
