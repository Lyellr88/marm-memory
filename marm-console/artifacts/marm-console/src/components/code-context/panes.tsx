import { Sparkles, FileCode2, Brain, FileText, Network } from 'lucide-react';
import { TabsList, TabsTrigger, cn } from '@/components/ui/core';
import type { CodeContextMemory, CodeContextResult, CodeContextSymbol } from '@/lib/marm-types';

/** Described once and rendered twice — as the tab strip after a composition,
 *  and as the empty state before one. One source means the page cannot
 *  advertise a pane it does not then show. */
export const PANES = [
  {
    value: 'answer',
    summary: 'A grounded answer, cited back to the code',
    accent: 'text-rose-300',
    icon: Sparkles,
    label: 'Ask',
    tone: 'console-tab-rose',
    blurb:
      'A grounded answer to your question, written by a local model from the ranked context alone, citing the symbols it used. Nothing leaves this machine.',
  },
  {
    value: 'symbols',
    summary: 'The symbols that matter, with their source',
    accent: 'text-cyan-300',
    icon: FileCode2,
    label: 'Ranked symbols',
    tone: 'console-tab-cyan',
    blurb:
      'The symbols that matter for the task, ranked by personalised PageRank over the call graph, grouped by file, each with its source and how it was reached.',
  },
  {
    value: 'graph',
    summary: 'The call neighbourhood it ranked over',
    accent: 'text-violet-300',
    icon: Network,
    label: 'Call graph',
    tone: 'console-tab-violet',
    blurb:
      'The ranked call neighbourhood the scores were computed over. Node size is PageRank score.',
  },
  {
    value: 'memory',
    summary: 'Decisions and rationale MARM has stored',
    accent: 'text-emerald-300',
    icon: Brain,
    label: 'What memory knows',
    tone: 'console-tab-emerald',
    blurb:
      'Decisions, rationale and concept links MARM has stored about these symbols. This is the part no code index can supply.',
  },
  {
    value: 'agent',
    summary: 'The exact markdown an agent receives',
    accent: 'text-blue-300',
    icon: FileText,
    label: 'Agent view',
    tone: 'console-tab-blue',
    blurb:
      'The exact markdown an agent receives from marm_code_context, so you can see what the tool said rather than a re-rendering of it.',
  },
] as const;

/** What a pane will show, before there is anything to show.
 *
 *  Selecting a box used to switch to a tab that did not exist yet, because the
 *  whole strip was hidden until a composition returned. Now every box is always
 *  selectable and answers the question it raises: what is this one for?
 */
export function PanePreview({ value }: { value: string }) {
  const pane = PANES.find((item) => item.value === value);
  if (!pane) return null;
  return (
    <div
      className={cn(
        'console-tab console-tab-filled flex flex-col items-center rounded-xl border p-12 text-center',
        pane.tone,
      )}
    >
      <span className="console-tab-icon mb-4 flex h-11 w-11 items-center justify-center rounded-xl border">
        <pane.icon className="h-5 w-5" />
      </span>
      <p className="text-sm font-medium text-foreground/90">{pane.label}</p>
      <p className="mt-1.5 max-w-xl text-xs leading-relaxed text-muted-foreground">{pane.blurb}</p>
      <p className="mt-4 text-[11px] text-muted-foreground/80">
        Compose a task above to fill this pane.
      </p>
    </div>
  );
}

type PaneTabsProps = {
  result: CodeContextResult | undefined;
  symbols: CodeContextSymbol[];
  memories: CodeContextMemory[];
  links: Array<Record<string, unknown>>;
};

export function PaneTabs({ result, symbols, memories, links }: PaneTabsProps) {
  return (
    <TabsList className="mb-5 grid h-auto w-full shrink-0 grid-cols-2 gap-2 rounded-xl border border-card-border bg-card/40 p-2 shadow-[0_14px_40px_rgba(0,0,0,0.16)] md:grid-cols-3 lg:grid-cols-5">
      {PANES.map((pane, index) => {
        const count =
          !result || result.status !== 'success' || pane.value === 'answer' || pane.value === 'agent'
            ? null
            : pane.value === 'symbols'
              ? symbols.length
              : pane.value === 'graph'
                ? (result.graph_nodes ?? 0)
                : memories.length + links.length;
        return (
          <TabsTrigger
            key={pane.value}
            value={pane.value}
            title={pane.blurb}
            className={cn(
              'console-tab console-tab-filled metric-enter group relative h-auto flex-col items-start gap-1.5 overflow-hidden rounded-lg border px-3 py-2.5 text-left',
              pane.tone,
            )}
            style={{ animationDelay: `${index * 45}ms` }}
          >
            <span className="flex w-full items-center gap-2">
              <span className="console-tab-icon flex h-6 w-6 shrink-0 items-center justify-center rounded-md border transition-transform duration-200 group-hover:scale-105">
                <pane.icon className="h-3.5 w-3.5" />
              </span>
              <span className="min-w-0 flex-1 truncate text-xs font-semibold text-foreground">
                {pane.label}
              </span>
              {count !== null && (
                <span className="font-mono text-sm font-semibold tabular-nums text-foreground/90">
                  {count.toLocaleString()}
                </span>
              )}
            </span>
            <span className="line-clamp-2 w-full whitespace-normal text-[10.5px] leading-snug text-muted-foreground">
              {pane.summary}
            </span>
          </TabsTrigger>
        );
      })}
    </TabsList>
  );
}
