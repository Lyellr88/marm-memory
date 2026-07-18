import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { forceCollide } from 'd3-force';
import { Badge, Button } from '@/components/ui/core';
import { Play, Pause, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';
import type { Neighborhood, NeighborhoodNode } from '@/lib/marm-types';
import { typeColor, nodeRadius } from './shared';

export function GraphViz({
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
