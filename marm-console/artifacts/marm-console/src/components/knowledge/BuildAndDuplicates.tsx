import { useState, useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useBuildConcepts, useMarmConfig, useFilters, useConceptBuild, useConceptDuplicates } from '@/hooks/use-marm-queries';
import { Card, CardContent, CardHeader, CardTitle, CardDescription, Button, Badge, Dialog, DialogClose, DialogContent, DialogHeader, DialogTitle, Table, TableHeader, TableRow, TableHead, TableBody, TableCell, Select, SelectTrigger, SelectValue, SelectContent, SelectItem, Label } from '@/components/ui/core';
import { Play, AlertTriangle, X } from 'lucide-react';
import type { ConceptBuildInput, ConceptBuildRun } from '@/lib/marm-types';

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
  const [scope, setScope] = useState<'session' | 'project' | 'all'>('session');
  const [scopeValue, setScopeValue] = useState('');
  const [confirmAll, setConfirmAll] = useState(false);
  const [now, setNow] = useState(Date.now());
  const completedJobId = useRef<string | null>(null);

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
    if (!open) {
      setScope('session');
      setScopeValue('');
      setConfirmAll(false);
    }
  }, [open]);

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
    : jobStatus?.error_code || 'The build stopped before it could finish. Try the build again.';

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
        {!jobId ? (
          <div className="py-4 flex flex-col gap-4">
            <p className="text-sm text-muted-foreground">
              Extract entities and relationships from unstructured memories. Pick exactly one scope.
              This requires processing time against the LLM backend.
            </p>
            <div className="space-y-2">
              <Label className="text-xs">Scope</Label>
              <Select value={scope} onValueChange={(v: any) => { setScope(v); setScopeValue(''); setConfirmAll(false); }}>
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
                <div
                  className="h-2 overflow-hidden rounded-full bg-muted"
                  role="progressbar"
                  aria-label="Concept build progress"
                  aria-valuemin={0}
                  aria-valuemax={memoriesTotal || undefined}
                  aria-valuenow={memoriesTotal ? memoriesProcessed : undefined}
                >
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
            {jobStatus?.status === 'error' && (
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
            <Button
              className="w-full mt-4"
              variant="outline"
              onClick={() => handleDialogOpenChange(false)}
            >
              {isRunning ? 'Run in Background' : 'Close'}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function DuplicatesTab() {
  const { data, isLoading } = useConceptDuplicates();

  return (
    <div className="h-full flex flex-col pb-4">
      <Card className="flex-1 flex flex-col overflow-hidden">
        <CardHeader>
          <CardTitle>Duplicate Candidates</CardTitle>
          <CardDescription>Review potential concept duplicates based on similarity. (Read-only)</CardDescription>
        </CardHeader>
        <CardContent className="flex-1 overflow-auto p-0">
          <Table>
            <TableHeader className="sticky top-0 bg-muted/80 backdrop-blur">
              <TableRow>
                <TableHead>Entity A</TableHead>
                <TableHead>Entity B</TableHead>
                <TableHead className="text-right">Similarity</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow><TableCell colSpan={3} className="text-center text-muted-foreground h-24">Loading duplicates...</TableCell></TableRow>
              ) : data?.length === 0 ? (
                <TableRow><TableCell colSpan={3} className="text-center text-muted-foreground h-24">No duplicate candidates found.</TableCell></TableRow>
              ) : (
                data?.map((dup, i) => (
                  <TableRow key={i}>
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
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
