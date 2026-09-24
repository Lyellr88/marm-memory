import { useMemo, useState } from 'react';
import { Badge, Button, Input, cn } from '@/components/ui/core';
import { MemoryEmptyState } from '@/components/memory/shared';
import { ChevronDown, ChevronRight, Search } from 'lucide-react';
import type { CodeContextSymbol } from '@/lib/marm-types';
import { CopyButton } from './shared';

/** Risk comes from the graph engine on a traced edge. Variant by value is the
 *  idiom Explorer already uses for its impact table. */
function riskVariant(risk: string): 'destructive' | 'secondary' | 'outline' {
  const value = risk.toLowerCase();
  if (value === 'critical' || value === 'high') return 'destructive';
  if (value === 'medium') return 'secondary';
  return 'outline';
}

function ProvenanceBadges({ symbol }: { symbol: CodeContextSymbol }) {
  if (symbol.seeded) {
    return <Badge title="This symbol's name matched the task text">matched the task</Badge>;
  }
  const p = symbol.provenance;
  if (!p) return <Badge variant="outline">via call graph</Badge>;

  // `heuristic` is called out in amber on purpose. The ranker scales edge
  // weight by strategy precisely because heuristic binding invents cross-module
  // edges, so a reader who cannot see it cannot discount the row.
  const heuristic = p.strategy && p.strategy !== 'lsp';
  return (
    <>
      <Badge variant="outline" title="Hops away from a symbol that matched the task">
        {p.hop ? `${p.hop} hop` : 'via call graph'}
      </Badge>
      {p.strategy && (
        <Badge
          variant="outline"
          className={cn('font-mono', heuristic && 'border-amber-400/30 text-amber-300')}
          title={
            heuristic
              ? 'Resolved by name matching, which can bind across module boundaries — treat with suspicion'
              : 'Resolved by the language server'
          }
        >
          {p.strategy}
          {p.confidence ? ` ${p.confidence.toFixed(2)}` : ''}
        </Badge>
      )}
      {p.risk && (
        <Badge variant={riskVariant(p.risk)} className="text-[10px] uppercase" title="Risk label from the graph engine">
          {p.risk}
        </Badge>
      )}
    </>
  );
}

function SourceBlock({ symbol }: { symbol: CodeContextSymbol }) {
  if (!symbol.source) {
    return <p className="px-4 py-3 text-sm text-muted-foreground">Source was not readable from disk.</p>;
  }
  const lines = symbol.source.split('\n');
  const width = String(symbol.start_line + lines.length - 1).length;
  return (
    <pre className="max-h-80 overflow-auto bg-background/30 px-4 py-3 font-mono text-[12px] leading-relaxed">
      <code>
        {lines.map((line, i) => (
          <div key={i} className="flex">
            {/* Real file line numbers, not 1-based: you are about to open this
                file at this line, and a 1-based gutter would be a lie. */}
            <span
              aria-hidden="true"
              className="mr-4 shrink-0 select-none text-right tabular-nums text-muted-foreground/50"
              style={{ width: `${width}ch` }}
            >
              {symbol.start_line + i}
            </span>
            <span className="min-w-0 whitespace-pre-wrap">{line}</span>
          </div>
        ))}
      </code>
    </pre>
  );
}

function SymbolCard({ symbol, delay, top }: { symbol: CodeContextSymbol; delay: number; top: number }) {
  const location = symbol.file_path ? `${symbol.file_path}:${symbol.start_line}` : symbol.qualified_name;
  return (
    <div
      // Anchor for the Answer pane: a citation scrolls to the symbol it names,
      // so "it cites X" and "here is X" are one click apart rather than a
      // manual search through a filtered list.
      data-symbol={symbol.qualified_name}
      className="metric-enter scroll-mt-4 rounded-xl border border-border/80 bg-card/45 transition-transform duration-200 hover:-translate-y-px"
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-border/70 px-4 py-3">
        <span className="font-mono text-sm font-semibold text-primary-highlight">{symbol.name}</span>
        {symbol.label && <Badge variant="secondary">{symbol.label}</Badge>}
        <ProvenanceBadges symbol={symbol} />
        <span className="truncate font-mono text-[11px] text-muted-foreground" title={location}>
          {location}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <ScoreWeight score={symbol.score} top={top} />
          <CopyButton className="h-6 w-6" value={location} label={`Copy ${location}`} />
        </div>
      </div>
      <SourceBlock symbol={symbol} />
      {symbol.truncated && (
        <p className="border-t border-border/70 px-4 py-2 text-[11px] text-muted-foreground">
          Truncated to fit the character budget.
        </p>
      )}
    </div>
  );
}

