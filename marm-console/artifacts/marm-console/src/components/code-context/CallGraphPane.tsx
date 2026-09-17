import { useMemo, useState } from 'react';
import { GraphViz } from '@/components/knowledge/GraphViz';
import { MemoryEmptyState } from '@/components/memory/shared';
import { Badge } from '@/components/ui/core';
import type {
  CodeContextSymbol,
  Neighborhood,
  NeighborhoodNode,
} from '@/lib/marm-types';

/** Adapt a composed call neighbourhood onto the Knowledge Graph's renderer.
 *
 *  This pane used to own a second force-graph component. That was wrong in two
 *  directions: it duplicated a renderer the app already had, and it was the
 *  poorer of the two — `GraphViz` has pause, zoom, fit-to-view, collision
 *  spacing, hover and focus handling, and honours prefers-reduced-motion, none
 *  of which the bespoke one did.
 *
 *  The earlier note here argued against reusing `CodeGraphViz`, and that
 *  argument still holds: it is a file-import visualiser whose node `kind` is
 *  the literal 'file'. But it aimed at the wrong component. `GraphViz` is
 *  generic over a `Neighborhood`, so only the DATA needs adapting, and the two
 *  graphs are never on screen together — they are different sidebar pages — so
 *  sharing it costs nothing at runtime.
 */
function toNeighborhood(
  symbols: CodeContextSymbol[],
  edges: Array<[string, string, number]>,
): { graph: Neighborhood; byId: Map<number, CodeContextSymbol> } {
  const index = new Map<string, number>();
  const byId = new Map<number, CodeContextSymbol>();
  const nodes: NeighborhoodNode[] = [];

  // Degree drives node radius in the shared renderer, so it is counted from the
  // edges rather than left at zero — otherwise every symbol renders identically
  // and the structure the pane exists to show is invisible.
  const degree = new Map<string, number>();
  for (const [source, target] of edges) {
    degree.set(source, (degree.get(source) ?? 0) + 1);
    degree.set(target, (degree.get(target) ?? 0) + 1);
  }

  const ensure = (qualified: string, symbol?: CodeContextSymbol): number => {
    const existing = index.get(qualified);
    if (existing !== undefined) return existing;
    const id = nodes.length + 1;
    index.set(qualified, id);
    nodes.push({
      id,
      name: symbol?.name || qualified.split(/[.:]/).pop() || qualified,
      // `type` is what colours a node in the shared renderer. Seeded versus
      // reached-by-call is the distinction that matters here: which symbols
      // answered the task, and which were pulled in around them.
      type: symbol?.seeded ? 'tool' : 'concept',
      session_name: null,
      project: symbol?.file_path ?? null,
      mention_count: 0,
      degree: degree.get(qualified) ?? 0,
      hidden_neighbor_count: 0,
      linked_code: [],
    });
    if (symbol) byId.set(id, symbol);
    return id;
  };

  for (const symbol of symbols) ensure(symbol.qualified_name || symbol.name, symbol);

  const graphEdges = edges.map(([source, target, weight], i) => ({
    id: i + 1,
    source: ensure(source),
    target: ensure(target),
    predicate: 'calls',
    memory_id: null,
    weight,
  }));

  return {
    graph: {
      seed_id: null,
      nodes,
      edges: graphEdges,
      limits: { nodes: nodes.length, edges: graphEdges.length },
      truncated: false,
    },
    byId,
  };
}

export function CallGraphPane({
  symbols,
  edges,
  nodeCount = 0,
}: {
  symbols: CodeContextSymbol[];
  edges?: Array<[string, string, number]>;
  nodeCount?: number;
}) {
  const [selected, setSelected] = useState<CodeContextSymbol | null>(null);
  const { graph, byId } = useMemo(
    () => toNeighborhood(symbols, edges ?? []),
    [symbols, edges],
  );

  if (!edges || edges.length === 0) {
    return (
      <MemoryEmptyState
        title="No call edges were returned"
        detail={
          nodeCount > 0
            ? `Ranking reached ${nodeCount.toLocaleString()} nodes, but every returned symbol matched the task directly — there were no caller or callee hops left to draw.`
            : 'Ranking found no call neighbourhood for this task. A question about behaviour usually reaches further than a bare symbol name.'
        }
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
        <span className="graph-metric font-mono tabular-nums">
          {graph.nodes.length.toLocaleString()} nodes
        </span>
        <span className="graph-metric font-mono tabular-nums">
          {graph.edges.length.toLocaleString()} call edges
        </span>
        <Badge variant="outline" className="border-emerald-400/30 text-emerald-300">
          matched the task
        </Badge>
        <Badge variant="outline" className="border-sky-400/30 text-sky-300">
          reached via the call graph
        </Badge>
        <span className="ml-auto">Node size is how many calls touch it. Click one to read it.</span>
      </div>

      <div className="knowledge-graph-surface force-graph-container h-[460px] overflow-hidden rounded-xl border border-border/70">
        <GraphViz
          neighborhood={graph}
          hiddenPredicates={new Set()}
          hiddenTypes={new Set()}
          focusedId={null}
          expandingId={null}
          onNodeClick={(node) => setSelected(byId.get(node.id) ?? null)}
        />
      </div>

      {selected && (
        <div className="rounded-xl border border-border/80 bg-card/45 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-semibold text-primary-highlight">
              {selected.name}
            </span>
            {selected.label && <Badge variant="secondary">{selected.label}</Badge>}
            <span className="font-mono text-[11px] text-muted-foreground">
              {selected.file_path}:{selected.start_line}
            </span>
          </div>
          {selected.source && (
            <pre className="mt-2 max-h-56 overflow-auto rounded-lg bg-background/30 px-3 py-2 font-mono text-[12px] leading-relaxed">
              <code>{selected.source}</code>
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
