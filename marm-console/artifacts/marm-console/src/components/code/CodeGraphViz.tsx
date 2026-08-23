import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { forceCollide } from 'd3-force';
import { Maximize2, ZoomIn, ZoomOut } from 'lucide-react';
import { Button } from '@/components/ui/core';
import type { CodeGraphSnapshot } from '@/lib/marm-types';

type ForceGraphEndpoint = string | { id: string };
type ForceGraphLink = { source: ForceGraphEndpoint; target: ForceGraphEndpoint; count: number };

const DIRECTORY_COLORS = ['#22d3ee', '#60a5fa', '#818cf8', '#a78bfa', '#34d399', '#f59e0b', '#f472b6'];

function endpointId(endpoint: ForceGraphEndpoint) {
  return typeof endpoint === 'object' ? endpoint.id : endpoint;
}

function directoryGroup(path: string) {
  const directories = path.split('/').filter(Boolean).slice(0, -1);
  if (directories.length === 0) return 'root';
  return directories.slice(-2).join('/');
}

function directoryColor(group: string) {
  let hash = 0;
  for (let index = 0; index < group.length; index += 1) hash = (hash * 31 + group.charCodeAt(index)) >>> 0;
  return DIRECTORY_COLORS[hash % DIRECTORY_COLORS.length];
}

export function buildCodeGraphData(graph: CodeGraphSnapshot, normalizedFilter: string) {
  const visibleNodes = graph.nodes.filter((node) => !normalizedFilter || node.path.toLowerCase().includes(normalizedFilter));
  const visibleIds = new Set(visibleNodes.map((node) => node.id));
  const links = graph.edges
    .filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
    .map((edge) => ({ ...edge }));
  const degree = new Map<string, number>();
  links.forEach((edge) => {
    degree.set(edge.source, (degree.get(edge.source) || 0) + edge.count);
    degree.set(edge.target, (degree.get(edge.target) || 0) + edge.count);
  });
  return {
    nodes: visibleNodes.map((node) => {
      const group = directoryGroup(node.path);
      return { ...node, degree: degree.get(node.id) || 0, group, color: directoryColor(group) };
    }),
    links,
  };
}

export function codeGraphNeighbours(links: ForceGraphLink[], selectedId: string | null) {
  if (!selectedId) return new Set<string>();
  const ids = new Set<string>([selectedId]);
  links.forEach((edge) => {
    const source = endpointId(edge.source);
    const target = endpointId(edge.target);
    if (source === selectedId) ids.add(target);
    if (target === selectedId) ids.add(source);
  });
  return ids;
}