/** The score range across one composition spans ~2,400x, which reads as
 *  undifferentiated text. The bar is relative to the top result, so it answers
 *  "how much does this matter compared to the best answer". */
function ScoreWeight({ score, top }: { score: number; top: number }) {
  const pct = Math.max(2, Math.min(100, (score / (top || 1)) * 100));
  return (
    <span className="flex items-center gap-1.5" title={`Personalised PageRank score ${score.toFixed(5)}`}>
      <span className="h-1 w-10 overflow-hidden rounded-full bg-muted">
        <span className="block h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
      </span>
      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">{score.toFixed(4)}</span>
    </span>
  );
}

export function SymbolsPane({ symbols }: { symbols: CodeContextSymbol[] }) {
  const [filter, setFilter] = useState('');
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const groups = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const matching = needle
      ? symbols.filter(
          (s) =>
            s.name.toLowerCase().includes(needle) ||
            s.file_path.toLowerCase().includes(needle) ||
            s.qualified_name.toLowerCase().includes(needle),
        )
      : symbols;

    const byFile = new Map<string, CodeContextSymbol[]>();
    for (const symbol of matching) {
      const file = symbol.file_path || 'unresolved';
      const bucket = byFile.get(file);
      if (bucket) bucket.push(symbol);
      else byFile.set(file, [symbol]);
    }
    // Files ordered by their best symbol, so the file holding the answer is
    // first — not the file that happens to contribute the most results.
    return [...byFile.entries()]
      .map(([file, items]) => ({ file, items, best: Math.max(...items.map((s) => s.score)) }))
      .sort((a, b) => b.best - a.best);
  }, [filter, symbols]);

  if (symbols.length === 0) {
    return (
      <MemoryEmptyState
        title="No indexed symbols matched this task"
        detail="Ranking is seeded from the task's own words, so a question about behaviour composes a better neighbourhood than a bare symbol name."
      />
    );
  }

  const shown = groups.reduce((n, g) => n + g.items.length, 0);
  const topScore = Math.max(...symbols.map((s) => s.score), 0);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[16rem] flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter by symbol or file…"
            aria-label="Filter symbols"
            className="bg-muted/50 pl-9 font-mono"
          />
        </div>
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
          {shown.toLocaleString()} of {symbols.length.toLocaleString()} in {groups.length.toLocaleString()} files
        </span>
      </div>

      {groups.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border/70 bg-background/25 p-4 text-sm text-muted-foreground">
          No symbol or file matches that filter.
        </p>
      ) : (
        groups.map((group) => {
          const isCollapsed = collapsed.has(group.file);
          return (
            <div key={group.file} className="rounded-xl border border-border/70 bg-background/20">
              <div className="flex items-center gap-2 px-3 py-2">
                <button
                  type="button"
                  onClick={() =>
                    setCollapsed((prev) => {
                      const next = new Set(prev);
                      if (next.has(group.file)) next.delete(group.file);
                      else next.add(group.file);
                      return next;
                    })
                  }
                  aria-expanded={!isCollapsed}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                >
                  {isCollapsed ? (
                    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  ) : (
                    <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  )}
                  <span className="truncate font-mono text-xs text-foreground/90" title={group.file}>
                    {group.file}
                  </span>
                  <Badge variant="outline" className="shrink-0 font-mono text-[10px]">
                    {group.items.length}
                  </Badge>
                </button>
                <CopyButton className="h-6 w-6 shrink-0" value={group.file} label={`Copy ${group.file}`} />
              </div>
              {!isCollapsed && (
                <div className="space-y-3 px-3 pb-3">
                  {group.items.map((symbol, index) => (
                    <SymbolCard
                      key={symbol.qualified_name || symbol.name}
                      symbol={symbol}
                      delay={index * 45}
                      top={topScore}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
