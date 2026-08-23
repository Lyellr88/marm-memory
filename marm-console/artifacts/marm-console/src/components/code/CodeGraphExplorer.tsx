import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Braces, FileCode2, GitFork, Network, Search, Waypoints, X } from 'lucide-react';
import { Badge, Button, Card, CardContent, CardHeader, Input, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/core';
import type { CodeGraphNeighborhood, CodeGraphSnapshot, ProjectSummary } from '@/lib/marm-types';
import { useProjectGraphNeighborhood } from '@/hooks/use-marm-queries';
import { CodeGraphViz } from './CodeGraphViz';

export function CodeGraphExplorer({
  project,
  projects,
  projectName,
  onProjectChange,
  graph,
  isLoading,
  isError,
}: {
  project: ProjectSummary;
  projects: ProjectSummary[];
  projectName: string;
  onProjectChange: (project: string) => void;
  graph: CodeGraphSnapshot | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  const [filter, setFilter] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const neighborhood = useProjectGraphNeighborhood(project.name, selectedId);
  const expandedGraph = useMemo(() => {
    if (!graph || neighborhood.data?.state !== 'ready') return graph;
    const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
    neighborhood.data.nodes.forEach((node) => {
      if (!nodes.has(node.id)) nodes.set(node.id, node);
    });
    const edges = new Map(graph.edges.map((edge) => [`${edge.source}\u0000${edge.target}`, edge]));
    neighborhood.data.edges.forEach((edge) => {
      const key = `${edge.source}\u0000${edge.target}`;
      const existing = edges.get(key);
      if (!existing || edge.count > existing.count) edges.set(key, edge);
    });
    return {
      ...graph,
      rendered: { code_units: nodes.size, import_edges: edges.size },
      nodes: [...nodes.values()],
      edges: [...edges.values()],
    };
  }, [graph, neighborhood.data]);
  const selected = useMemo(() => expandedGraph?.nodes.find((node) => node.id === selectedId) || null, [expandedGraph?.nodes, selectedId]);
  const visibleFiles = useMemo(() => {
    const normalized = filter.trim().toLowerCase();
    return [...(expandedGraph?.nodes || [])]
      .filter((node) => !normalized || node.path.toLowerCase().includes(normalized))
      .sort((a, b) => ((b.fan_in || 0) + (b.fan_out || 0)) - ((a.fan_in || 0) + (a.fan_out || 0)) || a.path.localeCompare(b.path));
  }, [expandedGraph?.nodes, filter]);

  useEffect(() => {
    if (selectedId && !expandedGraph?.nodes.some((node) => node.id === selectedId)) setSelectedId(null);
  }, [expandedGraph?.nodes, selectedId]);

  const stateMessage = isLoading
    ? 'Building a bounded code graph view…'
    : isError || graph?.state === 'unavailable'
      ? graph?.message || 'The graph backend could not provide a safe visual snapshot right now.'
      : !graph || graph.state === 'empty_index'
        ? 'This project has no indexed code files yet.'
        : graph.state === 'indexed_no_summary'
          ? 'The repository is indexed, but MARM could not identify source files suitable for the Code Graph.'
          : null;
  const readyGraph = graph?.state === 'ready' ? graph : null;

  if (stateMessage || !readyGraph) return <div className="flex h-full min-h-0 flex-col gap-3 pb-4">
    <ProjectPicker project={project} projects={projects} projectName={projectName} onProjectChange={onProjectChange} />
    <div className={`flex min-h-[28rem] flex-1 items-center justify-center rounded-lg border p-8 text-center text-sm text-muted-foreground ${isError || graph?.state === 'unavailable' ? 'border-destructive/30 bg-destructive/5' : 'border-dashed'}`}><div><p className="font-medium text-foreground">{isError || graph?.state === 'unavailable' ? 'Code Graph is unavailable' : isLoading ? 'Loading Code Explorer' : 'No code graph to show yet'}</p><p className="mt-1">{stateMessage}</p></div></div>
  </div>;

  return <div className="grid h-full min-h-0 grid-cols-1 gap-6 lg:grid-cols-3">
    <aside className="flex h-full min-h-0 flex-col gap-6 overflow-hidden pb-4">
      <Card className="graph-metrics-rail shrink-0 overflow-hidden border-card-border border-t-cyan-400/45 bg-card/80 shadow-[0_18px_44px_rgba(0,0,0,0.18)]">
        <CardContent className="p-4">
          <div className="grid grid-cols-3 divide-x divide-border/70 text-center">
            <RailMetric icon={<Network className="h-3.5 w-3.5" />} label="Files" value={readyGraph.total.code_units.toLocaleString()} />
            <RailMetric icon={<Waypoints className="h-3.5 w-3.5" />} label="Imports" value={readyGraph.total.import_edges.toLocaleString()} />
            <RailMetric icon={<Braces className="h-3.5 w-3.5" />} label="Visible" value={readyGraph.rendered.code_units.toLocaleString()} />
          </div>
        </CardContent>
      </Card>

      <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <CardHeader className="shrink-0 pb-3">
          <div className="relative"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" /><Input id="code-graph-filter" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Search files…" className="bg-muted/50 pl-9 font-mono" /></div>
        </CardHeader>
        <CardContent className="flex-1 overflow-auto p-0 px-2 pb-2">
          <div className="space-y-1">
            {visibleFiles.length === 0 ? <div className="p-4 text-center text-sm text-muted-foreground">No visible files match that search.</div> : visibleFiles.map((node) => {
              const connections = (node.fan_in || 0) + (node.fan_out || 0);
              return <button key={node.id} type="button" onClick={() => setSelectedId(node.id)} className={`w-full rounded-md border p-3 text-left transition-colors ${selectedId === node.id ? 'border-cyan-400/45 bg-cyan-400/10' : 'border-transparent hover:bg-muted'}`}>
                <div className="flex items-center justify-between gap-2 font-mono text-sm font-medium"><span className="flex min-w-0 items-center gap-2 truncate"><span className="h-2 w-2 shrink-0 rounded-full bg-cyan-400" /><span className="truncate">{node.label}</span></span><span className="shrink-0 text-xs text-muted-foreground">{connections} links</span></div>
                <div className="mt-2 flex items-center gap-2"><Badge variant="secondary" className="text-[10px]">file</Badge><span className="truncate font-mono text-[10px] text-muted-foreground">{node.path}</span></div>
              </button>;
            })}
          </div>
        </CardContent>
      </Card>
    </aside>

    <section className="flex min-h-0 flex-col gap-3 pb-4 lg:col-span-2">
      <div className="flex min-h-[26px] flex-wrap items-center gap-2 shrink-0">
        <ProjectPicker project={project} projects={projects} projectName={projectName} onProjectChange={onProjectChange} />
        <Badge variant="outline" className="border-cyan-400/25 bg-cyan-400/5 text-cyan-200"><FileCode2 className="mr-1 h-3 w-3" /> File imports</Badge>
        <Badge variant="outline" className="border-border bg-muted/40 text-muted-foreground">{readyGraph.truncated ? 'Bounded view' : 'Complete view'}</Badge>
      </div>
      <div className="relative flex min-h-[28rem] flex-1 overflow-hidden rounded-lg border bg-card shadow-inner">
        <CodeGraphViz graph={expandedGraph || readyGraph} filter={filter} selectedId={selectedId} onNodeClick={setSelectedId} />
        {selected && <FileFocusPanel selected={selected} neighborhood={neighborhood.data} isLoading={neighborhood.isLoading} onClose={() => setSelectedId(null)} />}
      </div>
      {readyGraph.sample_reason && <p className="shrink-0 px-1 text-[11px] leading-relaxed text-muted-foreground">{readyGraph.sample_reason}</p>}
    </section>
  </div>;
}

function RailMetric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <div className="graph-metric group"><div className="flex items-center justify-center gap-1.5 text-cyan-300/80">{icon}<span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span></div><div className="mt-1 text-xl font-bold text-cyan-300">{value}</div></div>;
}

function ProjectPicker({ project, projects, projectName, onProjectChange }: Pick<Parameters<typeof CodeGraphExplorer>[0], 'project' | 'projects' | 'projectName' | 'onProjectChange'>) {
  return <Select value={projectName} onValueChange={onProjectChange}><SelectTrigger className="h-7 w-[min(100%,24rem)] text-xs" aria-label={`Indexed repository: ${project.name}`}><SelectValue placeholder="Select indexed repository" /></SelectTrigger><SelectContent>{projects.map((item) => <SelectItem key={item.name} value={item.name}>{item.name}</SelectItem>)}</SelectContent></Select>;
}

function FileFocusPanel({ selected, neighborhood, isLoading, onClose }: { selected: CodeGraphSnapshot['nodes'][number]; neighborhood: CodeGraphNeighborhood | undefined; isLoading: boolean; onClose: () => void }) {
  return <aside className="absolute right-0 top-0 z-10 flex h-full w-72 flex-col border-l bg-card/95 shadow-xl backdrop-blur">
    <div className="flex shrink-0 items-start justify-between gap-2 border-b p-4"><div className="flex min-w-0 items-center gap-2"><span className="h-2.5 w-2.5 shrink-0 rounded-full bg-cyan-400" /><div className="min-w-0"><p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-300">File focus</p><p className="truncate font-mono text-sm font-medium">{selected.label}</p></div></div><Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" title="Clear file focus" onClick={onClose}><X className="h-4 w-4" /></Button></div>
    <div className="flex-1 space-y-4 overflow-auto p-4 text-sm"><p className="break-all font-mono text-xs text-muted-foreground">{selected.path}</p><div className="grid grid-cols-2 gap-2 text-xs"><FocusMetric label="Imported by" value={selected.fan_in === null ? 'Not sampled' : String(selected.fan_in)} /><FocusMetric label="Imports" value={selected.fan_out === null ? 'Not sampled' : String(selected.fan_out)} /></div><div className="rounded-lg border border-dashed p-3 text-xs leading-relaxed text-muted-foreground"><GitFork className="mb-2 h-4 w-4 text-cyan-300" />{isLoading ? 'Loading its bounded direct imports and importers…' : neighborhood?.state === 'unavailable' ? 'A wider neighborhood is unavailable; the initial graph remains available.' : neighborhood?.truncated ? `Showing ${neighborhood.rendered_imports} of ${neighborhood.total_imports} import statements around this file.` : 'Highlighted links include this file’s direct import neighborhood.'}</div></div>
    <div className="shrink-0 border-t p-4"><Button className="w-full" size="sm" variant="outline" onClick={onClose}>Return to full topology</Button></div>
  </aside>;
}

function FocusMetric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-muted/30 p-2 text-center"><div className="text-base font-bold text-cyan-200">{value}</div><div className="mt-0.5 text-muted-foreground">{label}</div></div>;
}
