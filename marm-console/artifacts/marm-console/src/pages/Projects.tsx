import { useState } from 'react';
import { useProjects, useIndexProject, useIndexJob, useDeleteProject, useSearchProjectCode, useTraceProject, useProjectImpact } from '@/hooks/use-marm-queries';
import { Card, CardContent, CardHeader, CardTitle, CardDescription, Badge, Button, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, Input, Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Tabs, TabsList, TabsTrigger, TabsContent, Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from '@/components/ui/core';
import { FolderCode, HardDrive, RefreshCw, Trash2, SearchCode, GitBranch, Search, Share2, AlertCircle } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import type { IndexMode, ProjectIndexInput, ProjectSummary, CodeSearchKind, TraceDirection, TraceMode } from '@/lib/marm-types';

function IndexDialog({ open, onOpenChange }: { open: boolean, onOpenChange: (o: boolean) => void }) {
  const indexProj = useIndexProject();
  const [repoPath, setRepoPath] = useState('');
  const [name, setName] = useState('');
  const [mode, setMode] = useState<IndexMode>('fast');
  const [jobId, setJobId] = useState<string | null>(null);
  const { data: jobStatus } = useIndexJob(jobId || '');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!repoPath) return;
    indexProj.mutate(
      { repo_path: repoPath, project: name || undefined, mode },
      { onSuccess: (res) => setJobId(res.job_id) }
    );
  };

  const isRunning = jobStatus?.status === 'queued' || jobStatus?.status === 'running';

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!isRunning) onOpenChange(o); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Index Local Repository</DialogTitle>
          <DialogDescription>
            Point MARM to a local codebase to build an architectural graph. The path must be absolute and accessible to the server.
          </DialogDescription>
        </DialogHeader>
        
        {!jobId ? (
          <form onSubmit={handleSubmit} className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Repository Path</Label>
              <Input placeholder="/Users/dev/workspace/my-app" value={repoPath} onChange={e => setRepoPath(e.target.value)} required className="font-mono text-xs" />
            </div>
            <div className="space-y-2">
              <Label>Project Name (Optional)</Label>
              <Input placeholder="Inferred from folder if empty" value={name} onChange={e => setName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Index Mode</Label>
              <Select value={mode} onValueChange={(v: IndexMode) => setMode(v)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="fast">Fast (Signatures & Imports)</SelectItem>
                  <SelectItem value="moderate">Moderate (Includes Types)</SelectItem>
                  <SelectItem value="full">Full (Deep Body Analysis)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
              <Button type="submit" isLoading={indexProj.isPending}>Start Indexing</Button>
            </DialogFooter>
          </form>
        ) : (
          <div className="py-8 text-center space-y-4">
            <RefreshCw className={`w-12 h-12 mx-auto ${isRunning ? 'animate-spin text-primary' : jobStatus?.status === 'error' ? 'text-destructive' : 'text-emerald-500'}`} />
            <h3 className="font-semibold text-lg capitalize">{jobStatus?.status || 'Initializing...'}</h3>
            {jobStatus?.phase && <p className="text-sm font-mono text-muted-foreground">{jobStatus.phase}</p>}
            {jobStatus?.error && <p className="text-xs text-destructive p-2 bg-destructive/10 rounded">{jobStatus.error}</p>}
            
            {!isRunning && (
              <Button className="mt-4" onClick={() => onOpenChange(false)}>Done</Button>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
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

function ExploreDialog({ project, open, onOpenChange }: { project: ProjectSummary | null, open: boolean, onOpenChange: (o: boolean) => void }) {
  const searchCode = useSearchProjectCode();
  const traceCode = useTraceProject();
  const impactCode = useProjectImpact();

  // Search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchKind, setSearchKind] = useState<CodeSearchKind>('auto');

  // Trace
  const [traceSymbol, setTraceSymbol] = useState('');
  const [traceDir, setTraceDir] = useState<TraceDirection>('both');
  const [traceMode, setTraceMode] = useState<TraceMode>('calls');

  // Impact
  const [impactBranch, setImpactBranch] = useState('main');

  if (!project) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Explore: {project.name}</DialogTitle>
        </DialogHeader>

        <Tabs defaultValue="search" className="flex-1 flex flex-col overflow-hidden">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="search">Code Search</TabsTrigger>
            <TabsTrigger value="trace">Trace Symbol</TabsTrigger>
            <TabsTrigger value="impact">Impact Analysis</TabsTrigger>
          </TabsList>
          
          <TabsContent value="search" className="flex-1 overflow-hidden flex flex-col gap-4 pt-4">
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
          
          <TabsContent value="trace" className="flex-1 overflow-hidden flex flex-col gap-4 pt-4">
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

          <TabsContent value="impact" className="flex-1 overflow-hidden flex flex-col gap-4 pt-4">
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
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

export function ProjectsPage() {
  const { data: projects, isLoading } = useProjects();
  const [indexOpen, setIndexOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ProjectSummary | null>(null);
  const [exploreTarget, setExploreTarget] = useState<ProjectSummary | null>(null);

  return (
    <div className="p-8 flex flex-col h-full overflow-hidden">
      <div className="flex justify-between items-center mb-8 shrink-0">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Codebase Intelligence</h1>
          <p className="text-muted-foreground text-sm mt-1">Indexed local repositories and AST graphs</p>
        </div>
        <Button onClick={() => setIndexOpen(true)}>
          <FolderCode className="w-4 h-4 mr-2" /> Index Repository
        </Button>
      </div>

      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="text-center p-12 text-muted-foreground">Loading projects...</div>
        ) : projects?.length === 0 ? (
          <div className="border border-dashed rounded-lg p-12 text-center flex flex-col items-center">
            <SearchCode className="w-12 h-12 text-muted-foreground mb-4 opacity-50" />
            <h3 className="text-lg font-medium mb-2">No projects indexed</h3>
            <p className="text-muted-foreground max-w-sm mb-6">Index a local repository to give your agents structural awareness of the codebase.</p>
            <Button variant="outline" onClick={() => setIndexOpen(true)}>Index First Repo</Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            {projects?.map(proj => (
              <Card key={proj.name} className="flex flex-col">
                <CardHeader className="flex flex-row items-start justify-between pb-2">
                  <div>
                    <CardTitle className="font-mono text-lg flex items-center gap-2">
                      {proj.name}
                      <Badge variant={proj.status === 'ready' ? 'default' : proj.status === 'indexing' ? 'secondary' : 'destructive'} className="text-[10px] ml-2">
                        {proj.status}
                      </Badge>
                    </CardTitle>
                    <CardDescription className="font-mono text-xs mt-1 truncate max-w-sm" title={proj.root_path}>
                      {proj.root_path}
                    </CardDescription>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <Button variant="outline" size="sm" onClick={() => setExploreTarget(proj)}>
                      Explore
                    </Button>
                    <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-destructive shrink-0" onClick={() => setDeleteTarget(proj)}>
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="mt-4 flex-1">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="bg-muted/30 p-4 rounded-md border border-border/50">
                      <div className="flex items-center gap-2 mb-1">
                        <HardDrive className="w-4 h-4 text-primary" />
                        <span className="text-sm font-medium">Nodes</span>
                      </div>
                      <div className="text-2xl font-mono">{proj.nodes.toLocaleString()}</div>
                      <div className="text-[10px] text-muted-foreground uppercase tracking-widest mt-1">Files & Symbols</div>
                    </div>
                    <div className="bg-muted/30 p-4 rounded-md border border-border/50">
                      <div className="flex items-center gap-2 mb-1">
                        <GitBranch className="w-4 h-4 text-accent-foreground" />
                        <span className="text-sm font-medium">Edges</span>
                      </div>
                      <div className="text-2xl font-mono">{proj.edges.toLocaleString()}</div>
                      <div className="text-[10px] text-muted-foreground uppercase tracking-widest mt-1">Imports & Calls</div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      <IndexDialog open={indexOpen} onOpenChange={setIndexOpen} />
      <DeleteDialog project={deleteTarget} open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)} />
      <ExploreDialog project={exploreTarget} open={!!exploreTarget} onOpenChange={(o) => !o && setExploreTarget(null)} />
    </div>
  );
}
