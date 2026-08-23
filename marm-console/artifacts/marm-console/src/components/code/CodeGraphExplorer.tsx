import { useMemo, useState } from 'react';
import { GitFork, Network, SearchCode, X } from 'lucide-react';
import { Badge, Button, Input } from '@/components/ui/core';
import type { CodeGraphSnapshot, ProjectSummary } from '@/lib/marm-types';
import { useProjectGraphNeighborhood } from '@/hooks/use-marm-queries';
import { CodeGraphViz } from './CodeGraphViz';

export function CodeGraphExplorer({
  project,
  graph,
  isLoading,
  isError,
}: {
  project: ProjectSummary;
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

  if (isLoading) return <div className="flex min-h-[28rem] items-center justify-center text-sm text-muted-foreground">Building a bounded code graph view…</div>;
  if (isError || graph?.state === 'unavailable') return <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-muted-foreground"><p className="font-medium text-foreground">Code Graph is unavailable</p><p className="mt-1">{graph?.message || 'The graph backend could not provide a safe visual snapshot right now.'}</p></div>;
  if (!graph || graph.state === 'empty_index') return <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">This project has no indexed code files yet.</div>;
  if (graph.state === 'indexed_no_summary') return <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">The repository is indexed, but MARM could not identify source files suitable for the Code Graph.</div>;

  return <div className="flex min-h-0 flex-1 flex-col gap-4">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Metric label="Indexed graph" value={`${project.nodes.toLocaleString()} nodes`} detail={`${project.edges.toLocaleString()} relationships`} />
      <Metric label="Code files" value={graph.total.code_units.toLocaleString()} detail={`${graph.rendered.code_units.toLocaleString()} rendered`} tone="cyan" />
      <Metric label="Import edges" value={graph.total.import_edges.toLocaleString()} detail={`${graph.rendered.import_edges.toLocaleString()} visible`} tone="violet" />
      <Metric label="Layer" value="Code Graph" detail="Independent of memories" tone="emerald" />
    </div>
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/70 bg-muted/20 p-3">
      <div className="flex min-w-0 items-center gap-2"><Network className="h-4 w-4 shrink-0 text-cyan-300" /><div><p className="text-sm font-medium">File import topology</p><p className="text-xs text-muted-foreground">Most connected source files, never an unbounded raw graph dump.</p></div></div>
      <Badge variant="outline" className="border-cyan-400/25 bg-cyan-400/5 text-cyan-200">{graph.truncated ? 'Bounded view' : 'Complete view'}</Badge>
    </div>
    <div className="grid min-h-[27rem] flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_15rem]">
      <div className="min-h-[27rem]">
        <CodeGraphViz graph={expandedGraph || graph} filter={filter} selectedId={selectedId} onNodeClick={setSelectedId} />
      </div>
      <aside className="flex min-h-0 flex-col rounded-xl border border-border/70 bg-muted/15 p-3">
        <label className="mb-2 text-xs font-medium text-muted-foreground" htmlFor="code-graph-filter">Filter visible files</label>
        <div className="relative"><SearchCode className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" /><Input id="code-graph-filter" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="path or filename" className="h-9 pl-8 font-mono text-xs" /></div>
        {selected ? <div className="mt-4 space-y-3"><div className="flex items-start justify-between gap-2"><p className="break-all font-mono text-xs font-medium">{selected.path}</p><Button variant="ghost" size="icon" className="-mr-1 -mt-1 h-7 w-7" title="Clear file focus" onClick={() => setSelectedId(null)}><X className="h-3.5 w-3.5" /></Button></div><div className="grid grid-cols-2 gap-2"><Metric label="Imported by" value={selected.fan_in === null ? 'Not sampled' : String(selected.fan_in)} compact /><Metric label="Imports" value={selected.fan_out === null ? 'Not sampled' : String(selected.fan_out)} compact /></div>{neighborhood.isLoading ? <p className="text-xs text-muted-foreground">Loading its bounded import neighborhood…</p> : neighborhood.data?.state === 'unavailable' ? <p className="text-xs text-muted-foreground">A wider neighborhood is unavailable; the initial snapshot is still shown.</p> : <p className="text-xs leading-relaxed text-muted-foreground">{neighborhood.data?.truncated ? `Showing ${neighborhood.data.rendered_imports} of ${neighborhood.data.total_imports} import statements around this file.` : 'Highlighted links include this file’s direct import neighborhood.'} Use Trace symbol for function-level callers and dependencies.</p>}</div> : <div className="mt-5 rounded-lg border border-dashed p-3 text-xs leading-relaxed text-muted-foreground"><GitFork className="mb-2 h-4 w-4 text-cyan-300" />Select a file to load its bounded direct imports and importers.</div>}
        {graph.sample_reason && <p className="mt-auto pt-4 text-[11px] leading-relaxed text-muted-foreground">{graph.sample_reason}</p>}
      </aside>
    </div>
  </div>;
}

function Metric({ label, value, detail, tone, compact = false }: { label: string; value: string; detail?: string; tone?: 'cyan' | 'violet' | 'emerald'; compact?: boolean }) {
  const color = tone === 'cyan' ? 'border-cyan-400/20 bg-cyan-400/5' : tone === 'violet' ? 'border-violet-400/20 bg-violet-400/5' : tone === 'emerald' ? 'border-emerald-400/20 bg-emerald-400/5' : 'border-border/70 bg-muted/20';
  return <div className={`rounded-lg border ${compact ? 'p-2.5' : 'p-3'} ${color}`}><p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p><p className={`${compact ? 'mt-1 text-base' : 'mt-1.5 text-lg'} font-semibold tracking-tight`}>{value}</p>{detail && <p className="mt-0.5 text-[10px] text-muted-foreground">{detail}</p>}</div>;
}
