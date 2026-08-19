import { useState, useEffect, useMemo } from 'react';
import { useConceptsSummary, useSearchConcepts, useNeighborhood, useConceptGraph, useConcept, useMarmConfig, useGraphAutoRefresh } from '@/hooks/use-marm-queries';
import { Card, CardContent, CardHeader, Input, Button, Badge, Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/core';
import { Search, GitGraph, Network, AlertTriangle, X, ArrowLeft } from 'lucide-react';
import type { Neighborhood, NeighborhoodNode, ConceptDetail } from '@/lib/marm-types';
import { DEFAULT_HIDDEN_PREDICATES, typeColor, mergeNeighborhoods } from './shared';
import { GraphViz } from './GraphViz';

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

export function ExplorerTab() {
  // Background indexing adds nodes with nobody watching. This component only
  // exists while the Explorer tab is showing, so the polling stops with it.
  useGraphAutoRefresh();
  const { data: summary } = useConceptsSummary();
  const { client } = useMarmConfig();
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const { data: searchResults, isLoading: searchLoading } = useSearchConcepts({ q: debouncedQ, limit: 10 });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showFullAtlas, setShowFullAtlas] = useState(false);
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
  } = useConceptGraph(selectedId === null, showFullAtlas);
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
  const rebuildRequired = overviewGraph?.schema_status === 'rebuild_required';

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
          {selectedId === null && overviewGraph && (
            <Badge variant="outline" className="h-6 text-[10px] font-mono">
              {overviewGraph.mode === 'full'
                ? `Full atlas · ${overviewGraph.rendered.nodes} nodes`
                : `Compact graph · ${overviewGraph.rendered.nodes}/${overviewGraph.total.nodes} nodes`}
            </Badge>
          )}
          {selectedId === null && overviewGraph?.truncated && !showFullAtlas && (
            <Button
              variant="outline"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => setShowFullAtlas(true)}
            >
              Render all {overviewGraph.total.nodes.toLocaleString()} nodes
            </Button>
          )}
          {selectedId === null && showFullAtlas && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => setShowFullAtlas(false)}
            >
              Use compact graph
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
          {rebuildRequired ? (
            <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-3 px-8 text-center">
              <AlertTriangle className="w-12 h-12 text-amber-500/70" />
              <p className="font-medium text-foreground">Concept rebuild required</p>
              <p className="text-sm max-w-md">
                Run Build Concepts for all memories once to add platform-safe graph scope.
              </p>
            </div>
          ) : isEmpty ? (
            <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-3 px-8 text-center">
              <GitGraph className="w-16 h-16 opacity-20" />
              <p className="font-medium text-foreground">No knowledge graph yet</p>
              <p className="text-sm max-w-sm">
                Run Build Concepts to extract entities and relationships from your stored memories,
                then explore them here.
              </p>
            </div>
          ) : loadError ? (
            <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-2">
              <AlertTriangle className="w-8 h-8 text-amber-500" />
              <p>{selectedId === null ? 'Could not load the knowledge graph.' : 'Could not load this neighborhood.'}</p>
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
                suppressBackgroundLinks={showFullAtlas && selectedId === null}
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
