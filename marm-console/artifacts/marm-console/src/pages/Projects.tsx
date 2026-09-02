import { useEffect, useMemo, useState } from 'react';
import { Link } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';
import { queryKeys, useProjects, useIndexProject, useIndexJob, useDeleteProject, useSearchProjectCode, useTraceProject, useProjectImpact, useProjectArchitecture, useProjectCodeUnits, useProjectCoverage, useProjectAdr, useUpdateProjectAdr, useIngestProjectRuntimeTraces, useMarmConfig } from '@/hooks/use-marm-queries';
import { Card, CardContent, CardHeader, CardTitle, CardDescription, Badge, Button, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, Input, Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Tabs, TabsList, TabsTrigger, TabsContent, Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from '@/components/ui/core';
import { Panel, SmallStat, StatCard } from '@/components/ui/panels';
import { CheckCircle2, CircleAlert, Clock3, Compass, FolderCode, HardDrive, Network, Play, RefreshCw, SearchCode, Trash2, XCircle } from 'lucide-react';
import type { IndexMode, ProjectSummary, CodeSearchKind, RuntimeTrace, TraceDirection, TraceMode } from '@/lib/marm-types';

const INDEX_MODES: Array<{ value: IndexMode; label: string; description: string }> = [
  { value: 'fast', label: 'Fast', description: 'Signatures and imports' },
  { value: 'moderate', label: 'Moderate', description: 'Includes types' },
  { value: 'full', label: 'Full', description: 'Deep body analysis' },
];

function formatElapsed(timestamp: string | null | undefined) {
  if (!timestamp) return 'Starting…';
  const elapsed = Math.max(0, Math.floor((Date.now() - new Date(timestamp).getTime()) / 1000));
  return elapsed < 60 ? `${elapsed}s elapsed` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s elapsed`;
}

function IndexWorkspace({ repoPath, setRepoPath, mode, setMode, jobId, setJobId }: {
  repoPath: string;
  setRepoPath: (value: string) => void;
  mode: IndexMode;
  setMode: (value: IndexMode) => void;
  jobId: string | null;
  setJobId: (value: string | null) => void;
}) {
  const indexProj = useIndexProject();
  const { data: jobStatus, error: jobError, isError: jobFailed, refetch: refetchJob } = useIndexJob(jobId || '');
  const { baseUrl } = useMarmConfig();
  const queryClient = useQueryClient();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!repoPath) return;
    indexProj.mutate(
      { repo_path: repoPath, mode },
      { onSuccess: (res) => setJobId(res.job_id) }
    );
  };

  const isSettled = !!jobStatus && jobStatus.status !== 'queued' && jobStatus.status !== 'running';
  const isRunning = !!jobId && !isSettled && !jobFailed;

  useEffect(() => {
    if (jobStatus && jobStatus.status !== 'queued' && jobStatus.status !== 'running') {
      queryClient.invalidateQueries({ queryKey: ['projects', baseUrl] });
      if (jobStatus.project) {
        queryClient.invalidateQueries({ queryKey: ['projectGraph', baseUrl, jobStatus.project] });
        queryClient.invalidateQueries({ queryKey: ['projectGraphNeighborhood', baseUrl, jobStatus.project] });
        queryClient.invalidateQueries({ queryKey: queryKeys.projectArchitecture(baseUrl, jobStatus.project) });
        queryClient.invalidateQueries({ queryKey: queryKeys.projectCodeUnits(baseUrl, jobStatus.project) });
      }
    }
  }, [baseUrl, jobStatus?.project, jobStatus?.status, queryClient]);

  return (
    <section id="index-workspace" className="project-index-workspace grid gap-5 rounded-2xl border border-primary/20 bg-card/80 p-5 shadow-[0_18px_50px_-30px_rgba(var(--primary-rgb),0.7)] lg:grid-cols-[minmax(0,1fr)_19rem]">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold"><FolderCode className="h-4 w-4 text-primary" /> Index a repository</h2>
          <p className="text-sm text-muted-foreground">Build a local structural graph for code search, tracing, impact, and architecture review.</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="repository-path">Repository path</Label>
          <Input id="repository-path" placeholder="C:\\work\\my-app" value={repoPath} onChange={e => setRepoPath(e.target.value)} required className="font-mono text-xs" disabled={isRunning} />
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          {INDEX_MODES.map((option) => (
            <button key={option.value} type="button" onClick={() => setMode(option.value)} disabled={isRunning} className={`rounded-xl border p-3 text-left transition-all ${mode === option.value ? 'border-primary bg-primary/10 shadow-sm' : 'border-border bg-background/40 hover:border-primary/35 hover:bg-muted/50'}`}>
              <span className="block text-sm font-semibold">{option.label}</span>
              <span className="mt-1 block text-xs leading-snug text-muted-foreground">{option.description}</span>
            </button>
          ))}
        </div>
        {indexProj.error && <p className="rounded-lg bg-destructive/10 p-3 text-xs text-destructive">{indexProj.error.message}</p>}
        <Button type="submit" className="min-w-40" isLoading={indexProj.isPending} disabled={isRunning || !repoPath.trim()}><Play className="mr-2 h-4 w-4" /> Start {mode} index</Button>
      </form>

      <div className={`rounded-xl border p-4 ${isRunning ? 'border-primary/35 bg-primary/[0.06] status-pulse' : jobStatus?.status === 'success' ? 'border-emerald-500/30 bg-emerald-500/[0.06] success-pop' : jobStatus?.status === 'error' || jobFailed ? 'border-destructive/35 bg-destructive/[0.06]' : 'border-border bg-background/40'}`}>
        {jobId ? (
          <div className="flex h-full flex-col">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{isRunning ? 'Live index' : 'Latest index'}</p>
                <p className="mt-1 font-semibold capitalize">{jobFailed ? 'Status unavailable' : jobStatus?.status || 'Preparing job'}</p>
              </div>
              {isRunning ? <RefreshCw className="h-5 w-5 animate-spin text-primary" /> : jobStatus?.status === 'success' ? <CheckCircle2 className="h-5 w-5 text-emerald-400" /> : <XCircle className="h-5 w-5 text-destructive" />}
            </div>
            <div className="mt-5 space-y-2 text-sm">
              <p className="font-mono text-xs text-muted-foreground">{jobStatus?.phase || 'Queued'}</p>
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><Clock3 className="h-3.5 w-3.5" /> {formatElapsed(jobStatus?.started_at || jobStatus?.created_at)}</p>
              {jobStatus?.project && <p className="truncate font-mono text-xs text-muted-foreground" title={jobStatus.project}>{jobStatus.project}</p>}
              {jobStatus?.error && <p className="rounded-md bg-destructive/10 p-2 text-xs text-destructive">{jobStatus.error}</p>}
              {jobFailed && <p className="rounded-md bg-destructive/10 p-2 text-xs text-destructive">{jobError instanceof Error ? jobError.message : 'Could not read the indexing status.'}</p>}
            </div>
            {jobFailed ? <div className="mt-auto flex gap-2"><Button variant="outline" size="sm" onClick={() => refetchJob()}>Retry status</Button><Button variant="ghost" size="sm" onClick={() => setJobId(null)}>Clear status</Button></div> : isSettled && <Button variant="ghost" size="sm" className="mt-auto self-start" onClick={() => setJobId(null)}>Clear status</Button>}
          </div>
        ) : (
          <div className="flex h-full flex-col justify-between">
            <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">Ready to build</p><p className="mt-2 text-sm text-muted-foreground">Choose a depth, enter an absolute local path, and keep working while the graph builds.</p></div>
            <p className="mt-5 text-xs text-muted-foreground">Indexing never changes your source files.</p>
          </div>
        )}
      </div>
    </section>
  );
}

function DeleteDialog({ project, open, onOpenChange }: { project: ProjectSummary | null, open: boolean, onOpenChange: (o: boolean) => void }) {
  const [confirmName, setConfirmName] = useState('');
  const deleteProj = useDeleteProject();

  if (!project) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="text-destructive">Delete Project Graph</DialogTitle>
          <DialogDescription>
            This removes the AST index for <strong>{project.name}</strong> from MARM. Your local files are untouched.
          </DialogDescription>
        </DialogHeader>
        <div className="py-4 space-y-4">
          <Label className="text-sm">Type the project name to confirm:</Label>
          <Input 
            value={confirmName} 
            onChange={e => setConfirmName(e.target.value)} 
            placeholder={project.name}
            className="font-mono border-destructive/50 focus-visible:ring-destructive"
          />
        </div>
        {deleteProj.error && (
          <p className="text-xs text-destructive p-2 bg-destructive/10 rounded">{deleteProj.error.message}</p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            variant="destructive"
            disabled={confirmName !== project.name}
            isLoading={deleteProj.isPending}
            onClick={() => {
              deleteProj.mutate({ project: project.name, name: project.name }, {
                onSuccess: () => onOpenChange(false)
              });
            }}
          >
            Delete Permanently
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ProjectsPage() {
  const { data: projects, isLoading } = useProjects();
  const [repoPath, setRepoPath] = useState('');
  const [mode, setMode] = useState<IndexMode>('moderate');
  const [jobId, setJobId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ProjectSummary | null>(null);
  const metrics = useMemo(() => {
    const rows = projects || [];
    return {
      repositories: rows.length,
      nodes: rows.reduce((total, project) => total + (project.nodes || 0), 0),
      edges: rows.reduce((total, project) => total + (project.edges || 0), 0),
      attention: rows.filter((project) => project.status === 'error' || project.status === 'indexing').length,
    };
  }, [projects]);

  const prepareReindex = (project: ProjectSummary) => {
    setRepoPath(project.root_path);
    setMode('moderate');
    setJobId(null);
    document.getElementById('index-workspace')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    window.setTimeout(() => document.getElementById('repository-path')?.focus(), 350);
  };

  return (
    <div className="page-enter h-full overflow-auto p-7 xl:p-8">
      <div className="mb-6 flex items-center justify-between gap-5">
        <div>
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">Code intelligence</div>
          <h1 className="text-[1.8rem] font-semibold tracking-[-0.045em]">Indexed Projects</h1>
          <p className="mt-1 text-sm text-muted-foreground">Build, inspect, and evolve local code graphs from one workspace.</p>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {([
          { label: 'Indexed repositories', value: String(metrics.repositories), detail: metrics.repositories === 1 ? '1 workspace with a code graph' : `${metrics.repositories} workspaces with a code graph`, icon: <FolderCode className="h-5 w-5" />, tone: 'cyan' },
          { label: 'Graph nodes', value: metrics.nodes.toLocaleString(), detail: 'Files and symbols', icon: <HardDrive className="h-5 w-5" />, tone: 'teal' },
          { label: 'Graph edges', value: metrics.edges.toLocaleString(), detail: 'Calls and imports', icon: <Network className="h-5 w-5" />, tone: 'violet' },
          { label: 'Needs attention', value: String(metrics.attention), detail: metrics.attention ? 'Projects failed to index' : 'Every project indexed cleanly', icon: <CircleAlert className="h-5 w-5" />, tone: metrics.attention ? 'amber' : 'emerald' },
        ] as const).map((metric, index) => <StatCard key={metric.label} label={metric.label} value={metric.value} detail={metric.detail} icon={metric.icon} tone={metric.tone} delay={index * 55} />)}
      </div>

      <div className="mt-6">
        <IndexWorkspace repoPath={repoPath} setRepoPath={setRepoPath} mode={mode} setMode={setMode} jobId={jobId} setJobId={setJobId} />
      </div>

      <section className="mt-8 pb-8">
        <div className="mb-4 flex items-center justify-between"><div><h2 className="text-lg font-semibold">Projects</h2><p className="mt-0.5 text-sm text-muted-foreground">Open an explorer for the graph, coverage, decisions, and runtime evidence.</p></div><Badge variant="outline" className="font-mono text-[10px]">{metrics.repositories} total</Badge></div>
        {isLoading ? <div className="p-12 text-center text-muted-foreground">Loading projects…</div> : projects?.length === 0 ? (
          <div className="flex flex-col items-center rounded-xl border border-dashed p-12 text-center"><SearchCode className="mb-4 h-10 w-10 text-muted-foreground/60" /><h3 className="text-lg font-medium">Your first code graph starts here</h3><p className="mt-2 max-w-sm text-sm text-muted-foreground">Enter an absolute repository path above to give MARM structural awareness of a codebase.</p></div>
        ) : <div className="grid gap-4 xl:grid-cols-2">{projects?.map((proj, index) => {
          const status = proj.status || 'ready';
          const statusTone = status === 'ready' ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/25' : status === 'indexing' ? 'bg-primary/10 text-primary border-primary/25' : 'bg-destructive/10 text-destructive border-destructive/25';
          return <Card key={proj.name} className="project-card group metric-enter overflow-hidden border-border/70" style={{ animationDelay: `${index * 45}ms` }}><CardHeader className="flex flex-row items-start justify-between gap-4 pb-3"><div className="min-w-0"><div className="flex items-center gap-2"><CardTitle className="truncate font-mono text-base">{proj.name}</CardTitle><Badge variant="outline" className={`shrink-0 border text-[10px] capitalize ${statusTone}`}>{status === 'indexing' && <RefreshCw className="mr-1 h-3 w-3 animate-spin" />}{status}</Badge></div><CardDescription className="mt-2 truncate font-mono text-xs" title={proj.root_path}>{proj.root_path}</CardDescription></div><div className="flex shrink-0 items-center gap-1"><Link href={`/explorer/${encodeURIComponent(proj.name)}`}><Button variant="outline" size="sm"><Compass className="mr-1.5 h-3.5 w-3.5" />Open in explorer</Button></Link><Button variant="ghost" size="icon" title="Prepare reindex" onClick={() => prepareReindex(proj)}><RefreshCw className="h-4 w-4" /></Button><Button variant="ghost" size="icon" className="text-muted-foreground hover:text-destructive" title="Delete project graph" onClick={() => setDeleteTarget(proj)}><Trash2 className="h-4 w-4" /></Button></div></CardHeader><CardContent><div className="grid grid-cols-2 gap-3"><SmallStat label="Nodes" value={proj.nodes.toLocaleString()} caption="Files & symbols" /><SmallStat label="Edges" value={proj.edges.toLocaleString()} caption="Calls & imports" /></div></CardContent></Card>;
        })}</div>}
      </section>

      <DeleteDialog project={deleteTarget} open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)} />
    </div>
  );
}
