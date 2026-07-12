import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useConceptsSummary, useSearchConcepts, useNeighborhood, useConceptGraph, useConcept, useBuildConcepts, useConceptBuild, useConceptDuplicates, useMarmConfig, useFilters } from '@/hooks/use-marm-queries';
import { Card, CardContent, CardHeader, CardTitle, CardDescription, Input, Button, Badge, Dialog, DialogContent, DialogHeader, DialogTitle, Tabs, TabsList, TabsTrigger, TabsContent, Table, TableHeader, TableRow, TableHead, TableBody, TableCell, Select, SelectTrigger, SelectValue, SelectContent, SelectItem, Label } from '@/components/ui/core';
import { Search, GitGraph, Network, AlertTriangle, Layers, Play, Pause, X, ZoomIn, ZoomOut, Maximize2, ArrowLeft } from 'lucide-react';
import ForceGraph2D from 'react-force-graph-2d';
import { forceCollide } from 'd3-force';
import { useQueryClient } from '@tanstack/react-query';
import type { Neighborhood, NeighborhoodNode, NeighborhoodEdge, ConceptBuildInput, ConceptDetail } from '@/lib/marm-types';

const DEFAULT_HIDDEN_PREDICATES = new Set(['co_occurs_with']);

// CVD-validated categorical palette for the dark canvas (dataviz six-checks,
// surface #040810). Identity is never color alone: labels + legend back it up.
const TYPE_COLORS: Record<string, string> = {
  concept: '#0284c7',
  decision: '#8b5cf6',
  pattern: '#d97706',
  tool: '#059669',
  person: '#ec4899',
  error: '#ef4444',
  org: '#ea580c',
  product: '#65a30d',
};
const OTHER_TYPE_COLOR = '#64748b';

function typeColor(type: string): string {
  return TYPE_COLORS[type] ?? OTHER_TYPE_COLOR;
}

function nodeRadius(degree: number): number {
  return Math.min(2.5 + Math.sqrt(Math.max(degree, 1)) * 1.3, 13);
}

function mergeNeighborhoods(base: Neighborhood, addition: Neighborhood): Neighborhood {
  const nodeMap = new Map<number, NeighborhoodNode>();
  base.nodes.forEach(n => nodeMap.set(n.id, n));
  addition.nodes.forEach(n => nodeMap.set(n.id, n));
  const edgeMap = new Map<number, NeighborhoodEdge>();
  base.edges.forEach(e => edgeMap.set(e.id, e));
  addition.edges.forEach(e => edgeMap.set(e.id, e));
  return {
    seed_id: base.seed_id,
    nodes: Array.from(nodeMap.values()),
    edges: Array.from(edgeMap.values()),
    limits: base.limits,
    truncated: base.truncated || addition.truncated,
  };
}

