import { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Label,
  Input,
  Spinner,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from '@/components/ui/core';
import { Sparkles, FileCode2, Brain, FileText, AlertTriangle, Network } from 'lucide-react';
import { useBuildCodeContext, useProjects } from '@/hooks/use-marm-queries';
import { MarmApiError } from '@/lib/marm-api';
import type { CodeContextResult, CodeContextSymbol } from '@/lib/marm-types';

const DEFAULT_BUDGET = 12000;

/** The composition answers a task, not a query, so the placeholder shows the
 *  shape that ranks well: a question about behaviour, not a symbol name. */
const PLACEHOLDER = 'How does recall decide which memories to return?';

/** Described once and rendered twice -- as the tab strip after a composition,
 *  and as the empty state before one. Keeping a single source means the page
 *  cannot promise a pane it does not then show. */
const PANES = [
  {
    value: 'symbols',
    icon: FileCode2,
    label: 'Ranked symbols',
    blurb:
      'The symbols that matter for the task, ranked by personalised PageRank over the call graph, each with its source read from disk and whether it matched the task or arrived via the call graph.',
  },
  {
    value: 'memory',
    icon: Brain,
    label: 'What memory knows',
    blurb:
      'Decisions, rationale and concept links MARM has stored about these symbols. This is the part no code index can supply.',
  },
  {
    value: 'agent',
    icon: FileText,
    label: 'Agent view',
    blurb:
      'The exact markdown an agent receives from marm_code_context, so you can see what the tool actually said rather than a re-rendering of it.',
  },
] as const;

/** Behaviour questions, not symbol names: ranking is seeded from the task's own
 *  words, so "how does X decide Y" composes a better neighbourhood than "X". */
const EXAMPLE_TASKS = [
  'How does recall decide which memories to return?',
  'Where is the distinctiveness gate applied?',
  'What would changing the ranking weights affect?',
];

function memoryText(memory: Record<string, unknown>): string {
  const raw = (memory.content ?? memory.summary ?? '') as string;
  return raw.split(/\s+/).join(' ').trim();
}

function linkText(link: Record<string, unknown>): string {
  const qualified = (link.qualified_name ?? link.graph_qualified_name ?? '') as string;
  const entity = (link.entity_name as string) || qualified.split('.').slice(-1)[0] || '?';
  const symbol = qualified.split('.').slice(-1)[0] || '?';
  const file = (link.file_path as string) || '';
  return `${entity} → ${symbol}${file ? ` (${file})` : ''}`;
}

function SymbolCard({ symbol }: { symbol: CodeContextSymbol }) {
  const location = symbol.file_path
    ? `${symbol.file_path}:${symbol.start_line}`
    : symbol.qualified_name;
  return (
    <div className="rounded-lg border border-border/70 bg-card/50">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border/70 px-4 py-3">
        <span className="font-mono text-sm font-semibold text-primary-highlight">{symbol.name}</span>
        {symbol.label && <Badge variant="secondary">{symbol.label}</Badge>}
        {/* Provenance, not decoration: a seeded symbol matched the task's own
            words, while the rest were pulled in by the call graph. */}
        <Badge variant={symbol.seeded ? 'default' : 'outline'}>
          {symbol.seeded ? 'matched the task' : 'via call graph'}
        </Badge>
        <span className="font-mono text-[11px] text-muted-foreground">{location}</span>
        <span className="ml-auto font-mono text-[11px] text-muted-foreground" title="Personalised PageRank score">
          {symbol.score.toFixed(5)}
        </span>
      </div>
      {symbol.source ? (
        <pre className="max-h-80 overflow-auto px-4 py-3 font-mono text-[12px] leading-relaxed">
          <code>{symbol.source}</code>
        </pre>
      ) : (
        <p className="px-4 py-3 text-sm text-muted-foreground">Source was not readable from disk.</p>
      )}
      {symbol.truncated && (
        <p className="border-t border-border/70 px-4 py-2 text-[11px] text-muted-foreground">
          Truncated to fit the character budget. Raise the budget to see the rest.
        </p>
      )}
    </div>
  );
}

function StatusNotice({ result }: { result: CodeContextResult }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-amber-500/35 bg-amber-500/[0.07] p-4">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
      <div className="min-w-0">
        <p className="text-sm">{result.message ?? 'No context could be composed.'}</p>
        {result.hint && <p className="mt-1 text-sm text-muted-foreground">{result.hint}</p>}
      </div>
    </div>
  );
}

