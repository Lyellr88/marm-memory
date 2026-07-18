import type { Neighborhood, NeighborhoodNode, NeighborhoodEdge } from '@/lib/marm-types';

export const DEFAULT_HIDDEN_PREDICATES = new Set(['co_occurs_with']);

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

export function typeColor(type: string): string {
  return TYPE_COLORS[type] ?? OTHER_TYPE_COLOR;
}

export function nodeRadius(degree: number): number {
  return Math.min(2.5 + Math.sqrt(Math.max(degree, 1)) * 1.3, 13);
}

export function mergeNeighborhoods(base: Neighborhood, addition: Neighborhood): Neighborhood {
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
