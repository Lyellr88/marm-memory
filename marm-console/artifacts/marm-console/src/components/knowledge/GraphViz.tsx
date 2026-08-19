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
  suppressBackgroundLinks,
}: {
  neighborhood: Neighborhood;
  hiddenPredicates: Set<string>;
  hiddenTypes: Set<string>;
  onNodeClick: (node: NeighborhoodNode) => void;
  focusedId: number | null;
  expandingId: number | null;
  suppressBackgroundLinks: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<any>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [hoverId, setHoverId] = useState<number | null>(null);
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);
  const didInitialFit = useRef(false);
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

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || !didInitialFit.current || dimensions.width === 0) return;
    fg.zoomToFit(reducedMotion ? 0 : 250, 24);
  }, [dimensions, reducedMotion]);

  const gData = useMemo(() => {
    const visibleNodeIds = new Set(
      neighborhood.nodes.filter(n => !hiddenTypes.has(n.type)).map(n => n.id)
    );
    const visibleEdges = neighborhood.edges.filter(
      e => !hiddenPredicates.has(e.predicate) && visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target)
    );
    // Focused neighborhoods omit stranded nodes, but the atlas must retain
    // isolated entities returned by its overview contract.
    const connected = new Set<number>();
    visibleEdges.forEach(e => { connected.add(e.source); connected.add(e.target); });
    if (neighborhood.seed_id !== null) connected.add(neighborhood.seed_id);
    if (focusedId !== null) connected.add(focusedId);
    const nodes = neighborhood.nodes
      .filter(n => visibleNodeIds.has(n.id) && (
        neighborhood.seed_id === null || connected.has(n.id)
      ))
      .map((n) => {
        return {
          id: n.id,
          name: n.name,
          type: n.type,
          degree: n.degree ?? n.mention_count,
          hiddenNeighborCount: n.hidden_neighbor_count,
          isSeed: n.id === neighborhood.seed_id,
        };
      });
    return {
      nodes,
      links: visibleEdges.map((e) => ({
        source: e.source,
        target: e.target,
        predicate: e.predicate,
        weight: e.weight ?? e.evidence_count ?? 1,
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

  const activeId = hoverId ?? focusedId;
  const activeNeighbors = activeId !== null ? adjacency.get(activeId) : null;
  const labelledHubIds = useMemo(() => {
    const maxLabels = gData.nodes.length > 300 ? 8 : 12;
    const labelBudget = Math.min(maxLabels, Math.max(4, Math.ceil(Math.sqrt(gData.nodes.length))));
    const ranked = [...gData.nodes].sort(
      (a: any, b: any) => b.degree - a.degree || a.id - b.id
    );
    const medianDegree = ranked.length
      ? ranked[Math.floor(ranked.length / 2)].degree
      : Infinity;
    return new Set(
      ranked
        .filter((node: any) => node.degree > medianDegree)
        .slice(0, labelBudget)
        .map((node: any) => node.id)
    );
  }, [gData.nodes]);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    const nodeCount = Math.max(gData.nodes.length, 1);
    const denseAtlas = nodeCount > 300;
    const chargeDistance = denseAtlas
      ? Math.max(620, Math.sqrt(nodeCount) * 30)
      : 360;
    const sampleDegree = new Map<number, number>();
    gData.links.forEach((link: any) => {
      const source = typeof link.source === 'object' ? link.source.id : link.source;
      const target = typeof link.target === 'object' ? link.target.id : link.target;
      sampleDegree.set(source, (sampleDegree.get(source) ?? 0) + 1);
      sampleDegree.set(target, (sampleDegree.get(target) ?? 0) + 1);
    });
    fg.d3Force('charge')
      ?.strength((node: any) => {
        if (!denseAtlas) return -Math.max(55, 110 - Math.log2(nodeCount) * 5);
        const connections = sampleDegree.get(node.id) ?? 1;
        return -Math.min(190, 58 + Math.sqrt(connections) * 8);
      })
      .distanceMax(chargeDistance);
    fg.d3Force('link')
      ?.distance((l: any) => {
        if (denseAtlas) return l.predicate === 'co_occurs_with' ? 68 : 92;
        return l.predicate === 'co_occurs_with' ? 36 : 50;
      })
      .strength((l: any) => {
        const weighted = Math.log2((l.weight ?? 1) + 1);
        if (!denseAtlas) return Math.min(0.25, 0.06 + weighted * 0.035);
        const source = typeof l.source === 'object' ? l.source.id : l.source;
        const target = typeof l.target === 'object' ? l.target.id : l.target;
        const weakerEndpoint = Math.min(
          sampleDegree.get(source) ?? 1,
          sampleDegree.get(target) ?? 1
        );
        const topologyScale = 1 / Math.sqrt(Math.max(1, weakerEndpoint));
        return Math.min(0.14, (0.055 + weighted * 0.025) * topologyScale);
      });
    fg.d3Force(
      'collide',
      forceCollide((n: any) => nodeRadius(n.degree) + (denseAtlas ? 4 : 2.5))
        .strength(0.85)
        .iterations(2)
    );
    didInitialFit.current = false;
    if (!pausedRef.current) fg.d3ReheatSimulation();
  }, [gData]);

  const handleEngineStop = useCallback(() => {
    const fg = fgRef.current;
    if (!fg) return;
    if (!didInitialFit.current) {
      didInitialFit.current = true;
      fg.zoomToFit(reducedMotion ? 0 : 500, 24);
      if (reducedMotion) {
        fg.pauseAnimation();
        pausedRef.current = true;
        setPaused(true);
      }
    }
  }, [reducedMotion]);

  const isDimmed = useCallback((id: number) => {
    if (activeId === null) return false;
    return id !== activeId && !activeNeighbors?.has(id);
  }, [activeId, activeNeighbors]);

  const paintNode = useCallback((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const denseAtlasScale = suppressBackgroundLinks ? 1.25 : gData.nodes.length > 300 ? 0.62 : 1;
    const r = nodeRadius(node.degree) * denseAtlasScale;
    const color = typeColor(node.type);
    const dimmed = isDimmed(node.id);
    const emphasized = node.id === activeId || node.isSeed;

    ctx.globalAlpha = dimmed ? 0.12 : 1;

    // Keep enough glow to identify hubs without merging dense clusters into a blob.
    if (!dimmed) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r * 1.55, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.globalAlpha = emphasized ? 0.2 : 0.08;
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
      emphasized || labelledHubIds.has(node.id) || globalScale > 3.2
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
  }, [activeId, focusedId, expandingId, isDimmed, labelledHubIds, gData.nodes.length, suppressBackgroundLinks]);

  const paintPointerArea = useCallback((node: any, color: string, ctx: CanvasRenderingContext2D) => {
    const denseAtlasScale = suppressBackgroundLinks ? 1.25 : gData.nodes.length > 300 ? 0.62 : 1;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(node.x, node.y, nodeRadius(node.degree) * denseAtlasScale + (suppressBackgroundLinks ? 22 : 5), 0, 2 * Math.PI);
    ctx.fill();
  }, [gData.nodes.length, suppressBackgroundLinks]);

  const linkColor = useCallback((link: any) => {
    const s = typeof link.source === 'object' ? link.source.id : link.source;
    const t = typeof link.target === 'object' ? link.target.id : link.target;
    if (activeId !== null) {
      if (s === activeId || t === activeId) return 'rgba(56, 189, 248, 0.55)';
      return 'rgba(148, 163, 184, 0.04)';
    }
    const evidence = Math.min(1, Math.log2((link.weight ?? 1) + 1) / 5);
    return link.predicate === 'co_occurs_with'
      ? `rgba(14, 116, 144, ${0.2 + evidence * 0.12})`
      : `rgba(125, 211, 252, ${0.28 + evidence * 0.2})`;
  }, [activeId]);

  const linkWidth = useCallback((link: any) => {
    const s = typeof link.source === 'object' ? link.source.id : link.source;
    const t = typeof link.target === 'object' ? link.target.id : link.target;
    if (activeId !== null && (s === activeId || t === activeId)) return 2.2;
    const evidenceWidth = Math.min(1.8, Math.log2((link.weight ?? 1) + 1) * 0.3);
    return link.predicate === 'co_occurs_with'
      ? 0.75 + evidenceWidth * 0.45
      : 0.9 + evidenceWidth;
  }, [activeId]);

  const linkVisible = useCallback((link: any) => {
    if (!suppressBackgroundLinks) return true;
    if (activeId === null) return false;
    const s = typeof link.source === 'object' ? link.source.id : link.source;
    const t = typeof link.target === 'object' ? link.target.id : link.target;
    return s === activeId || t === activeId;
  }, [activeId, suppressBackgroundLinks]);

  const arrowLength = useCallback((link: any) => {
    if (link.predicate === 'co_occurs_with') return 0;
    return linkVisible(link) ? 2.6 : 0;
  }, [linkVisible]);

  const togglePause = () => {
    const fg = fgRef.current;
    if (!fg) return;
    const nextPaused = !pausedRef.current;
    if (nextPaused) fg.pauseAnimation(); else fg.resumeAnimation();
    pausedRef.current = nextPaused;
    setPaused(nextPaused);
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
          linkVisibility={linkVisible}
          linkCurvature={suppressBackgroundLinks ? 0 : 0.12}
          linkDirectionalArrowLength={arrowLength}
          linkDirectionalArrowRelPos={1}
          onNodeHover={(node: any) => setHoverId(node ? node.id : null)}
          onNodeClick={(node: any) => {
            const full = neighborhood.nodes.find((n) => n.id === node.id);
            if (full) onNodeClick(full);
          }}
          onBackgroundClick={() => setHoverId(null)}
          onEngineStop={handleEngineStop}
          warmupTicks={gData.nodes.length > 300 ? 80 : 30}
          cooldownTicks={gData.nodes.length > 300 ? 320 : 180}
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
        <Button variant="secondary" size="icon" className="h-7 w-7 bg-black/50 backdrop-blur border border-border" onClick={() => fgRef.current?.zoomToFit(300, 24)} title="Fit to view">
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