export function CodeGraphViz({
  graph,
  filter,
  selectedId,
  onNodeClick,
}: {
  graph: CodeGraphSnapshot;
  filter: string;
  selectedId: string | null;
  onNodeClick: (nodeId: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [hoverId, setHoverId] = useState<string | null>(null);
  const configuredGraphRef = useRef<unknown>(null);
  const pendingFitRef = useRef(false);
  const didInitialFitRef = useRef(false);
  const normalizedFilter = filter.trim().toLowerCase();

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver(([entry]) => {
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const graphData = useMemo(() => {
    return buildCodeGraphData(graph, normalizedFilter);
  }, [graph, normalizedFilter]);

  const neighbours = useMemo(() => {
    return codeGraphNeighbours(graphData.links, selectedId || hoverId);
  }, [graphData.links, hoverId, selectedId]);

  const folderLegend = useMemo(() => {
    const counts = new Map<string, { color: string; count: number }>();
    graphData.nodes.forEach((node) => {
      const current = counts.get(node.group) || { color: node.color, count: 0 };
      current.count += 1;
      counts.set(node.group, current);
    });
    return [...counts.entries()].sort(([, a], [, b]) => b.count - a.count).slice(0, 4);
  }, [graphData.nodes]);

  useLayoutEffect(() => {
    const forceGraph = graphRef.current;
    if (!forceGraph || size.width === 0 || configuredGraphRef.current === graphData) return;
    const degreeById = new Map(graphData.nodes.map((node) => [node.id, node.degree]));
    forceGraph.d3Force('charge')
      ?.strength((node: any) => -Math.min(150, 60 + Math.sqrt(degreeById.get(node.id) || 0) * 15))
      .distanceMax(560);
    forceGraph.d3Force('link')
      ?.distance((edge: any) => 72 + Math.min(36, Math.log2((edge.count || 1) + 1) * 12))
      .strength(0.15);
    forceGraph.d3Force('collide', forceCollide((node: any) => {
      const degree = degreeById.get(node.id) || 0;
      return Math.max(8, Math.min(14, 5 + Math.log2(degree + 1) * 1.5));
    }).strength(0.9).iterations(2));
    configuredGraphRef.current = graphData;
    pendingFitRef.current = true;
    didInitialFitRef.current = false;
    forceGraph.d3ReheatSimulation();
  }, [graphData, size.height, size.width]);

  useEffect(() => {
    if (didInitialFitRef.current && size.width > 0) graphRef.current?.zoomToFit(0, 52);
  }, [size.height, size.width]);

  const paintNode = useCallback((node: any, ctx: CanvasRenderingContext2D, scale: number) => {
    const activeId = selectedId || hoverId;
    const selected = node.id === selectedId;
    const hovered = node.id === hoverId;
    const dimmed = !!activeId && !neighbours.has(node.id);
    const radius = Math.max(3.5, Math.min(8.5, 3.2 + Math.log2((node.degree || 0) + 1) * 1.25));
    ctx.globalAlpha = dimmed ? 0.14 : 1;
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius + 3, 0, 2 * Math.PI);
    ctx.fillStyle = selected || hovered ? 'rgba(226, 232, 240, .3)' : `${node.color}24`;
    ctx.fill();
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
    ctx.fillStyle = selected || hovered ? '#e0f2fe' : node.color;
    ctx.fill();
    if (selected || hovered) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, radius + 2, 0, 2 * Math.PI);
      ctx.strokeStyle = '#e0f2fe';
      ctx.lineWidth = 1.2 / scale;
      ctx.stroke();
    }
    if (!dimmed && (selected || hovered || scale > 3.5)) {
      const fontSize = Math.max(10 / scale, 2.6);
      ctx.font = `500 ${fontSize}px 'JetBrains Mono', monospace`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.lineWidth = 3 / scale;
      ctx.strokeStyle = 'rgba(4, 8, 16, .9)';
      ctx.strokeText(node.label, node.x, node.y + radius + 2 / scale);
      ctx.fillStyle = selected || hovered ? '#f8fafc' : '#cbd5e1';
      ctx.fillText(node.label, node.x, node.y + radius + 2 / scale);
    }
    ctx.globalAlpha = 1;
  }, [hoverId, neighbours, selectedId]);

  const linkColor = useCallback((edge: any) => {
    const source = typeof edge.source === 'object' ? edge.source.id : edge.source;
    const target = typeof edge.target === 'object' ? edge.target.id : edge.target;
    const activeId = selectedId || hoverId;
    if (!activeId) return 'rgba(34, 211, 238, .24)';
    return source === activeId || target === activeId
      ? 'rgba(56, 189, 248, .72)'
      : 'rgba(148, 163, 184, .05)';
  }, [hoverId, selectedId]);

  const handleEngineStop = useCallback(() => {
    if (!pendingFitRef.current || didInitialFitRef.current || !graphRef.current) return;
    pendingFitRef.current = false;
    didInitialFitRef.current = true;
    graphRef.current.zoomToFit(520, 52);
  }, []);

  const zoom = (factor: number) => {
    if (graphRef.current) graphRef.current.zoom(graphRef.current.zoom() * factor, 180);
  };

  return (
    <div ref={containerRef} className="knowledge-graph-surface absolute inset-0 overflow-hidden rounded-xl border border-cyan-400/20">
      {size.width > 0 && <ForceGraph2D
        ref={graphRef}
        width={size.width}
        height={size.height}
        graphData={graphData}
        backgroundColor="rgba(0,0,0,0)"
        nodeLabel={(node: any) => node.path}
        nodeCanvasObjectMode={() => 'replace'}
        nodeCanvasObject={paintNode}
        linkColor={linkColor}
        linkWidth={(edge: any) => Math.min(2.5, 0.75 + Math.log2(edge.count + 1) * 0.5)}
        linkDirectionalArrowLength={2.8}
        linkDirectionalArrowRelPos={1}
        linkDirectionalArrowColor={linkColor}
        onNodeClick={(node: any) => onNodeClick(node.id)}
        onNodeHover={(node: any) => setHoverId(node?.id || null)}
        onBackgroundClick={() => setHoverId(null)}
        onEngineStop={handleEngineStop}
        cooldownTime={2_600}
        cooldownTicks={240}
      />}
      <div className="pointer-events-none absolute left-3 top-3 rounded-lg border border-cyan-400/20 bg-background/75 px-3 py-2 backdrop-blur">
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-300">Visible topology</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{graphData.nodes.length} files · {graphData.links.length} import links</p>
      </div>
      {folderLegend.length > 1 && <div className="pointer-events-none absolute right-3 top-3 flex max-w-[52%] flex-wrap justify-end gap-1.5 rounded-lg border border-border/70 bg-background/75 px-2 py-1.5 backdrop-blur">{folderLegend.map(([group, info]) => <span key={group} className="flex max-w-28 items-center gap-1 truncate font-mono text-[10px] text-muted-foreground"><span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: info.color }} />{group}</span>)}</div>}
      <div className="absolute bottom-3 left-3 flex gap-1.5">
        <Button variant="secondary" size="icon" className="h-7 w-7 border border-border/70 bg-background/80" onClick={() => zoom(1.35)} title="Zoom in"><ZoomIn className="h-3.5 w-3.5" /></Button>
        <Button variant="secondary" size="icon" className="h-7 w-7 border border-border/70 bg-background/80" onClick={() => zoom(1 / 1.35)} title="Zoom out"><ZoomOut className="h-3.5 w-3.5" /></Button>
        <Button variant="secondary" size="icon" className="h-7 w-7 border border-border/70 bg-background/80" onClick={() => graphRef.current?.zoomToFit(300, 40)} title="Fit graph"><Maximize2 className="h-3.5 w-3.5" /></Button>
      </div>
      <p className="pointer-events-none absolute bottom-3 right-3 rounded bg-background/70 px-2 py-1 text-[10px] text-muted-foreground backdrop-blur">Hover to trace imports · click a file for details</p>
    </div>
  );
}
