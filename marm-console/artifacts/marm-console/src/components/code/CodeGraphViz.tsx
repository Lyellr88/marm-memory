import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { Maximize2, ZoomIn, ZoomOut } from 'lucide-react';
import { Button } from '@/components/ui/core';
import type { CodeGraphSnapshot } from '@/lib/marm-types';

type ForceGraphEndpoint = string | { id: string };
type ForceGraphLink = { source: ForceGraphEndpoint; target: ForceGraphEndpoint; count: number };

function endpointId(endpoint: ForceGraphEndpoint) {
  return typeof endpoint === 'object' ? endpoint.id : endpoint;
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
    nodes: visibleNodes.map((node) => ({ ...node, degree: degree.get(node.id) || 0 })),
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
    return codeGraphNeighbours(graphData.links, selectedId);
  }, [graphData.links, selectedId]);

  const paintNode = useCallback((node: any, ctx: CanvasRenderingContext2D, scale: number) => {
    const selected = node.id === selectedId;
    const dimmed = !!selectedId && !neighbours.has(node.id);
    const radius = Math.max(4, Math.min(13, 4 + Math.sqrt(node.degree || 0) * 1.25));
    ctx.globalAlpha = dimmed ? 0.14 : 1;
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius + 3, 0, 2 * Math.PI);
    ctx.fillStyle = selected ? 'rgba(56, 189, 248, .27)' : 'rgba(34, 211, 238, .10)';
    ctx.fill();
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
    ctx.fillStyle = selected ? '#38bdf8' : '#0e7490';
    ctx.fill();
    if (selected) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, radius + 2, 0, 2 * Math.PI);
      ctx.strokeStyle = '#e0f2fe';
      ctx.lineWidth = 1.2 / scale;
      ctx.stroke();
    }
    if (!dimmed && (selected || node.degree > 2 || scale > 2.7)) {
      const fontSize = Math.max(10 / scale, 2.6);
      ctx.font = `500 ${fontSize}px 'JetBrains Mono', monospace`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.lineWidth = 3 / scale;
      ctx.strokeStyle = 'rgba(4, 8, 16, .9)';
      ctx.strokeText(node.label, node.x, node.y + radius + 2 / scale);
      ctx.fillStyle = '#cbd5e1';
      ctx.fillText(node.label, node.x, node.y + radius + 2 / scale);
    }
    ctx.globalAlpha = 1;
  }, [neighbours, selectedId]);

  const linkColor = useCallback((edge: any) => {
    const source = typeof edge.source === 'object' ? edge.source.id : edge.source;
    const target = typeof edge.target === 'object' ? edge.target.id : edge.target;
    if (!selectedId) return 'rgba(34, 211, 238, .24)';
    return source === selectedId || target === selectedId
      ? 'rgba(56, 189, 248, .72)'
      : 'rgba(148, 163, 184, .05)';
  }, [selectedId]);

  useEffect(() => {
    if (graphRef.current && size.width) graphRef.current.zoomToFit(350, 40);
  }, [graphData, size.width, size.height]);

  const zoom = (factor: number) => {
    if (graphRef.current) graphRef.current.zoom(graphRef.current.zoom() * factor, 180);
  };

  return (
    <div ref={containerRef} className="relative h-full min-h-[22rem] overflow-hidden rounded-xl border border-cyan-400/20 bg-[radial-gradient(circle_at_top,rgba(8,47,73,.46),transparent_48%),hsl(var(--background))]">
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
        cooldownTime={1_800}
        cooldownTicks={160}
      />}
      <div className="pointer-events-none absolute left-3 top-3 rounded-lg border border-cyan-400/20 bg-background/75 px-3 py-2 backdrop-blur">
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-300">Visible topology</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{graphData.nodes.length} files · {graphData.links.length} import links</p>
      </div>
      <div className="absolute bottom-3 left-3 flex gap-1.5">
        <Button variant="secondary" size="icon" className="h-7 w-7 border border-border/70 bg-background/80" onClick={() => zoom(1.35)} title="Zoom in"><ZoomIn className="h-3.5 w-3.5" /></Button>
        <Button variant="secondary" size="icon" className="h-7 w-7 border border-border/70 bg-background/80" onClick={() => zoom(1 / 1.35)} title="Zoom out"><ZoomOut className="h-3.5 w-3.5" /></Button>
        <Button variant="secondary" size="icon" className="h-7 w-7 border border-border/70 bg-background/80" onClick={() => graphRef.current?.zoomToFit(300, 40)} title="Fit graph"><Maximize2 className="h-3.5 w-3.5" /></Button>
      </div>
      <p className="pointer-events-none absolute bottom-3 right-3 rounded bg-background/70 px-2 py-1 text-[10px] text-muted-foreground backdrop-blur">Select a file to isolate its visible imports</p>
    </div>
  );
}
