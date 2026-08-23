import { describe, expect, it, vi } from 'vitest';

vi.mock('react-force-graph-2d', () => ({ default: () => null }));

import { buildCodeGraphData, codeGraphNeighbours } from './CodeGraphViz';
import type { CodeGraphSnapshot } from '@/lib/marm-types';

const graph: CodeGraphSnapshot = {
  state: 'ready',
  total: { code_units: 2, import_edges: 1 },
  rendered: { code_units: 2, import_edges: 1 },
  truncated: false,
  nodes: [
    { id: 'src/a.ts', label: 'a.ts', path: 'src/a.ts', kind: 'file', fan_in: 0, fan_out: 1 },
    { id: 'src/b.ts', label: 'b.ts', path: 'src/b.ts', kind: 'file', fan_in: 1, fan_out: 0 },
  ],
  edges: [{ source: 'src/a.ts', target: 'src/b.ts', relation: 'imports', count: 1 }],
};

describe('CodeGraphViz data adapter', () => {
  it('keeps cached edge identities immutable when the force engine mutates its links', () => {
    const first = buildCodeGraphData(graph, '');
    (first.links[0] as unknown as { source: { id: string } }).source = { id: 'src/a.ts' };
    (first.links[0] as unknown as { target: { id: string } }).target = { id: 'src/b.ts' };

    const filtered = buildCodeGraphData(graph, 'src');

    expect(graph.edges[0]).toMatchObject({ source: 'src/a.ts', target: 'src/b.ts' });
    expect(filtered.links).toEqual([{ source: 'src/a.ts', target: 'src/b.ts', relation: 'imports', count: 1 }]);
    expect(codeGraphNeighbours(first.links, 'src/a.ts')).toEqual(new Set(['src/a.ts', 'src/b.ts']));
  });
});
