import { useState, useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useBuildConcepts, useMarmConfig, useFilters, useConceptBuild, useConceptBuilds, useStopConceptBuild, useRetryConceptBuild, useDeleteConceptGraph, useConceptDuplicates, useConcept, useDismissConceptDuplicate, useMergeConceptDuplicate, useRemoveConceptEntity } from '@/hooks/use-marm-queries';
import { Card, CardContent, CardHeader, CardTitle, CardDescription, Button, Badge, Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Table, TableHeader, TableRow, TableHead, TableBody, TableCell, Select, SelectTrigger, SelectValue, SelectContent, SelectItem, Label } from '@/components/ui/core';
import { Play, AlertTriangle, X, Eye, Merge, ShieldX, Trash2, ChevronLeft, ChevronRight, Square, RotateCcw } from 'lucide-react';
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
  const { data: jobStatus } = useConceptBuild(jobId || '');
  const { data: buildHistory, isLoading: historyLoading } = useConceptBuilds();
  const stopBuild = useStopConceptBuild();
  const retryBuild = useRetryConceptBuild();
  const deleteGraph = useDeleteConceptGraph();
  const [scope, setScope] = useState<'session' | 'project' | 'all'>('session');
  const [scopeValue, setScopeValue] = useState('');
  const [confirmAll, setConfirmAll] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [tab, setTab] = useState<'start' | 'history'>('start');
  const [resetOpen, setResetOpen] = useState(false);
  const [lifecycleError, setLifecycleError] = useState('');
  const completedJobId = useRef<string | null>(null);
  const wasOpen = useRef(false);

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
      const hasActiveBuild = !!jobId || buildHistory?.some(
        (buildRun) => buildRun.status === 'queued' || buildRun.status === 'running',
      );
      setTab(hasActiveBuild ? 'history' : 'start');
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

  useEffect(() => {
    if (!isRunning) return;
    setNow(Date.now());
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [isRunning]);

  const elapsedAt = jobStatus?.started_at || jobStatus?.created_at;
  const elapsedSeconds = elapsedAt
    ? Math.max(0, Math.floor((now - new Date(elapsedAt).getTime()) / 1000))
    : 0;
  const elapsed = `${Math.floor(elapsedSeconds / 60)}:${String(elapsedSeconds % 60).padStart(2, '0')}`;
  const memoriesTotal = jobStatus?.memories_total || 0;
  const memoriesProcessed = jobStatus?.memories_processed || 0;
  const progress = memoriesTotal > 0
    ? Math.min(100, Math.round((memoriesProcessed / memoriesTotal) * 100))
    : 0;
  const errorMessage = jobStatus?.error_code === 'rebuild_required'
    ? 'This graph needs one full rebuild after the schema update. Close this dialog, choose All memory (global), confirm it, and let it finish.'
    : jobStatus?.error_code === 'stale_run'
      ? 'The build stopped reporting progress. Restart the server before trying the build again.'
      : jobStatus?.error_code === 'cancelled_by_user'
        ? 'The build stopped after its current memory. Its partial scoped extraction remains available.'
      : jobStatus?.error_code || 'The build stopped before it could finish. Try the build again.';

  const hasActiveBuild = isRunning || buildHistory?.some(
    (buildRun) => buildRun.status === 'queued' || buildRun.status === 'running',
  ) || false;
  const lifecyclePending = stopBuild.isPending || retryBuild.isPending || deleteGraph.isPending;

  const showLifecycleError = (error: unknown, fallback: string) => {
    setLifecycleError(error instanceof Error ? error.message : fallback);
  };

  const retryHistoryBuild = (runId: string) => {
    setLifecycleError('');
    retryBuild.mutate(runId, {
      onSuccess: ({ job_id }) => {
        onJobIdChange(job_id);
        setTab('start');
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
        setTab('start');
      },
      onError: (error) => showLifecycleError(error, 'Could not delete the knowledge graph.'),
    });
  };

  const handleDialogOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && !isRunning) onJobIdChange(null);
    onOpenChange(nextOpen);
  };

  return (
    <Dialog open={open} onOpenChange={handleDialogOpenChange}>
      <DialogContent>
        <DialogClose asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="absolute right-4 top-4 h-8 w-8"
            aria-label="Close build dialog"
          >
            <X className="h-4 w-4" />
          </Button>
        </DialogClose>
        <DialogHeader>
          <DialogTitle>Build Concept Graph</DialogTitle>
        </DialogHeader>
        <div className="grid grid-cols-2 border-b border-border/70" role="tablist" aria-label="Concept build workspace">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'start'}
            className={`border-b-2 px-3 py-2 text-sm font-medium transition-colors ${tab === 'start' ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
            onClick={() => setTab('start')}
          >
            Start build
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'history'}
            className={`border-b-2 px-3 py-2 text-sm font-medium transition-colors ${tab === 'history' ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
            onClick={() => setTab('history')}
          >
            Build history
          </button>
        </div>

        {lifecycleError && (
          <div role="alert" className="mt-4 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {lifecycleError}
          </div>
        )}

        {tab === 'start' && (!jobId ? (
          <div className="py-4 flex flex-col gap-4">
            <p className="text-sm text-muted-foreground">
              Extract entities and relationships from unstructured memories. Pick exactly one scope.
              This requires processing time against the local concept runtime.
            </p>
            <div className="space-y-2">
              <Label className="text-xs">Scope</Label>
              <Select value={scope} onValueChange={(v) => { setScope(v as 'session' | 'project' | 'all'); setScopeValue(''); setConfirmAll(false); }}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="session">Session</SelectItem>
                  <SelectItem value="project">Project</SelectItem>
                  <SelectItem value="all">All memory (global)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {scope === 'session' && (
              <Select value={scopeValue} onValueChange={setScopeValue}>
                <SelectTrigger><SelectValue placeholder="Choose a session" /></SelectTrigger>
                <SelectContent>
                  {filters?.sessions.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                </SelectContent>
              </Select>
            )}
            {scope === 'project' && (
              <Select value={scopeValue} onValueChange={setScopeValue}>
                <SelectTrigger><SelectValue placeholder="Choose a project" /></SelectTrigger>
                <SelectContent>
                  {filters?.projects.map(p => <SelectItem key={p} value={p}>{p}</SelectItem>)}
                </SelectContent>
              </Select>
            )}
            {scope === 'all' && (
              <label className="flex items-start gap-2 text-sm p-3 bg-amber-500/10 border border-amber-500/20 rounded">
                <input type="checkbox" checked={confirmAll} onChange={e => setConfirmAll(e.target.checked)} className="mt-1" />
                <span>I understand this processes every memory across every session and project, and may take a while.</span>
              </label>
            )}
            <Button onClick={handleBuild} isLoading={build.isPending} disabled={!canSubmit} className="w-full">
              <Play className="w-4 h-4 mr-2" /> Start Build
            </Button>
          </div>
        ) : (
          <div className="py-6 space-y-4">
            <div className="flex items-center justify-between font-mono text-sm border-b pb-2">
              <span>Status</span>
              <Badge variant={jobStatus?.status === 'error' ? 'destructive' : 'default'} className="uppercase">
                {jobStatus?.status || 'Starting...'}
              </Badge>
            </div>
            {isRunning && (
              <div className="space-y-2">
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>{memoriesTotal > 0 ? `${memoriesProcessed} of ${memoriesTotal} memories` : 'Preparing build...'}</span>
                  <span>Elapsed {elapsed}</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="Concept build progress" aria-valuemin={0} aria-valuemax={memoriesTotal || undefined} aria-valuenow={memoriesTotal ? memoriesProcessed : undefined}>
                  <div className="h-full bg-primary transition-all" style={{ width: `${progress}%` }} />
                </div>
              </div>
            )}
            {jobStatus?.status === 'degraded' && (
              <div className="p-3 bg-amber-500/10 text-amber-500 border border-amber-500/20 rounded text-sm flex gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <p>Degraded mode: {jobStatus.error_code || 'Missing dependencies on server'}</p>
              </div>
            )}
            {(jobStatus?.status === 'error' || jobStatus?.status === 'cancelled') && (
              <div className="p-3 bg-destructive/10 text-destructive border border-destructive/20 rounded text-sm flex gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <p>{errorMessage}</p>
              </div>
            )}
            <div className="grid grid-cols-2 gap-4 pt-2">
              <div className="p-4 bg-muted/30 rounded-lg text-center">
                <div className="text-2xl font-bold font-mono">{jobStatus?.entities_extracted || 0}</div>
                <div className="text-xs text-muted-foreground mt-1">Entities</div>
              </div>
              <div className="p-4 bg-muted/30 rounded-lg text-center">
                <div className="text-2xl font-bold font-mono">{jobStatus?.relationships_created || 0}</div>
                <div className="text-xs text-muted-foreground mt-1">Relationships</div>
              </div>
            </div>
            <Button className="w-full mt-4" variant="outline" onClick={() => handleDialogOpenChange(false)}>
              {isRunning ? 'Run in Background' : 'Close'}
            </Button>
          </div>
        ))}

        {tab === 'history' && (
          <div className="py-4 space-y-4">
            <div className="flex items-start justify-between gap-4">
              <p className="text-sm text-muted-foreground">Build runs persist here after this dialog closes. Stopping a build finishes its current memory safely.</p>
              <Button variant="destructive" size="sm" disabled={hasActiveBuild || lifecyclePending} onClick={() => setResetOpen(true)}>
                <Trash2 className="mr-2 h-3.5 w-3.5" /> Delete graph
              </Button>
            </div>
            {hasActiveBuild && <p className="text-xs text-muted-foreground">Stop the active build and wait for it to finish before deleting the graph.</p>}
            <div className="max-h-[22rem] space-y-2 overflow-y-auto pr-1 [scrollbar-gutter:stable]" role="region" aria-label="Concept build history" tabIndex={0}>
              {historyLoading ? (
                <div className="py-10 text-center text-sm text-muted-foreground">Loading build history...</div>
              ) : buildHistory?.length ? buildHistory.map((buildRun) => {
                const active = buildRun.status === 'queued' || buildRun.status === 'running';
                const retryable = buildRun.status === 'error' || buildRun.status === 'degraded' || buildRun.status === 'cancelled';
                const scopeLabel = buildRun.scope_type === 'all' ? 'All memory' : `${buildRun.scope_type === 'session' ? 'Session' : 'Project'} · ${buildRun.scope_value || 'Unknown'}`;
                const started = buildRun.started_at || buildRun.created_at;
                const duration = buildRun.duration_ms != null ? `${Math.max(1, Math.round(buildRun.duration_ms / 1000))}s` : active && started ? `${Math.max(0, Math.floor((now - new Date(started).getTime()) / 1000))}s elapsed` : '—';
                return (
                  <article key={buildRun.id} className="rounded-lg border border-border/80 bg-card/60 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium">{scopeLabel}</div>
                        <div className="mt-1 font-mono text-xs text-muted-foreground">{buildRun.memories_processed} / {buildRun.memories_total || '—'} memories · {duration}</div>
                      </div>
                      <Badge variant={buildRun.status === 'error' ? 'destructive' : buildRun.status === 'degraded' ? 'outline' : 'default'} className="shrink-0 uppercase">{buildRun.status}</Badge>
                    </div>
                    {buildRun.error_code && <p className="mt-2 text-xs text-muted-foreground">{buildRun.error_code === 'cancelled_by_user' ? 'Stopped by user; partial scoped extraction remains.' : buildRun.error_code}</p>}
                    <div className="mt-3 flex items-center justify-between gap-3">
                      <span className="text-xs text-muted-foreground">{buildRun.entities_extracted} entities · {buildRun.relationships_created} relationships</span>
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
                <div className="rounded-lg border border-dashed border-border/80 py-10 text-center text-sm text-muted-foreground">No concept builds yet.</div>
              )}
            </div>
          </div>
        )}
      </DialogContent>

      <Dialog open={resetOpen} onOpenChange={(nextOpen) => !deleteGraph.isPending && setResetOpen(nextOpen)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete the knowledge graph?</DialogTitle>
            <DialogDescription>This removes the derived concept entities, relationships, code links, and build history. Your memories and indexed code projects are not affected.</DialogDescription>
          </DialogHeader>
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            A timestamped backup is retained. Your duplicate-review choices remain, so future builds continue to respect them.
          </div>
          <DialogFooter>
            <Button variant="outline" disabled={deleteGraph.isPending} onClick={() => setResetOpen(false)}>Cancel</Button>
            <Button variant="destructive" isLoading={deleteGraph.isPending} onClick={confirmGraphDeletion}>Delete graph</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Dialog>
  );
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
