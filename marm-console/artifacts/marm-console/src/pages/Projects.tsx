import { useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { queryKeys, useProjects, useIndexProject, useIndexJob, useDeleteProject, useSearchProjectCode, useTraceProject, useProjectImpact, useProjectArchitecture, useProjectCodeUnits, useProjectCoverage, useProjectAdr, useUpdateProjectAdr, useIngestProjectRuntimeTraces, useMarmConfig } from '@/hooks/use-marm-queries';
import { Card, CardContent, CardHeader, CardTitle, CardDescription, Badge, Button, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, Input, Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Tabs, TabsList, TabsTrigger, TabsContent, Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from '@/components/ui/core';
import { Activity, BookOpen, CheckCircle2, CircleAlert, Clock3, FileWarning, FolderCode, HardDrive, Network, Play, RefreshCw, Save, Search, SearchCode, Trash2, Upload, XCircle } from 'lucide-react';
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
    <section id="index-workspace" className="project-index-workspace grid gap-5 rounded-2xl border border-primary/20 bg-card/80 p-5 shadow-[0_18px_50px_-30px_hsl(var(--primary)/0.7)] lg:grid-cols-[minmax(0,1fr)_19rem]">
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

export function ExploreDialog({ project, open, onOpenChange }: { project: ProjectSummary | null, open: boolean, onOpenChange: (o: boolean) => void }) {
  const [activeTab, setActiveTab] = useState('search');
  const searchCode = useSearchProjectCode();
  const traceCode = useTraceProject();
  const impactCode = useProjectImpact();
  const updateAdr = useUpdateProjectAdr();
  const ingestRuntimeTraces = useIngestProjectRuntimeTraces();
  const { data: architecture, isLoading: architectureLoading, isError: architectureFailed } = useProjectArchitecture(project?.name || '');
  const { data: codeUnits, isLoading: codeUnitsLoading, isError: codeUnitsFailed } = useProjectCodeUnits(project?.name || '');
  const { data: coverage, isLoading: coverageLoading, isError: coverageFailed } = useProjectCoverage(project?.name || '');
  const { data: adr, isLoading: adrLoading } = useProjectAdr(project?.name || '');
  // A failed refetch keeps the last successful data, so isError and state 'ready'
  // are both true at once. The failure wins: a populated table under "could not
  // reach the server" is exactly the ambiguous state this table exists to remove.
  const codeUnitsState = codeUnitsFailed ? 'failed' : codeUnits?.state;

  // Search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchKind, setSearchKind] = useState<CodeSearchKind>('auto');

  // Trace
  const [traceSymbol, setTraceSymbol] = useState('');
  const [traceDir, setTraceDir] = useState<TraceDirection>('both');
  const [traceMode, setTraceMode] = useState<TraceMode>('calls');

  // Impact
  const [impactBranch, setImpactBranch] = useState('main');
  const [adrDraft, setAdrDraft] = useState('');
  const [runtimeCaller, setRuntimeCaller] = useState('');
  const [runtimeCallee, setRuntimeCallee] = useState('');
  const [runtimeCount, setRuntimeCount] = useState('1');

  useEffect(() => setAdrDraft(''), [project?.name]);

  useEffect(() => {
    searchCode.reset();
    traceCode.reset();
    impactCode.reset();
    updateAdr.reset();
    ingestRuntimeTraces.reset();
  }, [project?.name]);

  useEffect(() => {
    if (typeof adr?.content === 'string') setAdrDraft(adr.content);
  }, [adr?.content]);

  useEffect(() => setActiveTab('search'), [project?.name]);

  const parsedRuntimeCount = Number(runtimeCount);
  const runtimeCountValid = /^\d+$/.test(runtimeCount.trim())
    && Number.isInteger(parsedRuntimeCount)
    && parsedRuntimeCount >= 1
    && parsedRuntimeCount <= 1_000_000;

  if (!project) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="project-explorer-dialog !flex !flex-col h-[42rem] max-h-[85vh] max-w-5xl !gap-0 overflow-hidden !p-0">
        <DialogHeader className="project-explorer-header shrink-0 px-6 pb-5 pt-6">
          <div className="flex min-w-0 items-start gap-3 pr-8">
            <div className="project-explorer-mark"><Network className="h-4 w-4" /></div>
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">Code graph explorer</p>
              <DialogTitle className="mt-1 truncate text-lg">{project.name}</DialogTitle>
              <DialogDescription className="mt-1 truncate font-mono text-xs" title={project.root_path}>{project.root_path}</DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex min-h-0 flex-1 flex-col overflow-hidden px-6 pb-6">
          <TabsList className="project-explorer-tabs grid h-auto w-full shrink-0 grid-cols-2 gap-1.5 rounded-xl border border-border/70 bg-muted/20 p-1.5 sm:grid-cols-4">
            <TabsTrigger value="architecture" className="project-explorer-tab"><Network className="h-3.5 w-3.5" /><span>Architecture</span></TabsTrigger>
            <TabsTrigger value="search" className="project-explorer-tab"><SearchCode className="h-3.5 w-3.5" /><span>Code search</span></TabsTrigger>
            <TabsTrigger value="trace" className="project-explorer-tab"><Activity className="h-3.5 w-3.5" /><span>Trace symbol</span></TabsTrigger>
            <TabsTrigger value="impact" className="project-explorer-tab"><CircleAlert className="h-3.5 w-3.5" /><span>Impact</span></TabsTrigger>
            <TabsTrigger value="coverage" className="project-explorer-tab"><FileWarning className="h-3.5 w-3.5" /><span>Coverage</span></TabsTrigger>
            <TabsTrigger value="investigate" className="project-explorer-tab"><SearchCode className="h-3.5 w-3.5" /><span>Investigate</span></TabsTrigger>
            <TabsTrigger value="adr" className="project-explorer-tab"><BookOpen className="h-3.5 w-3.5" /><span>Decisions</span></TabsTrigger>
            <TabsTrigger value="runtime" className="project-explorer-tab"><Upload className="h-3.5 w-3.5" /><span>Runtime traces</span></TabsTrigger>
          </TabsList>

          <TabsContent value="architecture" className="project-explorer-panel mt-0 min-h-0 flex-1 overflow-y-auto pt-5">
            {architectureLoading ? (
              <div className="p-8 text-center text-sm text-muted-foreground">Loading architecture...</div>
            ) : architectureFailed ? (
              <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-7 text-sm text-muted-foreground"><p className="font-medium text-foreground">Architecture is unavailable</p><p className="mt-1">The index still exists, but the graph backend could not provide its architecture summary. Open Knowledge → Code Explorer after the backend is available.</p></div>
            ) : project.nodes === 0 ? (
              <div className="rounded-xl border border-dashed p-7 text-sm text-muted-foreground"><p className="font-medium text-foreground">This repository has no indexed graph nodes yet.</p><p className="mt-1">Run indexing again after selecting the repository path to populate its code structure.</p></div>
            ) : architecture?.state === 'indexed_no_summary' ? (
              <div className="rounded-xl border border-dashed p-7 text-sm text-muted-foreground"><p className="font-medium text-foreground">Index exists, but its architecture summary is sparse.</p><p className="mt-1">Knowledge → Code Explorer can still show the proven file/import topology. The index currently records {project.nodes.toLocaleString()} nodes and {project.edges.toLocaleString()} relationships.</p></div>
            ) : (
              <div className="space-y-5">
                <div className="grid grid-cols-2 gap-4">
                  <div className="border rounded-md p-4">
                    <p className="text-xs text-muted-foreground uppercase tracking-wider">Node types</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {architecture?.schema.node_types.map((type) => <Badge key={type.name} variant="secondary">{type.name}{type.count !== undefined && <span className="ml-1.5 opacity-60 font-mono">{type.count.toLocaleString()}</span>}</Badge>)}
                    </div>
                  </div>
                  <div className="border rounded-md p-4">
                    <p className="text-xs text-muted-foreground uppercase tracking-wider">Edge types</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {architecture?.schema.edge_types.map((type) => <Badge key={type.name} variant="outline">{type.name}{type.count !== undefined && <span className="ml-1.5 opacity-60 font-mono">{type.count.toLocaleString()}</span>}</Badge>)}
                    </div>
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="flex items-baseline justify-between">
                    <p className="text-xs text-muted-foreground uppercase tracking-wider">Code structure</p>
                    {codeUnits && codeUnitsState === 'ready' && (
                      <p className="text-xs text-muted-foreground">
                        {codeUnits.sampled
                          ? `Showing ${codeUnits.shown} of ${codeUnits.total} ranked candidates, most connected first`
                          : codeUnits.shown < codeUnits.total
                            ? `Showing ${codeUnits.shown} of ${codeUnits.total} files, most connected first`
                            : `${codeUnits.total} files, most connected first`}
                      </p>
                    )}
                  </div>
                  <div className="border rounded-md overflow-hidden">
                    <Table>
                      <TableHeader className="bg-muted/80"><TableRow><TableHead>File</TableHead><TableHead className="text-right">Imported by</TableHead><TableHead className="text-right">Imports</TableHead></TableRow></TableHeader>
                      <TableBody>
                        {codeUnitsLoading && <TableRow><TableCell colSpan={3} className="h-24 text-center text-muted-foreground">Loading code structure...</TableCell></TableRow>}
                        {!codeUnitsLoading && codeUnitsState === 'failed' && <TableRow><TableCell colSpan={3} className="h-24 text-center text-muted-foreground">Could not reach the server to read code structure.</TableCell></TableRow>}
                        {!codeUnitsLoading && codeUnitsState === 'empty_index' && <TableRow><TableCell colSpan={3} className="h-24 text-center text-muted-foreground">Nothing indexed yet. Index this project to see its structure.</TableCell></TableRow>}
                        {!codeUnitsLoading && codeUnitsState === 'indexed_no_summary' && <TableRow><TableCell colSpan={3} className="h-24 text-center text-muted-foreground">Indexed, but everything here looks like docs or config rather than code.</TableCell></TableRow>}
                        {!codeUnitsLoading && codeUnits && codeUnitsState === 'unavailable' && <TableRow><TableCell colSpan={3} className="h-24 text-center text-muted-foreground">{codeUnits.reason === 'graph_unavailable' ? 'The code graph is not running, so structure cannot be read.' : 'Code structure is unavailable right now.'}</TableCell></TableRow>}
                        {!codeUnitsLoading && codeUnits && codeUnitsState === 'ready' && codeUnits.code_units.map((unit) => <TableRow key={unit.unit}><TableCell className="font-mono text-xs">{unit.unit}</TableCell><TableCell className="text-right">{unit.fan_in}</TableCell><TableCell className="text-right">{unit.fan_out}</TableCell></TableRow>)}
                      </TableBody>
                    </Table>
                  </div>
                  {codeUnits && codeUnitsState === 'ready' && codeUnits.fan_in_is_lower_bound && (
                    <p className="text-xs text-muted-foreground">
                      "Imported by" counts files that import this one directly. Package-level imports are not attributed to the file they resolve to, so treat it as a minimum.
                    </p>
                  )}
                </div>
              </div>
            )}
          </TabsContent>

          <TabsContent value="search" className="project-explorer-panel mt-0 flex min-h-0 flex-1 flex-col gap-4 overflow-hidden pt-5">
            <div className="flex gap-2">
              <Input 
                placeholder="Search query..." 
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && searchQuery && searchCode.mutate({ project: project.name, data: { query: searchQuery, kind: searchKind } })}
              />
              <Select value={searchKind} onValueChange={(v: CodeSearchKind) => setSearchKind(v)}>
                <SelectTrigger className="w-[150px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Auto</SelectItem>
                  <SelectItem value="symbol">Symbol</SelectItem>
                  <SelectItem value="text">Text</SelectItem>
                  <SelectItem value="snippet">Snippet</SelectItem>
                </SelectContent>
              </Select>
              <Button 
                onClick={() => searchCode.mutate({ project: project.name, data: { query: searchQuery, kind: searchKind } })}
                disabled={!searchQuery}
                isLoading={searchCode.isPending}
              >
                <Search className="w-4 h-4" />
              </Button>
            </div>
            {searchCode.error && (
              <p className="text-xs text-destructive p-2 bg-destructive/10 rounded">{searchCode.error.message}</p>
            )}

            <div className="flex-1 overflow-auto border rounded-md">
              <Table>
                <TableHeader className="sticky top-0 bg-muted/80 backdrop-blur">
                  <TableRow>
                    <TableHead>Symbol / File</TableHead>
                    <TableHead>Kind</TableHead>
                    <TableHead>Preview</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {searchCode.data?.length === 0 && (
                    <TableRow><TableCell colSpan={3} className="text-center text-muted-foreground h-24">No results found.</TableCell></TableRow>
                  )}
                  {searchCode.data?.map((res, i) => (
                    <TableRow key={i}>
                      <TableCell>
                        <div className="font-mono text-sm">{res.qualified_name}</div>
                        <div className="text-xs text-muted-foreground">{res.file_path}{res.line ? `:${res.line}` : ''}</div>
                      </TableCell>
                      <TableCell><Badge variant="outline" className="text-[10px]">{res.kind}</Badge></TableCell>
                      <TableCell className="font-mono text-xs whitespace-pre-wrap max-w-xs">{res.snippet}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </TabsContent>
          
          <TabsContent value="trace" className="project-explorer-panel mt-0 flex min-h-0 flex-1 flex-col gap-4 overflow-hidden pt-5">
            <div className="flex gap-2">
              <Input 
                placeholder="Symbol name..." 
                value={traceSymbol}
                onChange={e => setTraceSymbol(e.target.value)}
              />
              <Select value={traceDir} onValueChange={(v: any) => setTraceDir(v)}>
                <SelectTrigger className="w-[130px]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="both">Both Ways</SelectItem>
                  <SelectItem value="inbound">Inbound</SelectItem>
                  <SelectItem value="outbound">Outbound</SelectItem>
                </SelectContent>
              </Select>
              <Select value={traceMode} onValueChange={(v: any) => setTraceMode(v)}>
                <SelectTrigger className="w-[130px]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="calls">Calls</SelectItem>
                  <SelectItem value="data_flow">Data Flow</SelectItem>
                  <SelectItem value="cross_service">Cross Service</SelectItem>
                </SelectContent>
              </Select>
              <Button 
                onClick={() => traceCode.mutate({ project: project.name, data: { symbol: traceSymbol, direction: traceDir, mode: traceMode } })}
                disabled={!traceSymbol}
                isLoading={traceCode.isPending}
              >
                Trace
              </Button>
            </div>
            {traceCode.error && (
              <p className="text-xs text-destructive p-2 bg-destructive/10 rounded">{traceCode.error.message}</p>
            )}

            <div className="flex-1 overflow-auto border rounded-md">
              <Table>
                <TableHeader className="sticky top-0 bg-muted/80 backdrop-blur">
                  <TableRow>
                    <TableHead>Relation</TableHead>
                    <TableHead>Symbol</TableHead>
                    <TableHead>File</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {traceCode.data?.steps.length === 0 && (
                    <TableRow><TableCell colSpan={3} className="text-center text-muted-foreground h-24">No traces found.</TableCell></TableRow>
                  )}
                  {traceCode.data?.steps.map((step, i) => (
                    <TableRow key={i}>
                      <TableCell><Badge variant="outline" className="text-[10px]">{step.relation}</Badge></TableCell>
                      <TableCell className="font-mono text-sm">{step.qualified_name}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{step.file_path}</TableCell>
                    </TableRow>
                  ))}
                  {traceCode.data?.truncated && (
                    <TableRow><TableCell colSpan={3} className="text-center text-amber-500 text-xs py-2 bg-amber-500/10">Results truncated</TableCell></TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          </TabsContent>

          <TabsContent value="impact" className="project-explorer-panel mt-0 flex min-h-0 flex-1 flex-col gap-4 overflow-hidden pt-5">
             <div className="flex gap-2">
              <Input 
                placeholder="Base branch (e.g. main)" 
                value={impactBranch}
                onChange={e => setImpactBranch(e.target.value)}
              />
              <Button 
                onClick={() => impactCode.mutate({ project: project.name, data: { base_branch: impactBranch } })}
                disabled={!impactBranch}
                isLoading={impactCode.isPending}
              >
                Analyze
              </Button>
            </div>
            {impactCode.error && (
              <p className="text-xs text-destructive p-2 bg-destructive/10 rounded">{impactCode.error.message}</p>
            )}

            <div className="flex-1 overflow-auto border rounded-md">
              <Table>
                <TableHeader className="sticky top-0 bg-muted/80 backdrop-blur">
                  <TableRow>
                    <TableHead>Risk</TableHead>
                    <TableHead>Affected Symbol</TableHead>
                    <TableHead>File</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {impactCode.data?.affected_symbols.length === 0 && (
                    <TableRow><TableCell colSpan={3} className="text-center text-muted-foreground h-24">No impact detected.</TableCell></TableRow>
                  )}
                  {impactCode.data?.affected_symbols.map((sym, i) => (
                    <TableRow key={i}>
                      <TableCell>
                        <Badge variant={sym.risk === 'high' ? 'destructive' : sym.risk === 'medium' ? 'secondary' : 'outline'} className="text-[10px] uppercase">
                          {sym.risk}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono text-sm">{sym.qualified_name}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{sym.file_path}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </TabsContent>

          <TabsContent value="coverage" className="project-explorer-panel mt-0 min-h-0 flex-1 overflow-y-auto pt-5">
            {coverageLoading ? <div className="p-8 text-center text-sm text-muted-foreground">Reading recorded coverage…</div> : coverageFailed ? <div className="rounded-lg bg-destructive/10 p-4 text-sm text-destructive">Coverage is unavailable right now.</div> : (
              <div className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-lg border bg-muted/20 p-3"><p className="text-xs text-muted-foreground">Signal</p><p className="mt-1 text-sm font-semibold">Best effort</p></div>
                  <div className="rounded-lg border bg-muted/20 p-3"><p className="text-xs text-muted-foreground">Index mode</p><p className="mt-1 text-sm font-semibold capitalize">{coverage?.metadata?.index_mode || 'Unknown'}</p></div>
                  <div className="rounded-lg border bg-muted/20 p-3"><p className="text-xs text-muted-foreground">Metadata</p><p className="mt-1 text-sm font-semibold">{coverage?.metadata?.generation_matches ? 'Current' : 'Check freshness'}</p></div>
                </div>
                <div className="rounded-lg border overflow-hidden">
                  <div className="border-b bg-muted/40 px-4 py-3"><p className="text-sm font-semibold">Recorded exclusions and gaps</p><p className="mt-0.5 text-xs text-muted-foreground">These are detected signals, not proof that unlisted source is complete.</p></div>
                  {(coverage?.scopes[0]?.entries.length ?? 0) === 0 ? <p className="p-5 text-sm text-muted-foreground">No recorded gaps in this scope.</p> : <div className="divide-y">{coverage?.scopes[0]?.entries.map((entry) => <div key={`${entry.kind}-${entry.path}`} className="flex items-start gap-3 px-4 py-3"><FileWarning className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" /><div><p className="font-mono text-xs">{entry.path}</p><p className="mt-0.5 text-xs text-muted-foreground">{entry.kind}{entry.detail ? ` · ${entry.detail}` : ''}</p></div></div>)}</div>}
                </div>
                {coverage?.caveat && <p className="text-xs text-muted-foreground">{coverage.caveat}</p>}
              </div>
            )}
          </TabsContent>

          <TabsContent value="investigate" className="project-explorer-panel mt-0 min-h-0 flex-1 overflow-y-auto pt-5">
            <div className="grid gap-3 sm:grid-cols-2">
              {[
                { title: 'Find a symbol', detail: 'Search names, code, or snippets within this indexed repository.', tab: 'search' },
                { title: 'Trace callers and dependencies', detail: 'Follow a qualified symbol through bounded call or data-flow paths.', tab: 'trace' },
                { title: 'Review architecture and structure', detail: 'Inspect indexed node types, relationships, and connected source files.', tab: 'architecture' },
                { title: 'Estimate change impact', detail: 'Compare a branch or revision to identify affected symbols.', tab: 'impact' },
                { title: 'Check indexed coverage', detail: 'Review recorded exclusions and freshness signals.', tab: 'coverage' },
                { title: 'Add runtime evidence', detail: 'Record observed caller → callee frequency alongside static structure.', tab: 'runtime' },
              ].map((item) => <button key={item.tab} type="button" onClick={() => setActiveTab(item.tab)} className="rounded-xl border border-border/70 bg-muted/20 p-4 text-left transition-colors hover:border-primary/40 hover:bg-primary/5"><p className="text-sm font-semibold">{item.title}</p><p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{item.detail}</p><span className="mt-3 inline-block text-xs font-medium text-primary">Open tool →</span></button>)}
            </div>
          </TabsContent>

          <TabsContent value="adr" className="project-explorer-panel mt-0 min-h-0 flex-1 overflow-y-auto pt-5">
            <div className="space-y-3">
              <div><p className="text-sm font-semibold">Architecture decisions</p><p className="mt-1 text-xs text-muted-foreground">This is the project’s engine-backed ADR document. Saving replaces the current document.</p></div>
              {adrLoading ? <p className="text-sm text-muted-foreground">Loading decisions…</p> : <textarea value={adrDraft} onChange={event => setAdrDraft(event.target.value)} placeholder="# Architecture decisions" className="min-h-64 w-full rounded-md border bg-background p-3 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring" />}
              {updateAdr.error && <p className="rounded-lg bg-destructive/10 p-3 text-xs text-destructive">{updateAdr.error.message}</p>}
              <Button onClick={() => updateAdr.mutate({ project: project.name, content: adrDraft })} disabled={adrLoading || !adrDraft.trim()} isLoading={updateAdr.isPending}><Save className="mr-2 h-4 w-4" /> Save decisions</Button>
            </div>
          </TabsContent>

          <TabsContent value="runtime" className="project-explorer-panel mt-0 min-h-0 flex-1 overflow-y-auto pt-5">
            <div className="space-y-4">
              <div><p className="text-sm font-semibold">Runtime trace edge</p><p className="mt-1 text-xs text-muted-foreground">Add observed caller → callee frequency to supplement static structure. Use qualified names from this project.</p></div>
              <div className="grid gap-3 sm:grid-cols-[1fr_1fr_7rem]">
                <Input value={runtimeCaller} onChange={event => setRuntimeCaller(event.target.value)} placeholder="caller.qualified_name" className="font-mono text-xs" />
                <Input value={runtimeCallee} onChange={event => setRuntimeCallee(event.target.value)} placeholder="callee.qualified_name" className="font-mono text-xs" />
                <Input value={runtimeCount} onChange={event => setRuntimeCount(event.target.value)} inputMode="numeric" placeholder="Count" />
              </div>
              {!runtimeCountValid && <p className="text-xs text-destructive">Count must be a whole number from 1 to 1,000,000.</p>}
              {ingestRuntimeTraces.error && <p className="rounded-lg bg-destructive/10 p-3 text-xs text-destructive">{ingestRuntimeTraces.error.message}</p>}
              {ingestRuntimeTraces.data?.status === 'success' && <p className="rounded-lg bg-emerald-500/10 p-3 text-xs text-emerald-300">Runtime edge added to the graph.</p>}
              <Button onClick={() => ingestRuntimeTraces.mutate({ project: project.name, traces: [{ caller: runtimeCaller, callee: runtimeCallee, count: parsedRuntimeCount } satisfies RuntimeTrace] })} disabled={!runtimeCaller.trim() || !runtimeCallee.trim() || !runtimeCountValid} isLoading={ingestRuntimeTraces.isPending}><Upload className="mr-2 h-4 w-4" /> Ingest trace</Button>
            </div>
          </TabsContent>
        </Tabs>
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
  const [exploreTarget, setExploreTarget] = useState<ProjectSummary | null>(null);
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
        {[
          { label: 'Indexed repositories', value: metrics.repositories, icon: FolderCode, tone: 'text-primary' },
          { label: 'Graph nodes', value: metrics.nodes.toLocaleString(), icon: HardDrive, tone: 'text-cyan-400' },
          { label: 'Graph edges', value: metrics.edges.toLocaleString(), icon: Network, tone: 'text-violet-400' },
          { label: 'Needs attention', value: metrics.attention, icon: CircleAlert, tone: metrics.attention ? 'text-amber-400' : 'text-emerald-400' },
        ].map((metric, index) => <Card key={metric.label} className="metric-enter overflow-hidden border-border/70" style={{ animationDelay: `${index * 55}ms` }}><CardContent className="relative p-4"><metric.icon className={`absolute right-4 top-4 h-5 w-5 ${metric.tone}`} /><p className="text-xs text-muted-foreground">{metric.label}</p><p className="mt-2 text-2xl font-semibold tracking-tight">{metric.value}</p></CardContent></Card>)}
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
          return <Card key={proj.name} className="project-card group metric-enter overflow-hidden border-border/70" style={{ animationDelay: `${index * 45}ms` }}><CardHeader className="flex flex-row items-start justify-between gap-4 pb-3"><div className="min-w-0"><div className="flex items-center gap-2"><CardTitle className="truncate font-mono text-base">{proj.name}</CardTitle><Badge variant="outline" className={`shrink-0 border text-[10px] capitalize ${statusTone}`}>{status === 'indexing' && <RefreshCw className="mr-1 h-3 w-3 animate-spin" />}{status}</Badge></div><CardDescription className="mt-2 truncate font-mono text-xs" title={proj.root_path}>{proj.root_path}</CardDescription></div><div className="flex shrink-0 gap-1"><Button variant="outline" size="sm" onClick={() => setExploreTarget(proj)}>Explore</Button><Button variant="ghost" size="icon" title="Prepare reindex" onClick={() => prepareReindex(proj)}><RefreshCw className="h-4 w-4" /></Button><Button variant="ghost" size="icon" className="text-muted-foreground hover:text-destructive" title="Delete project graph" onClick={() => setDeleteTarget(proj)}><Trash2 className="h-4 w-4" /></Button></div></CardHeader><CardContent><div className="grid grid-cols-2 gap-3"><div className="rounded-lg border border-border/60 bg-muted/20 p-3"><p className="text-xs text-muted-foreground">Nodes</p><p className="mt-1 font-mono text-xl font-semibold">{proj.nodes.toLocaleString()}</p><p className="mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">Files & symbols</p></div><div className="rounded-lg border border-border/60 bg-muted/20 p-3"><p className="text-xs text-muted-foreground">Edges</p><p className="mt-1 font-mono text-xl font-semibold">{proj.edges.toLocaleString()}</p><p className="mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">Calls & imports</p></div></div></CardContent></Card>;
        })}</div>}
      </section>

      <DeleteDialog project={deleteTarget} open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)} />
      <ExploreDialog project={exploreTarget} open={!!exploreTarget} onOpenChange={(o) => !o && setExploreTarget(null)} />
    </div>
  );
}
