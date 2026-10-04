import { FolderCode, Network, FileCode2, Brain } from 'lucide-react';
import { StatCard } from '@/components/ui/panels';
import type { CodeContextMemory, CodeContextResult, CodeContextSymbol } from '@/lib/marm-types';

type CompositionSummaryProps = {
  composed: CodeContextResult;
  symbols: CodeContextSymbol[];
  memories: CodeContextMemory[];
  links: Array<Record<string, unknown>>;
};

export function CompositionSummary({ composed, symbols, memories, links }: CompositionSummaryProps) {
  return (
    <section
      className="mb-4 grid shrink-0 gap-3 sm:grid-cols-2 xl:grid-cols-4"
      aria-label="Composition summary"
    >
      <StatCard
        label="Project"
        value={composed.project?.short_name ?? '—'}
        detail={composed.project?.root_path ?? 'Resolved by the server'}
        icon={<FolderCode className="h-5 w-5" />}
        tone="cyan"
        delay={0}
      />
      <StatCard
        label="Call neighbourhood"
        value={(composed.graph_nodes ?? 0).toLocaleString()}
        detail="Nodes reached from the task's seed symbols"
        icon={<Network className="h-5 w-5" />}
        tone="violet"
        delay={55}
      />
      <StatCard
        label="Symbols shown"
        value={symbols.length.toLocaleString()}
        detail="Ranked by personalised PageRank"
        icon={<FileCode2 className="h-5 w-5" />}
        tone="teal"
        delay={110}
      />
      <StatCard
        label="Memory items"
        value={(memories.length + links.length).toLocaleString()}
        detail="Decisions, rationale and concept links"
        icon={<Brain className="h-5 w-5" />}
        tone="emerald"
        delay={165}
      />
    </section>
  );
}
