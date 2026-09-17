import { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { MemoryEmptyState } from '@/components/memory/shared';
import type { CodeContextSymbol } from '@/lib/marm-types';

/** The ranked call neighbourhood.
 *
 *  Deliberately not CodeGraphViz. That component is a file-import visualiser:
 *  its props take a CodeGraphSnapshot whose node `kind` is the literal 'file'
 *  and whose edge `relation` is the literal 'imports', it groups and colours by
 *  directory, and it sizes nodes from fan_in/fan_out. Widening those literals
 *  to carry symbol-level call edges would weaken types that a working page
 *  depends on, so this is a second, much smaller component over the same
 *  already-bundled force-graph dependency.
 */
export function CallGraphPane({
  symbols,
  edges,
  onSelect,
}: {
  symbols: CodeContextSymbol[];
  edges: Array<[string, string, number]>;
  onSelect?: (qualifiedName: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver(([entry]) => {
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const data = useMemo(() => {
    const byName = new Map(symbols.map((s) => [s.qualified_name, s]));
    const top = Math.max(...symbols.map((s) => s.score), 0) || 1;
    const ids = new Set<string>();
    for (const [source, target] of edges) {
      ids.add(source);
      ids.add(target);
    }
    const nodes = [...ids].map((id) => {
      const symbol = byName.get(id);
      return {
        id,
        // A node in the neighbourhood that did not make the character budget
        // still shapes the ranking, so it is drawn — dimmed, and labelled by
        // its last segment because a qualified name is unreadable at this size.
        name: symbol?.name || id.split('.').slice(-1)[0] || id,
        score: symbol?.score ?? 0,
        inContext: Boolean(symbol),
        seeded: Boolean(symbol?.seeded),
        val: 2 + ((symbol?.score ?? 0) / top) * 10,
      };
    });
    return {
      nodes,
      links: edges.map(([source, target, weight]) => ({ source, target, weight })),
    };
  }, [edges, symbols]);

  if (edges.length === 0) {
    return (
      <MemoryEmptyState
        title="No call edges in this neighbourhood"
        detail="Every shown symbol matched the task directly, so there were no caller or callee hops to rank over."
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="graph-metrics-rail flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg px-4 py-2 text-xs">
        <span className="graph-metric">
          <span className="text-muted-foreground">Nodes </span>
          <span className="font-mono tabular-nums">{data.nodes.length.toLocaleString()}</span>
        </span>
        <span className="graph-metric">
          <span className="text-muted-foreground">Call edges </span>
          <span className="font-mono tabular-nums">{edges.length.toLocaleString()}</span>
        </span>
        <span className="text-muted-foreground">
          Size is PageRank score · filled nodes matched the task · dimmed nodes shape the ranking but were not shown
        </span>
      </div>
      <div
        ref={containerRef}
        className="force-graph-container knowledge-graph-surface h-[32rem] overflow-hidden rounded-xl border border-border/70"
      >
        {size.width > 0 && (
          <ForceGraph2D
            width={size.width}
            height={size.height}
            graphData={data}
            backgroundColor="transparent"
            nodeLabel={(node: any) => `${node.id}\nscore ${node.score.toFixed(5)}`}
            nodeVal={(node: any) => node.val}
            nodeColor={(node: any) =>
              node.seeded ? '#20b8f4' : node.inContext ? '#7bdcff' : '#3b5570'
            }
            linkColor={() => 'rgba(123, 220, 255, 0.18)'}
            linkWidth={(link: any) => 0.4 + (link.weight || 0) * 1.6}
            linkDirectionalArrowLength={3}
            linkDirectionalArrowRelPos={1}
            onNodeClick={(node: any) => onSelect?.(String(node.id))}
            cooldownTicks={80}
          />
        )}
      </div>
    </div>
  );
}
