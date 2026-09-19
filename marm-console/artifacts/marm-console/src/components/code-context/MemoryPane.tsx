import { Badge, cn } from '@/components/ui/core';
import { MemoryEmptyState, memoryContext } from '@/components/memory/shared';
import { AlertTriangle } from 'lucide-react';
import type { CodeContextMemory } from '@/lib/marm-types';

function when(timestamp?: string): string | null {
  if (!timestamp) return null;
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toLocaleString();
}

function text(memory: CodeContextMemory): string {
  return String(memory.content ?? memory.summary ?? '').split(/\s+/).join(' ').trim();
}

function MemoryCard({ memory }: { memory: CodeContextMemory }) {
  const context = memoryContext(memory.context_type ?? null);
  const Icon = context.icon;
  const stamp = when(memory.timestamp);
  return (
    <div className={cn('rounded-lg border border-l-2 border-border/70 bg-card/45 p-4', context.rail)}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className={cn('flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase', context.tone)}>
          <Icon className="h-3 w-3" />
          {memory.context_type || 'general'}
        </span>
        {typeof memory.similarity === 'number' && (
          <span className="font-mono text-sm text-amber-500" title="Semantic similarity to the probe that found it">
            {memory.similarity.toFixed(3)}
          </span>
        )}
        {memory.session_name && (
          <Badge variant="outline" className="font-mono text-[10px]">
            {memory.session_name}
          </Badge>
        )}
        {memory.platform && (
          <Badge variant="outline" className="text-[10px]">
            {memory.platform}
          </Badge>
        )}
        {stamp && <span className="ml-auto text-[11px] text-muted-foreground">{stamp}</span>}
      </div>
      <p className="text-sm">{text(memory)}</p>
    </div>
  );
}

function linkText(link: Record<string, unknown>): string {
  const qualified = String(link.qualified_name ?? link.graph_qualified_name ?? '');
  const entity = String(link.entity_name ?? '') || qualified.split('.').slice(-1)[0] || '?';
  const symbol = qualified.split('.').slice(-1)[0] || '?';
  const file = String(link.file_path ?? '');
  return `${entity} → ${symbol}${file ? ` (${file})` : ''}`;
}

export function MemoryPane({
  memories,
  links,
  recallUnavailable,
}: {
  memories: CodeContextMemory[];
  links: Array<Record<string, unknown>>;
  recallUnavailable: boolean;
}) {
  // Silence has two causes and they are not the same claim. Saying "memory
  // records nothing" when recall never ran is a lie the page used to tell.
  if (recallUnavailable) {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-amber-400/30 bg-amber-400/[0.05] p-4">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
        <div>
          <p className="text-sm font-medium text-foreground">Memory recall was unavailable</p>
          <p className="mt-1 text-sm text-muted-foreground">
            This pane is empty because recall could not run, not because memory knows nothing about these symbols.
          </p>
        </div>
      </div>
    );
  }

  if (memories.length === 0 && links.length === 0) {
    return (
      <MemoryEmptyState
        title="Memory records nothing about these symbols yet"
        detail="This is the part no code index can supply — decisions and rationale someone chose to write down."
      />
    );
  }

  return (
    <div className="space-y-2">
      {memories.map((memory, index) => (
        <MemoryCard key={String(memory.id ?? index)} memory={memory} />
      ))}
      {links.map((link, index) => (
        <p
          key={`link-${index}`}
          className="break-all rounded-lg border border-border/70 bg-background/35 p-3 font-mono text-xs text-muted-foreground"
        >
          {linkText(link)}
        </p>
      ))}
    </div>
  );
}