function GraphViz({
  neighborhood,
  hiddenPredicates,
  hiddenTypes,
  onNodeClick,
  focusedId,
  expandingId,
}: {
  neighborhood: Neighborhood;
  hiddenPredicates: Set<string>;
  hiddenTypes: Set<string>;
  onNodeClick: (node: NeighborhoodNode) => void;
  focusedId: number | null;
  expandingId: number | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<any>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [hoverId, setHoverId] = useState<number | null>(null);
  const [paused, setPaused] = useState(false);
  const didInitialFit = useRef(false);
  const pinnedRef = useRef<Map<number, { x: number; y: number }>>(new Map());
  const reducedMotion = useMemo(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    []
  );

  useEffect(() => {
    if (!containerRef.current) return;
    const obs = new ResizeObserver(entries => {
      setDimensions({
        width: entries[0].contentRect.width,
        height: entries[0].contentRect.height
      });
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  const gData = useMemo(() => {
    const visibleNodeIds = new Set(
      neighborhood.nodes.filter(n => !hiddenTypes.has(n.type)).map(n => n.id)
    );
    const visibleEdges = neighborhood.edges.filter(
      e => !hiddenPredicates.has(e.predicate) && visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target)
    );
    // Filtering edges out must not leave stranded dots: keep only nodes that
    // still connect to something, plus the seed and the focused node.
    const connected = new Set<number>();
    visibleEdges.forEach(e => { connected.add(e.source); connected.add(e.target); });
    if (neighborhood.seed_id !== null) connected.add(neighborhood.seed_id);
    if (focusedId !== null) connected.add(focusedId);
    const nodes = neighborhood.nodes
      .filter(n => visibleNodeIds.has(n.id) && connected.has(n.id))
      .map((n) => {
        const pinned = pinnedRef.current.get(n.id);
        return {
          id: n.id,
          name: n.name,
          type: n.type,
          degree: n.degree ?? n.mention_count,
          hiddenNeighborCount: n.hidden_neighbor_count,
          isSeed: n.id === neighborhood.seed_id,
          ...(pinned ? { fx: pinned.x, fy: pinned.y } : {}),
        };
      });
    return {
      nodes,
      links: visibleEdges.map((e) => ({
        source: e.source,
        target: e.target,
        predicate: e.predicate,
      })),
    };
  }, [neighborhood, hiddenPredicates, hiddenTypes, focusedId]);

  const adjacency = useMemo(() => {
    const map = new Map<number, Set<number>>();
    gData.links.forEach((l: any) => {
      const s = typeof l.source === 'object' ? l.source.id : l.source;
      const t = typeof l.target === 'object' ? l.target.id : l.target;
      if (!map.has(s)) map.set(s, new Set());
      if (!map.has(t)) map.set(t, new Set());
      map.get(s)!.add(t);
      map.get(t)!.add(s);
    });
    return map;
  }, [gData]);

  const hoverNeighbors = hoverId !== null ? adjacency.get(hoverId) : null;

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force('charge')?.strength(-110).distanceMax(280);
    fg.d3Force('link')?.distance((l: any) => (l.predicate === 'co_occurs_with' ? 62 : 44));
    fg.d3Force('collide', forceCollide((n: any) => nodeRadius(n.degree) + 4));
  }, [gData]);

  // Pin positions after the first settle so expansions don't re-layout
  // everything, then frame the graph once.
  const handleEngineStop = useCallback(() => {
    const fg = fgRef.current;
    if (!fg) return;
    const nodes: any[] = fg.graphData?.().nodes || [];
    nodes.forEach(n => {
      if (typeof n.x === 'number' && typeof n.y === 'number') {
        pinnedRef.current.set(n.id, { x: n.x, y: n.y });
      }
    });
    if (!didInitialFit.current) {
      didInitialFit.current = true;
      fg.zoomToFit(reducedMotion ? 0 : 500, 60);
      if (reducedMotion) {
        fg.pauseAnimation();
        setPaused(true);
      }
    }
  }, [reducedMotion]);

  const isDimmed = useCallback((id: number) => {
    if (hoverId === null) return false;
    return id !== hoverId && !hoverNeighbors?.has(id);
  }, [hoverId, hoverNeighbors]);

  const paintNode = useCallback((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const r = nodeRadius(node.degree);
    const color = typeColor(node.type);
    const dimmed = isDimmed(node.id);
    const emphasized = node.id === hoverId || node.id === focusedId || node.isSeed;

    ctx.globalAlpha = dimmed ? 0.12 : 1;

    // Soft halo keeps hubs luminous on the near-black canvas.
    if (!dimmed) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r * 2, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.globalAlpha = emphasized ? 0.28 : 0.13;
      ctx.fill();
      ctx.globalAlpha = 1;
    }

    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();

    if (node.isSeed || node.id === focusedId) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 1.6, 0, 2 * Math.PI);
      ctx.strokeStyle = node.isSeed ? '#e2e8f0' : '#38bdf8';
      ctx.lineWidth = 1.4;
      ctx.stroke();
    }

    // Labels: hubs always, everything when zoomed in or highlighted.
    const showLabel = !dimmed && (
      emphasized || r * globalScale > 10 || globalScale > 2.4
    );
    if (showLabel) {
      const fontSize = Math.max(11 / globalScale, 2.4);
      ctx.font = `500 ${fontSize}px 'JetBrains Mono', monospace`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      const labelY = node.y + r + 2.5 / globalScale;
      ctx.lineWidth = 3 / globalScale;
      ctx.strokeStyle = 'rgba(4, 8, 16, 0.92)';
      ctx.strokeText(node.name, node.x, labelY);
      ctx.fillStyle = emphasized ? '#f1f5f9' : '#94a3b8';
      ctx.fillText(node.name, node.x, labelY);

      if (node.hiddenNeighborCount > 0) {
        const badge = `+${node.hiddenNeighborCount}`;
        ctx.font = `${Math.max(9 / globalScale, 2)}px 'JetBrains Mono', monospace`;
        ctx.textBaseline = 'bottom';
        ctx.strokeText(badge, node.x + r + 5 / globalScale, node.y - r);
        ctx.fillStyle = expandingId === node.id ? '#fbbf24' : '#38bdf8';
        ctx.fillText(badge, node.x + r + 5 / globalScale, node.y - r);
      }
    }
    ctx.globalAlpha = 1;
  }, [hoverId, focusedId, expandingId, isDimmed]);

  const paintPointerArea = useCallback((node: any, color: string, ctx: CanvasRenderingContext2D) => {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(node.x, node.y, nodeRadius(node.degree) + 5, 0, 2 * Math.PI);
    ctx.fill();
  }, []);

  const linkColor = useCallback((link: any) => {
    const s = typeof link.source === 'object' ? link.source.id : link.source;
    const t = typeof link.target === 'object' ? link.target.id : link.target;
    if (hoverId !== null) {
      if (s === hoverId || t === hoverId) return 'rgba(56, 189, 248, 0.55)';
      return 'rgba(148, 163, 184, 0.04)';
    }
    return link.predicate === 'co_occurs_with'
      ? 'rgba(148, 163, 184, 0.08)'
      : 'rgba(148, 163, 184, 0.18)';
  }, [hoverId]);

  const linkWidth = useCallback((link: any) => {
    const s = typeof link.source === 'object' ? link.source.id : link.source;
    const t = typeof link.target === 'object' ? link.target.id : link.target;
    return hoverId !== null && (s === hoverId || t === hoverId) ? 1.4 : 0.6;
  }, [hoverId]);

  const togglePause = () => {
    const fg = fgRef.current;
    if (!fg) return;
    if (paused) fg.resumeAnimation(); else fg.pauseAnimation();
    setPaused(!paused);
  };

  const zoomBy = (factor: number) => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.zoom(fg.zoom() * factor, 200);
  };

  return (
    <div ref={containerRef} className="w-full h-full bg-[#040810] relative overflow-hidden rounded-md border border-primary/20">
      {dimensions.width > 0 && (
        <ForceGraph2D
          ref={fgRef}
          width={dimensions.width}
          height={dimensions.height}
          graphData={gData}
          nodeLabel={() => ''}
          linkLabel={(l: any) => l.predicate}
          nodeCanvasObjectMode={() => 'replace'}
          nodeCanvasObject={paintNode}
          nodePointerAreaPaint={paintPointerArea}
          linkColor={linkColor}
          linkWidth={linkWidth}
          linkCurvature={0.12}
          linkDirectionalArrowLength={(l: any) => (l.predicate === 'co_occurs_with' ? 0 : 2.6)}
          linkDirectionalArrowRelPos={1}
          onNodeHover={(node: any) => setHoverId(node ? node.id : null)}
          onNodeClick={(node: any) => {
            const full = neighborhood.nodes.find((n) => n.id === node.id);
            if (full) onNodeClick(full);
          }}
          onBackgroundClick={() => setHoverId(null)}
          onEngineStop={handleEngineStop}
          cooldownTicks={120}
        />
      )}
      <div className="absolute top-4 left-4 flex gap-2 pointer-events-none">
        <Badge variant="outline" className="bg-black/50 backdrop-blur border-primary/30 text-primary">
          {gData.nodes.length} Nodes
        </Badge>
        <Badge variant="outline" className="bg-black/50 backdrop-blur border-primary/30 text-primary">
          {gData.links.length} Edges
        </Badge>
        {neighborhood.truncated && (
          <Badge variant="destructive" className="bg-destructive/20 border-destructive">
            Budget Truncated
          </Badge>
        )}
      </div>
      <div className="absolute bottom-4 left-4 flex flex-col gap-1">
        <Button variant="secondary" size="icon" className="h-7 w-7 bg-black/50 backdrop-blur border border-border" onClick={() => zoomBy(1.4)} title="Zoom in">
          <ZoomIn className="w-3.5 h-3.5" />
        </Button>
        <Button variant="secondary" size="icon" className="h-7 w-7 bg-black/50 backdrop-blur border border-border" onClick={() => zoomBy(1 / 1.4)} title="Zoom out">
          <ZoomOut className="w-3.5 h-3.5" />
        </Button>
        <Button variant="secondary" size="icon" className="h-7 w-7 bg-black/50 backdrop-blur border border-border" onClick={() => fgRef.current?.zoomToFit(300, 60)} title="Fit to view">
          <Maximize2 className="w-3.5 h-3.5" />
        </Button>
        <Button variant="secondary" size="icon" className="h-7 w-7 bg-black/50 backdrop-blur border border-border" onClick={togglePause} title={paused ? 'Resume layout' : 'Freeze layout'}>
          {paused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
        </Button>
      </div>
      <div className="absolute bottom-4 right-4 text-[10px] text-muted-foreground bg-black/50 backdrop-blur px-2 py-1 rounded pointer-events-none">
        Hover to trace connections · click a node for details
      </div>
    </div>
  );
}