export function CodeContextPage() {
  const [task, setTask] = useState('');
  const [project, setProject] = useState('');
  const [budget, setBudget] = useState(DEFAULT_BUDGET);
  const { data: projects } = useProjects();
  const build = useBuildCodeContext();

  // Default to a real project rather than to path resolution. The server
  // resolves an omitted project from the CONSOLE's working directory, which is
  // wherever the service was started -- never the repository the reader has in
  // mind, and on this deployment not an indexed project at all. Leaving it
  // blank by default made the first click return no_project every time.
  useEffect(() => {
    if (!project && projects?.length) setProject(projects[0].name);
  }, [project, projects]);

  const selected = projects?.find((item) => item.name === project);

  const result = build.data;
  const symbols = useMemo(() => result?.symbols ?? [], [result]);
  const memories = useMemo(() => result?.memories ?? [], [result]);
  const links = useMemo(() => result?.links ?? [], [result]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = task.trim();
    if (!trimmed) return;
    build.mutate({ task: trimmed, project: project || null, budget });
  };

  const errorMessage =
    build.error instanceof MarmApiError
      ? build.error.message
      : build.error
        ? 'Composing context failed.'
        : null;

  return (
    <div className="page-enter flex h-full flex-col overflow-hidden p-7 xl:p-8">
      <div className="mb-6 shrink-0">
        <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">Composed retrieval</div>
        <h1 className="text-[1.8rem] font-semibold tracking-[-0.045em]">Code Context</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Ask what you are trying to do. MARM ranks the symbols that matter for that task by personalised PageRank
          over the call graph, reads their source from disk, and joins what memory records about them — the same
          answer an agent receives from <code className="font-mono text-xs">marm_code_context</code>.
        </p>
      </div>

      <form onSubmit={submit} className="mb-6 shrink-0 space-y-3">
        <div>
          <Label htmlFor="code-context-task">Task</Label>
          <Textarea
            id="code-context-task"
            value={task}
            onChange={(event) => setTask(event.target.value)}
            placeholder={PLACEHOLDER}
            rows={2}
            maxLength={1000}
            className="mt-1.5"
          />
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[16rem] flex-1">
            <Label htmlFor="code-context-project">Project</Label>
            <select
              id="code-context-project"
              value={project}
              onChange={(event) => setProject(event.target.value)}
              className="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">Auto-detect from the Console's working directory</option>
              {projects?.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.display_name || item.name}
                </option>
              ))}
            </select>
          </div>
          <div className="w-40">
            <Label htmlFor="code-context-budget">Source budget</Label>
            <Input
              id="code-context-budget"
              type="number"
              min={500}
              max={100000}
              step={500}
              value={budget}
              onChange={(event) => setBudget(Number(event.target.value))}
              className="mt-1.5"
            />
          </div>
          <Button type="submit" disabled={!task.trim() || build.isPending}>
            {build.isPending ? <Spinner className="mr-2" size="sm" /> : <Sparkles className="mr-2 h-4 w-4" />}
            Compose context
          </Button>
        </div>
      </form>

      <div className="min-h-0 flex-1 overflow-auto">
        {errorMessage && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/[0.08] p-4 text-sm" role="alert">
            {errorMessage}
          </div>
        )}

        {result && result.status !== 'success' && <StatusNotice result={result} />}

        {result?.status === 'success' && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border border-border/70 bg-card/40 px-4 py-3 text-sm">
              <span>
                <span className="text-muted-foreground">Project </span>
                <span className="font-mono text-primary-highlight">{result.project?.short_name}</span>
              </span>
              <span>
                <span className="text-muted-foreground">Call neighbourhood </span>
                <span className="font-mono">{result.graph_nodes ?? 0} nodes</span>
              </span>
              <span>
                <span className="text-muted-foreground">Shown </span>
                <span className="font-mono">{symbols.length} symbols</span>
              </span>
              <span>
                <span className="text-muted-foreground">Memory </span>
                <span className="font-mono">{memories.length + links.length} items</span>
              </span>
            </div>

            {result.notes?.map((note) => (
              <p key={note} className="text-sm text-muted-foreground">{note}</p>
            ))}

            <Tabs defaultValue="symbols">
              <TabsList className="justify-start rounded-none border-0 bg-transparent p-0">
                {PANES.map((pane) => (
                  <TabsTrigger
                    key={pane.value}
                    value={pane.value}
                    className="rounded-none border-b-2 border-transparent px-5 py-3 data-[state=active]:border-primary data-[state=active]:bg-transparent"
                  >
                    <pane.icon className="mr-2 h-4 w-4" /> {pane.label}
                  </TabsTrigger>
                ))}
              </TabsList>

              <TabsContent value="symbols" className="mt-4 space-y-3">
                {symbols.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No indexed symbols matched this task.</p>
                ) : (
                  symbols.map((symbol) => <SymbolCard key={symbol.qualified_name || symbol.name} symbol={symbol} />)
                )}
              </TabsContent>

              <TabsContent value="memory" className="mt-4 space-y-2">
                {memories.length === 0 && links.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Memory records nothing about these symbols yet. This is the part no code index can supply.
                  </p>
                ) : (
                  <>
                    {memories.map((memory, index) => (
                      <p key={`memory-${index}`} className="rounded-lg border border-border/70 bg-card/40 px-4 py-3 text-sm">
                        {memoryText(memory)}
                      </p>
                    ))}
                    {links.map((link, index) => (
                      <p key={`link-${index}`} className="rounded-lg border border-border/70 bg-card/40 px-4 py-3 font-mono text-[12px]">
                        {linkText(link)}
                      </p>
                    ))}
                  </>
                )}
              </TabsContent>

              {/* The exact text an agent receives, so a Console user can see
                  what the tool actually said rather than a re-rendering of it. */}
              <TabsContent value="agent" className="mt-4">
                <pre className="overflow-auto rounded-lg border border-border/70 bg-card/40 p-4 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">
                  {result.markdown}
                </pre>
              </TabsContent>
            </Tabs>
          </div>
        )}

        {/* Everything above renders only once a composition exists, so without
            this the page reads as a single text box and reviewers reasonably
            conclude the panes were never built. */}
        {!result && !errorMessage && !build.isPending && (
          <div className="space-y-6">
            <div>
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                What you get back
              </h2>
              <div className="mt-3 grid gap-3 md:grid-cols-3">
                {PANES.map((pane) => (
                  <div key={pane.value} className="rounded-lg border border-border/70 bg-card/40 p-4">
                    <div className="flex items-center gap-2">
                      <pane.icon className="h-4 w-4 text-primary" />
                      <span className="text-sm font-medium">{pane.label}</span>
                    </div>
                    <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">{pane.blurb}</p>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                Try one
              </h2>
              <div className="mt-3 flex flex-wrap gap-2">
                {EXAMPLE_TASKS.map((example) => (
                  <button
                    key={example}
                    type="button"
                    onClick={() => setTask(example)}
                    className="rounded-full border border-border/70 px-3 py-1.5 text-[13px] text-muted-foreground transition-colors hover:border-primary/50 hover:bg-muted/60 hover:text-foreground"
                  >
                    {example}
                  </button>
                ))}
              </div>
              <p className="mt-3 text-[13px] text-muted-foreground">
                Ranking is seeded from the task's own words, so a question about behaviour
                ("how does X decide Y") composes better context than a bare symbol name.
              </p>
            </div>

            {selected && (
              <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border border-border/70 bg-card/40 px-4 py-3 text-sm">
                <span className="flex items-center gap-2">
                  <Network className="h-4 w-4 text-primary" />
                  <span className="text-muted-foreground">Will search </span>
                  <span className="font-mono text-primary-highlight">{selected.display_name || selected.name}</span>
                </span>
                <span>
                  <span className="text-muted-foreground">Code graph </span>
                  <span className="font-mono">{selected.nodes} nodes · {selected.edges} edges</span>
                </span>
                {/* An unindexed or mid-index project composes nothing, and saying
                    so here is cheaper than a no_project after a 30s wait. */}
                {selected.status !== 'ready' && (
                  <span className="text-amber-400">Index status: {selected.status}</span>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
