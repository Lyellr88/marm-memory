import { useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'wouter';
import { Activity, BookOpen, ChevronRight, CircleAlert, FileWarning, FolderCode, Network, Save, Search, SearchCode, Upload } from 'lucide-react';
import { useProjects, useSearchProjectCode, useTraceProject, useProjectImpact, useProjectArchitecture, useProjectCodeUnits, useProjectCoverage, useProjectAdr, useUpdateProjectAdr, useIngestProjectRuntimeTraces } from '@/hooks/use-marm-queries';
import { Badge, Button, Input, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Tabs, TabsList, TabsTrigger, TabsContent, Table, TableHeader, TableRow, TableHead, TableBody, TableCell, Textarea } from '@/components/ui/core';
import { PageControls } from '@/components/memory/shared';
import type { CodeSearchKind, RuntimeTrace, TraceDirection, TraceMode } from '@/lib/marm-types';

const EXPLORER_PAGE_SIZE = 50;

const EXPLORER_TOOLS = [
  { id: 'architecture', label: 'Architecture', detail: 'Indexed node types, relationships, and connected source files.', icon: Network, tone: 'console-tab-cyan' },
  { id: 'search', label: 'Code search', detail: 'Search names, code, or snippets within this indexed repository.', icon: SearchCode, tone: 'console-tab-blue' },
  { id: 'trace', label: 'Trace symbol', detail: 'Follow a qualified symbol through bounded call or data-flow paths.', icon: Activity, tone: 'console-tab-emerald' },
  { id: 'impact', label: 'Impact', detail: 'Compare a branch or revision to identify affected symbols.', icon: CircleAlert, tone: 'console-tab-rose' },
  { id: 'coverage', label: 'Coverage', detail: 'Recorded exclusions and index freshness signals.', icon: FileWarning, tone: 'console-tab-amber' },
  { id: 'adr', label: 'Decisions', detail: 'Read and edit this project’s architecture decision record.', icon: BookOpen, tone: 'console-tab-violet' },
  { id: 'runtime', label: 'Runtime traces', detail: 'Observed caller and callee frequency alongside static structure.', icon: Upload, tone: 'console-tab-teal' },
] as const;

export function ExplorerPage() {
  const [, navigate] = useLocation();
  const params = useParams();
  const { data: projects, isLoading: projectsLoading } = useProjects();
  const selectedName = params.name ? decodeURIComponent(params.name) : null;
  const project = projects?.find((candidate) => candidate.name === selectedName) ?? projects?.[0] ?? null;
  const [activeTab, setActiveTab] = useState('architecture');
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
  const [searchPage, setSearchPage] = useState(0);

  // Trace
  const [traceSymbol, setTraceSymbol] = useState('');
  const [traceDir, setTraceDir] = useState<TraceDirection>('both');
  const [traceMode, setTraceMode] = useState<TraceMode>('calls');
  const [tracePage, setTracePage] = useState(0);

  // Impact
  const [impactBranch, setImpactBranch] = useState('main');
  const [impactPage, setImpactPage] = useState(0);
  const [adrDraft, setAdrDraft] = useState('');
  const [runtimeCaller, setRuntimeCaller] = useState('');
  const [runtimeCallee, setRuntimeCallee] = useState('');
  const [runtimeCount, setRuntimeCount] = useState('1');

  // Architecture / coverage
  const [codeUnitsPage, setCodeUnitsPage] = useState(0);
  const [coveragePage, setCoveragePage] = useState(0);

  useEffect(() => setAdrDraft(''), [project?.name]);

  useEffect(() => {
    searchCode.reset();
    traceCode.reset();
    impactCode.reset();
    updateAdr.reset();
    ingestRuntimeTraces.reset();
    setSearchPage(0);
    setTracePage(0);
    setImpactPage(0);
    setCodeUnitsPage(0);
    setCoveragePage(0);
  }, [project?.name]);

  useEffect(() => {
    if (typeof adr?.content === 'string') setAdrDraft(adr.content);
  }, [adr?.content]);


  const runSearch = () => {
    if (!project || !searchQuery) return;
    setSearchPage(0);
    searchCode.mutate({ project: project.name, data: { query: searchQuery, kind: searchKind } });
  };

  const runTrace = () => {
    if (!project || !traceSymbol) return;
    setTracePage(0);
    traceCode.mutate({ project: project.name, data: { symbol: traceSymbol, direction: traceDir, mode: traceMode } });
  };

  const runImpact = () => {
    if (!project || !impactBranch) return;
    setImpactPage(0);
    impactCode.mutate({ project: project.name, data: { base_branch: impactBranch } });
  };

  const parsedRuntimeCount = Number(runtimeCount);
  const runtimeCountValid = /^\d+$/.test(runtimeCount.trim())
    && Number.isInteger(parsedRuntimeCount)
    && parsedRuntimeCount >= 1
    && parsedRuntimeCount <= 1_000_000;

  if (projectsLoading) {
    return <div className="page-enter flex h-full items-center justify-center text-sm text-muted-foreground">Loading indexed projects…</div>;
  }

  return (
    <div className="page-enter flex h-full flex-col overflow-hidden p-7 xl:p-8">
      <div className="mb-6 flex shrink-0 flex-wrap items-start justify-between gap-5">
        <div className="min-w-0">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">Code intelligence</div>
          <h1 className="text-[1.8rem] font-semibold tracking-[-0.045em]">Project Explorer</h1>
          <p className="mt-1 text-sm text-muted-foreground">Architecture, search, tracing, impact, coverage, decisions, and runtime evidence for one indexed repository.</p>
        </div>
        {project && (
          <div className="w-full max-w-sm shrink-0 sm:w-80">
            <div className="mb-1.5 flex items-center justify-between gap-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Project</p>
              <Link href="/projects" className="group flex items-center gap-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-primary/80 transition-colors hover:text-primary-highlight">
                Indexed Projects <ChevronRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
              </Link>
            </div>
            <Select value={project.name} onValueChange={(name) => navigate(`/explorer/${encodeURIComponent(name)}`)}>
              <SelectTrigger aria-label="Project"><SelectValue /></SelectTrigger>
              <SelectContent>
                {projects?.map((candidate) => <SelectItem key={candidate.name} value={candidate.name}>{candidate.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      {!project ? (
        <div className="flex flex-1 flex-col items-center justify-center rounded-xl border border-dashed p-12 text-center">
          <FolderCode className="mb-4 h-10 w-10 text-muted-foreground/60" />
          <h2 className="text-lg font-medium">No indexed repositories yet</h2>
          <p className="mt-2 max-w-sm text-sm text-muted-foreground">The explorer reads a local code graph. Index a repository first and it appears here.</p>
          <Link href="/projects"><Button className="mt-5">Go to Indexed Projects</Button></Link>
        </div>
      ) : (
        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <TabsList className="mb-4 grid h-auto w-full shrink-0 grid-cols-2 gap-1.5 rounded-xl border border-card-border bg-card/70 p-1.5 shadow-[0_14px_40px_rgba(0,0,0,0.16),inset_0_1px_0_rgba(var(--primary-rgb),0.04)] sm:grid-cols-4 lg:grid-cols-7">
            {EXPLORER_TOOLS.map((tool, index) => (
              <TabsTrigger
                key={tool.id}
                value={tool.id}
                title={tool.detail}
                className={`console-tab metric-enter group relative h-11 justify-center gap-2 overflow-hidden border border-transparent px-3 data-[state=active]:bg-white/[0.035] ${tool.tone}`}
                style={{ animationDelay: `${index * 45}ms` }}
              >
                <span className="console-tab-icon flex h-6 w-6 shrink-0 items-center justify-center rounded-md border bg-background/45 transition-transform duration-200 group-hover:scale-105">
                  <tool.icon className="h-3.5 w-3.5" />
                </span>
                <span className="truncate text-xs font-semibold text-foreground">{tool.label}</span>
              </TabsTrigger>
            ))}
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
                          {!codeUnitsLoading && codeUnits && codeUnitsState === 'ready' && codeUnits.code_units.slice(codeUnitsPage * EXPLORER_PAGE_SIZE, (codeUnitsPage + 1) * EXPLORER_PAGE_SIZE).map((unit) => <TableRow key={unit.unit}><TableCell className="font-mono text-xs">{unit.unit}</TableCell><TableCell className="text-right">{unit.fan_in}</TableCell><TableCell className="text-right">{unit.fan_out}</TableCell></TableRow>)}
                        </TableBody>
                      </Table>
                      {codeUnits && codeUnitsState === 'ready' && codeUnits.code_units.length > 0 && (
                        <PageControls
                          page={codeUnitsPage}
                          pageSize={EXPLORER_PAGE_SIZE}
                          total={codeUnits.code_units.length}
                          itemLabel="files"
                          onPageChange={setCodeUnitsPage}
                        />
                      )}
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
                  onKeyDown={e => e.key === 'Enter' && searchQuery && runSearch()}
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
                  onClick={runSearch}
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
                    {searchCode.data?.slice(searchPage * EXPLORER_PAGE_SIZE, (searchPage + 1) * EXPLORER_PAGE_SIZE).map((res, i) => (
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
              {(searchCode.data?.length ?? 0) > EXPLORER_PAGE_SIZE && (
                <PageControls
                  page={searchPage}
                  pageSize={EXPLORER_PAGE_SIZE}
                  total={searchCode.data!.length}
                  itemLabel="results"
                  onPageChange={setSearchPage}
                />
              )}
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
                  onClick={runTrace}
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
                    {traceCode.data?.steps.slice(tracePage * EXPLORER_PAGE_SIZE, (tracePage + 1) * EXPLORER_PAGE_SIZE).map((step, i) => (
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
              {(traceCode.data?.steps.length ?? 0) > EXPLORER_PAGE_SIZE && (
                <PageControls
                  page={tracePage}
                  pageSize={EXPLORER_PAGE_SIZE}
                  total={traceCode.data!.steps.length}
                  itemLabel="steps"
                  onPageChange={setTracePage}
                />
              )}
            </TabsContent>

            <TabsContent value="impact" className="project-explorer-panel mt-0 flex min-h-0 flex-1 flex-col gap-4 overflow-hidden pt-5">
               <div className="flex gap-2">
                <Input 
                  placeholder="Base branch (e.g. main)" 
                  value={impactBranch}
                  onChange={e => setImpactBranch(e.target.value)}
                />
                <Button
                  onClick={runImpact}
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
                    {impactCode.data?.affected_symbols.slice(impactPage * EXPLORER_PAGE_SIZE, (impactPage + 1) * EXPLORER_PAGE_SIZE).map((sym, i) => (
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
              {(impactCode.data?.affected_symbols.length ?? 0) > EXPLORER_PAGE_SIZE && (
                <PageControls
                  page={impactPage}
                  pageSize={EXPLORER_PAGE_SIZE}
                  total={impactCode.data!.affected_symbols.length}
                  itemLabel="symbols"
                  onPageChange={setImpactPage}
                />
              )}
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
                    {(coverage?.scopes[0]?.entries.length ?? 0) === 0 ? <p className="p-5 text-sm text-muted-foreground">No recorded gaps in this scope.</p> : <div className="divide-y">{coverage?.scopes[0]?.entries.slice(coveragePage * EXPLORER_PAGE_SIZE, (coveragePage + 1) * EXPLORER_PAGE_SIZE).map((entry) => <div key={`${entry.kind}-${entry.path}`} className="flex items-start gap-3 px-4 py-3"><FileWarning className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" /><div><p className="font-mono text-xs">{entry.path}</p><p className="mt-0.5 text-xs text-muted-foreground">{entry.kind}{entry.detail ? ` · ${entry.detail}` : ''}</p></div></div>)}</div>}
                    {(coverage?.scopes[0]?.entries.length ?? 0) > 0 && (
                      <PageControls
                        page={coveragePage}
                        pageSize={EXPLORER_PAGE_SIZE}
                        total={coverage!.scopes[0].entries.length}
                        itemLabel="entries"
                        onPageChange={setCoveragePage}
                      />
                    )}
                  </div>
                  {coverage?.caveat && <p className="text-xs text-muted-foreground">{coverage.caveat}</p>}
                </div>
              )}
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
      )}
    </div>
  );
}