function BuildConceptsDialog({ open, onOpenChange }: { open: boolean, onOpenChange: (o: boolean) => void }) {
  const build = useBuildConcepts();
  const { baseUrl } = useMarmConfig();
  const queryClient = useQueryClient();
  const { data: filters } = useFilters();
  const [jobId, setJobId] = useState<string | null>(null);
  const { data: jobStatus } = useConceptBuild(jobId || '');
  const [scope, setScope] = useState<'session' | 'project' | 'all'>('session');
  const [scopeValue, setScopeValue] = useState('');
  const [confirmAll, setConfirmAll] = useState(false);

  const handleBuild = () => {
    const input: ConceptBuildInput =
      scope === 'session' ? { session_name: scopeValue } :
      scope === 'project' ? { project: scopeValue } :
      { search_all: true };
    build.mutate(input, {
      onSuccess: (res) => setJobId(res.job_id)
    });
  };

  const isRunning = jobStatus?.status === 'queued' || jobStatus?.status === 'running';
  const canSubmit = scope === 'all' ? confirmAll : !!scopeValue;

  useEffect(() => {
    if (!jobStatus || isRunning) return;
    queryClient.invalidateQueries({ queryKey: ['conceptsSummary', baseUrl] });
    queryClient.invalidateQueries({ queryKey: ['conceptsSearch', baseUrl] });
    queryClient.invalidateQueries({ queryKey: ['conceptsGraph', baseUrl] });
    queryClient.invalidateQueries({ queryKey: ['duplicates', baseUrl] });
  }, [baseUrl, isRunning, jobStatus, queryClient]);

  return (
    <Dialog open={open} onOpenChange={(o) => { if(!isRunning) onOpenChange(o); }}>
      <DialogContent>
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
            {jobStatus?.status === 'degraded' && (
              <div className="p-3 bg-amber-500/10 text-amber-500 border border-amber-500/20 rounded text-sm flex gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <p>Degraded mode: {jobStatus.error_code || 'Missing dependencies on server'}</p>
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
            {!isRunning && (
              <Button className="w-full mt-4" variant="outline" onClick={() => onOpenChange(false)}>
                Close
              </Button>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ProvenancePanel({
  node,
  detail,
  onClose,
  onExpand,
  onRecenter,
  isExpanding,
}: {
  node: NeighborhoodNode;
  detail?: ConceptDetail;
  onClose: () => void;
  onExpand: () => void;
  onRecenter: () => void;
  isExpanding: boolean;
}) {
  return (
    <div className="absolute top-0 right-0 h-full w-72 bg-card/95 backdrop-blur border-l shadow-xl flex flex-col z-10">
      <div className="flex items-center justify-between p-4 border-b shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: typeColor(node.type) }} />
          <div className="font-mono text-sm font-medium truncate">{node.name}</div>
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" onClick={onClose}><X className="w-4 h-4" /></Button>
      </div>
      <div className="flex-1 overflow-auto p-4 space-y-4 text-sm">
        <div className="flex flex-wrap gap-1">
          <Badge variant="secondary" className="text-[10px]">{node.type}</Badge>
          {node.session_name && <Badge variant="outline" className="text-[10px]">{node.session_name}</Badge>}
          {node.project && <Badge variant="outline" className="text-[10px]">{node.project}</Badge>}
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="p-2 bg-muted/30 rounded text-center">
            <div className="font-bold text-base">{node.mention_count}</div>
            <div className="text-muted-foreground">Mentions</div>
          </div>
          <div className="p-2 bg-muted/30 rounded text-center">
            <div className="font-bold text-base">{node.degree ?? 0}</div>
            <div className="text-muted-foreground">Connections</div>
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2">Linked code</div>
          {(detail?.linked_code ?? node.linked_code).length === 0 ? (
            <p className="text-xs text-muted-foreground">No linked code symbols.</p>
          ) : (
            <div className="space-y-1">
              {(detail?.linked_code ?? node.linked_code).map((c, i) => (
                <div key={i} className="font-mono text-xs p-2 bg-muted/30 rounded">
                  <div className="truncate">{c.qualified_name}</div>
                  <div className="text-muted-foreground truncate">{c.file_path}</div>
                </div>
              ))}
            </div>
          )}
        </div>
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2">Source memories</div>
          {!detail ? (
            <p className="text-xs text-muted-foreground">Loading provenance...</p>
          ) : detail.source_memories.length === 0 ? (
            <p className="text-xs text-muted-foreground">No source memories are available.</p>
          ) : (
            <div className="space-y-2">
              {detail.source_memories.map((memory) => (
                <div key={memory.id} className="p-2 bg-muted/30 rounded text-xs">
                  <p className="line-clamp-3">{memory.content}</p>
                  <p className="mt-1 text-muted-foreground truncate">{memory.session_name}{memory.project ? ` · ${memory.project}` : ''}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="p-4 border-t shrink-0 space-y-2">
        {node.hidden_neighbor_count > 0 && (
          <Button className="w-full" size="sm" onClick={onExpand} isLoading={isExpanding}>
            <Network className="w-4 h-4 mr-2" /> Expand {node.hidden_neighbor_count} hidden
          </Button>
        )}
        <Button className="w-full" size="sm" variant="outline" onClick={onRecenter}>
          Recenter graph here
        </Button>
      </div>
    </div>
  );
}

function ExplorerTab() {
  const { data: summary } = useConceptsSummary();
  const { client } = useMarmConfig();
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const { data: searchResults, isLoading: searchLoading } = useSearchConcepts({ q: debouncedQ, limit: 10 });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [direction, setDirection] = useState<'both' | 'incoming' | 'outgoing'>('both');
  const {
    data: baseNeighborhood,
    isError: neighborhoodError,
    isLoading: neighborhoodLoading,
  } = useNeighborhood(selectedId!, { depth: 2, direction });
  const {
    data: overviewGraph,
    isError: overviewError,
    isLoading: overviewLoading,
  } = useConceptGraph({ limit: 150 }, selectedId === null);
  const [graph, setGraph] = useState<Neighborhood | null>(null);
  const [focusedNode, setFocusedNode] = useState<NeighborhoodNode | null>(null);
  const [hiddenPredicates, setHiddenPredicates] = useState<Set<string>>(new Set(DEFAULT_HIDDEN_PREDICATES));
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [expandingId, setExpandingId] = useState<number | null>(null);
  const { data: focusedDetail } = useConcept(focusedNode?.id ?? 0);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  // Working graph follows the mode: seed neighborhood or whole-graph overview.
  useEffect(() => {
    if (selectedId !== null && baseNeighborhood) {
      setGraph(baseNeighborhood);
      setFocusedNode(null);
    }
  }, [baseNeighborhood, selectedId]);

  useEffect(() => {
    if (selectedId === null && overviewGraph) {
      setGraph(overviewGraph);
      setFocusedNode(null);
    }
  }, [overviewGraph, selectedId]);

  const predicates = useMemo(() => {
    const set = new Set<string>();
    graph?.edges.forEach(e => set.add(e.predicate));
    return Array.from(set).sort();
  }, [graph]);

  const typeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    graph?.nodes.forEach(n => counts.set(n.type, (counts.get(n.type) || 0) + 1));
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [graph]);

  const togglePredicate = (p: string) => {
    setHiddenPredicates(prev => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p); else next.add(p);
      return next;
    });
  };

  const toggleType = (t: string) => {
    setHiddenTypes(prev => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  };

  const handleExpand = async (node: NeighborhoodNode) => {
    setExpandingId(node.id);
    try {
      const addition = await client.getConceptNeighborhood(node.id, { depth: 1, direction });
      setGraph(prev => prev ? mergeNeighborhoods(prev, addition) : addition);
    } finally {
      setExpandingId(null);
    }
  };

  const graphKey = selectedId === null ? 'overview' : `seed-${selectedId}`;
  const isLoading = selectedId === null ? overviewLoading : neighborhoodLoading;
  const loadError = selectedId === null ? overviewError : neighborhoodError;
  const isEmpty = (summary?.entities ?? 0) === 0;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1 min-h-0 h-full">
      {/* Left Col: Search & Summary */}
      <div className="flex flex-col gap-6 overflow-hidden h-full pb-4">
        <Card className="shrink-0 bg-card/50">
          <CardContent className="p-4">
            <div className="grid grid-cols-3 gap-2 text-center">
              <div>
                <div className="text-xl font-bold text-primary">{summary?.entities.toLocaleString() || 0}</div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Nodes</div>
              </div>
              <div>
                <div className="text-xl font-bold text-accent-foreground">{summary?.relationships.toLocaleString() || 0}</div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Edges</div>
              </div>
              <div>
                <div className="text-xl font-bold text-muted-foreground">{summary?.code_links.toLocaleString() || 0}</div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Code Links</div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="flex-1 flex flex-col overflow-hidden">
          <CardHeader className="pb-3 shrink-0">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search entities..."
                className="pl-9 bg-muted/50"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
          </CardHeader>
          <CardContent className="flex-1 overflow-auto p-0 px-2 pb-2">
            <div className="space-y-1">
              {searchLoading ? (
                <div className="p-4 text-center text-sm text-muted-foreground">Searching...</div>
              ) : searchResults?.length === 0 ? (
                <div className="p-4 text-center text-sm text-muted-foreground">No entities found.</div>
              ) : (
                searchResults?.map(entity => (
                  <button
                    key={entity.id}
                    onClick={() => setSelectedId(entity.id)}
                    className={`w-full text-left p-3 rounded-md transition-colors ${selectedId === entity.id ? 'bg-primary/20 border-primary/50' : 'hover:bg-muted border border-transparent'}`}
                  >
                    <div className="font-mono text-sm font-medium flex justify-between items-center">
                      <span className="flex items-center gap-2 truncate">
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: typeColor(entity.type) }} />
                        <span className="truncate">{entity.name}</span>
                      </span>
                      <span className="text-muted-foreground ml-2 text-xs shrink-0">{entity.degree ?? entity.mention_count} links</span>
                    </div>
                    <div className="flex gap-2 mt-2">
                      <Badge variant="secondary" className="text-[10px]">{entity.type}</Badge>
                      {entity.project && <Badge variant="outline" className="text-[10px]">{entity.project}</Badge>}
                    </div>
                  </button>
                ))
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Right Col: Viz */}
      <div className="lg:col-span-2 flex flex-col gap-3 mb-4 min-h-0">
        <div className="flex flex-wrap items-center gap-2 shrink-0 min-h-[26px]">
          {selectedId !== null && (
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => setSelectedId(null)}>
              <ArrowLeft className="w-3 h-3 mr-1" /> Full graph
            </Button>
          )}
          {selectedId !== null && (
            <Select value={direction} onValueChange={(value: 'both' | 'incoming' | 'outgoing') => setDirection(value)}>
              <SelectTrigger className="h-6 w-28 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="both">Both ways</SelectItem>
                <SelectItem value="outgoing">Outgoing</SelectItem>
                <SelectItem value="incoming">Incoming</SelectItem>
              </SelectContent>
            </Select>
          )}
          {typeCounts.map(([t, count]) => (
            <button
              key={t}
              onClick={() => toggleType(t)}
              title={hiddenTypes.has(t) ? `Show ${t} entities` : `Hide ${t} entities`}
              className={`text-[10px] font-mono px-2 py-1 rounded-full border transition-colors flex items-center gap-1.5 ${hiddenTypes.has(t) ? 'border-border text-muted-foreground opacity-40' : 'border-border bg-muted/40 text-foreground'}`}
            >
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: typeColor(t) }} />
              {t} <span className="text-muted-foreground">{count}</span>
            </button>
          ))}
          {typeCounts.length > 0 && predicates.length > 0 && (
            <span className="w-px h-4 bg-border mx-1" />
          )}
          {predicates.map(p => (
            <button
              key={p}
              onClick={() => togglePredicate(p)}
              title={hiddenPredicates.has(p) ? `Show ${p} relationships` : `Hide ${p} relationships`}
              className={`text-[10px] font-mono px-2 py-1 rounded-full border transition-colors ${hiddenPredicates.has(p) ? 'border-border text-muted-foreground opacity-40' : 'border-primary/50 bg-primary/10 text-primary'}`}
            >
              {p}
            </button>
          ))}
        </div>
        <div className="flex-1 border rounded-lg bg-card overflow-hidden flex flex-col relative shadow-inner">
          {isEmpty ? (
            <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-3 px-8 text-center">
              <GitGraph className="w-16 h-16 opacity-20" />
              <p className="font-medium text-foreground">No knowledge graph yet</p>
              <p className="text-sm max-w-sm">
                Run Build Concepts to extract entities and relationships from your stored memories,
                then explore them here.
              </p>
            </div>
          ) : graph && !isLoading ? (
            <>
              <GraphViz
                key={graphKey}
                neighborhood={graph}
                hiddenPredicates={hiddenPredicates}
                hiddenTypes={hiddenTypes}
                onNodeClick={setFocusedNode}
                focusedId={focusedNode?.id ?? null}
                expandingId={expandingId}
              />
              {focusedNode && (
                <ProvenancePanel
                  node={focusedNode}
                  detail={focusedDetail}
                  onClose={() => setFocusedNode(null)}
                  onExpand={() => handleExpand(focusedNode)}
                  onRecenter={() => setSelectedId(focusedNode.id)}
                  isExpanding={expandingId === focusedNode.id}
                />
              )}
            </>
          ) : loadError ? (
            <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-2">
              <AlertTriangle className="w-8 h-8 text-amber-500" />
              <p>{selectedId === null ? 'Could not load the knowledge graph.' : 'Could not load this neighborhood.'}</p>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-muted-foreground">
              Loading graph...
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DuplicatesTab() {
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

export function KnowledgePage() {
  const [buildOpen, setBuildOpen] = useState(false);

  return (
    <div className="p-8 flex flex-col h-full overflow-hidden">
      <div className="flex justify-between items-center mb-8 shrink-0">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Knowledge Graph</h1>
          <p className="text-muted-foreground text-sm mt-1">Extracted semantic network</p>
        </div>
        <Button onClick={() => setBuildOpen(true)} variant="secondary">
          <Layers className="w-4 h-4 mr-2" /> Build Concepts
        </Button>
      </div>

      <Tabs defaultValue="explorer" className="flex-1 flex flex-col overflow-hidden">
        <TabsList className="self-start shrink-0 mb-4 bg-transparent border-b rounded-none w-full justify-start p-0 h-auto">
          <TabsTrigger value="explorer" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none py-3 px-6">
            Explorer
          </TabsTrigger>
          <TabsTrigger value="duplicates" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none py-3 px-6">
            Duplicate Review
          </TabsTrigger>
        </TabsList>

        <div className="flex-1 overflow-hidden min-h-0">
          <TabsContent value="explorer" className="m-0 h-full">
            <ExplorerTab />
          </TabsContent>
          <TabsContent value="duplicates" className="m-0 h-full">
            <DuplicatesTab />
          </TabsContent>
        </div>
      </Tabs>

      <BuildConceptsDialog open={buildOpen} onOpenChange={setBuildOpen} />
    </div>
  );
}
