import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'wouter';
import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  cn,
} from '@/components/ui/core';
import { Panel, SectionHeading, SmallStat, StatCard } from '@/components/ui/panels';
import { ActionNoticePanel } from '@/components/memory/shared';
import { Sparkles, FileCode2, Brain, FileText, AlertTriangle, Network, FolderCode } from 'lucide-react';
import { useBuildCodeContext, useProjects, useRuntimeSettings, useStreamingAnswer } from '@/hooks/use-marm-queries';
import { MarmApiError } from '@/lib/marm-api';
import { CopyButton, LoadingState } from '@/components/code-context/shared';
import { SymbolsPane } from '@/components/code-context/SymbolsPane';
import { MemoryPane } from '@/components/code-context/MemoryPane';
import { CallGraphPane } from '@/components/code-context/CallGraphPane';
import { AnswerPane } from '@/components/code-context/AnswerPane';
import { AnswerEngineBar } from '@/components/code-context/AnswerEngineBar';

const DEFAULT_BUDGET = 12000;
const MAX_BUDGET = 100000;

/** Projects in the order a reader scans them: by the name they see.
 *
 *  The API returns them in index order, which puts the most recently touched
 *  at the bottom and reads as arbitrary to anyone looking for a name.
 *
 *  Sorts on `display_name` because that is what the option shows -- sorting on
 *  `name` would order a list by strings the reader cannot see. `localeCompare`
 *  rather than `<` so an accented name lands where it is expected instead of
 *  after Z by code point.
 */
export function sortProjectsByName<T extends { name: string; display_name?: string | null }>(
  projects: readonly T[] | undefined,
): T[] {
  return [...(projects ?? [])].sort((a, b) =>
    (a.display_name || a.name).localeCompare(b.display_name || b.name),
  );
}

/** Radix forbids `value=""` on a SelectItem, so the auto-detect option needs a
 *  sentinel. Kept rather than deleted: it is still correct for anyone running
 *  the Console from inside a repository rather than as a service. */
const AUTO_PROJECT = '__auto__';

/** The composition answers a task, not a query, so the placeholder shows the
 *  shape that ranks well: a question about behaviour, not a symbol name. */
const PLACEHOLDER = 'How does recall decide which memories to return?';

/** Described once and rendered twice — as the tab strip after a composition,
 *  and as the empty state before one. One source means the page cannot
 *  advertise a pane it does not then show. */
const PANES = [
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

/** Behaviour questions, not symbol names: ranking is seeded from the task's own
 *  words, so "how does X decide Y" composes a better neighbourhood than "X". */
const EXAMPLE_TASKS = [
  'How does recall decide which memories to return?',
  'Where is the distinctiveness gate applied?',
  'What would changing the ranking weights affect?',
];

/** What a pane will show, before there is anything to show.
 *
 *  Selecting a box used to switch to a tab that did not exist yet, because the
 *  whole strip was hidden until a composition returned. Now every box is always
 *  selectable and answers the question it raises: what is this one for?
 */
function PanePreview({ value }: { value: string }) {
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

export function CodeContextPage() {
  const [params, setParams] = useSearchParams();
  // Asking is opt-in per composition: generation is the slow step, and a
  // reader who only wants the ranked symbols should not wait for it.
  const [wantAnswer, setWantAnswer] = useState(true);
  const [tab, setTab] = useState('answer');
  const [task, setTask] = useState(() => params.get('task') ?? '');
  const [project, setProject] = useState(() => params.get('project') ?? '');
  const [budget, setBudget] = useState(() => Number(params.get('budget')) || DEFAULT_BUDGET);
  const { data: projects } = useProjects();
  // Same 5s poll the System page uses: free VRAM moves while a model is
  // loading, and a stale figure here is the one that misleads.
  const runtimeSettings = useRuntimeSettings();
  const build = useBuildCodeContext();
  const answer = useStreamingAnswer();
  const autoRan = useRef(false);

  // Default to a real project rather than to path resolution. The server
  // resolves an omitted project from the CONSOLE's working directory, which is
  // wherever the service was started — never the repository the reader has in
  // mind, and on a service install not an indexed project at all.
  useEffect(() => {
    if (!project && projects?.length) setProject(projects[0].name);
  }, [project, projects]);

  const sortedProjects = useMemo(() => sortProjectsByName(projects), [projects]);
  const selected = projects?.find((item) => item.name === project);
  const result = build.data;
  // A `no_project` or `unavailable` answer is rendered as a notice above, not
  // as panes. Branching on this once keeps the five panes from each having to
  // re-check the status.
  const composed = result?.status === 'success' ? result : undefined;
  const symbols = useMemo(() => result?.symbols ?? [], [result]);
  const memories = useMemo(() => result?.memories ?? [], [result]);
  const links = useMemo(() => result?.links ?? [], [result]);
  const edges = useMemo(() => result?.graph_edges ?? [], [result]);
  const notes = useMemo(() => result?.notes ?? [], [result]);
  const truncated = notes.some((note) => note.includes('budget'));
  const recallUnavailable = notes.some((note) => note.includes('recall unavailable'));

  // The budget that produced the displayed result. `result` carries task and
  // project but not budget, and reading the live form value meant the
  // truncation notice and its button described a request that had not run.
  const [composedBudget, setComposedBudget] = useState(DEFAULT_BUDGET);
  const compose = (
    nextTask: string,
    nextProject: string,
    nextBudget: number,
    withAnswer = wantAnswer,
  ) => {
    setComposedBudget(nextBudget);
    const scopedProject =
      nextProject && nextProject !== AUTO_PROJECT ? nextProject : null;
    // Two round trips on purpose. The composition returns in ~380 ms and fills
    // four panes; the answer takes seconds. Asking for both in one response
    // meant a reader waited 8.6 s to see anything at all.
    if (withAnswer) {
      answer.start({ task: nextTask, project: scopedProject, budget: nextBudget });
    } else {
      answer.reset();
    }
    build.mutate({
      task: nextTask,
      project: scopedProject,
      budget: nextBudget,
      include_graph: true,
      // The answer arrives on its own stream now, so the JSON body never waits
      // for generation.
      answer: false,
      // The page lays out symbols, source and memory bodies separately, so it
      // needs the structured fields the markdown duplicates. An agent does not,
      // which is why the server default is 1 rather than this.
      detail: 3,
    });
    setParams(
      (prev) => {
        prev.set('task', nextTask);
        if (nextProject) prev.set('project', nextProject);
        prev.set('budget', String(nextBudget));
        return prev;
      },
      { replace: true },
    );
  };

  // A deep link carries ?run=1 to compose on arrival. Latched, so neither a
  // re-render nor compose()'s own params write can fire it a second time.
  useEffect(() => {
    if (autoRan.current || params.get('run') !== '1') return;
    const seeded = params.get('task')?.trim();
    if (!seeded) return;
    // A link without ?project must wait for the default-project effect above.
    // Composing on the first render would send the empty string, and the server
    // then resolves the project from the CONSOLE's working directory -- which is
    // wherever the service was started, not the repository the link meant.
    const target = params.get('project') ?? project;
    if (!target) return;
    autoRan.current = true;
    compose(seeded, target, Number(params.get('budget')) || DEFAULT_BUDGET);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, project]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = task.trim();
    if (!trimmed) return;
    compose(trimmed, project, budget);
  };

  const errorMessage =
    build.error instanceof MarmApiError
      ? build.error.message
      : build.error
        ? 'Composing code context failed.'
        : null;

  return (
    <div className="page-enter flex h-full flex-col overflow-hidden p-7 xl:p-8">
      <div className="mx-auto flex h-full w-full max-w-[1560px] flex-col overflow-hidden">
        <header className="mb-6 shrink-0">
          <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">
            <Sparkles className="h-3 w-3" />
            Composed retrieval
          </div>
          <h1 className="text-[1.8rem] font-semibold tracking-[-0.045em]">Code Context</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Ask what you are trying to do. MARM ranks the symbols that matter for that task by personalised PageRank
            over the call graph, reads their source from disk, and joins what memory records about them — the same
            answer an agent receives from <code className="font-mono text-xs">marm_code_context</code>.
          </p>
          <AnswerEngineBar llm={runtimeSettings.data?.llm} hardware={runtimeSettings.data?.hardware} className="mt-4" />
        </header>

        <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {/* Above the form, and present before anything is composed. These are
              both the page's table of contents and its tab strip: five identical
              grey cards below an empty text box did not tell a reader what the
              page would do, and hiding the panes until a run made the page look
              unbuilt. Selecting one now previews what it will show. */}
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
              <Select value={project} onValueChange={setProject}>
                <SelectTrigger id="code-context-project" aria-label="Project" className="mt-1.5">
                  <SelectValue placeholder="Choose a project" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={AUTO_PROJECT}>Auto-detect from the Console's working directory</SelectItem>
                  {sortedProjects.map((item) => (
                    <SelectItem key={item.name} value={item.name} title={item.name}>
                      {item.display_name || item.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-40">
              <Label htmlFor="code-context-budget">Source budget</Label>
              <Input
                id="code-context-budget"
                type="number"
                min={500}
                max={MAX_BUDGET}
                step={500}
                value={budget}
                onChange={(event) => setBudget(Number(event.target.value))}
                className="mt-1.5"
              />
            </div>
            <label
              className="flex h-10 cursor-pointer select-none items-center gap-2 rounded-md border border-border/70 bg-muted/40 px-3 text-xs text-muted-foreground"
              title="Answer the question with the local model, grounded in the ranked context. Slower; the context itself does not need it."
            >
              <input
                type="checkbox"
                checked={wantAnswer}
                onChange={(event) => setWantAnswer(event.target.checked)}
                className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
              />
              Answer it too
            </label>
            <Button type="submit" isLoading={build.isPending} disabled={!task.trim()}>
              <Sparkles className="mr-2 h-4 w-4" /> Compose context
            </Button>
          </div>
        </form>

        {errorMessage && (
          <div className="mb-4 shrink-0">
            <ActionNoticePanel notice={{ kind: 'error', message: errorMessage }} />
          </div>
        )}

        {result && result.status !== 'success' && (
          <Panel
            className="mb-4 shrink-0"
            alert
            icon={<AlertTriangle className="h-5 w-5 text-amber-400" />}
            title={result.message ?? 'No context could be composed.'}
            description={result.hint}
          />
        )}

        {composed && (
          <>
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

            {truncated && (
              <div className="mb-4 flex shrink-0 flex-wrap items-center gap-3 rounded-lg border border-amber-400/30 bg-amber-400/[0.05] px-4 py-3 text-sm">
                <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
                <span>
                  Output was truncated at {budget.toLocaleString()} characters, so lower-ranked symbols were left out.
                </span>
                {/* The note was already the right diagnosis; it just was not
                    wired to the control that fixes it, 300px above. */}
                {budget < MAX_BUDGET && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="ml-auto"
                    onClick={() => {
                      const raised = Math.min(composedBudget * 2, MAX_BUDGET);
                      setBudget(raised);
                      // The request that produced THIS result, not whatever is
                      // in the form now. The control says "recompose", so
                      // editing the box first must not silently change what is
                      // re-run under that label.
                      compose(composed.task || task.trim(), composed.project?.name || project, raised);
                    }}
                  >
                    Raise to {Math.min(composedBudget * 2, MAX_BUDGET).toLocaleString()} and recompose
                  </Button>
                )}
              </div>
            )}
          </>
        )}

        {/* The panes live OUTSIDE the success guard. Each renders its real
            content when there is a composition and a preview of itself when
            there is not, so selecting a box always shows something rather than
            switching a tab that is not on the page yet. */}
        <div className="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
          {build.isPending && !composed && <LoadingState label="Composing code context…" />}

          <TabsContent value="answer" className="m-0">
            <AnswerPane
              result={composed}
              symbols={symbols}
              stream={answer}
              asking={build.isPending || answer.status === 'streaming'}
              canAsk={Boolean(task.trim())}
              onAsk={() => {
                setWantAnswer(true);
                compose(task.trim() || composed?.task || '', project, budget, true);
              }}
              onCite={(citation) => {
                // Jump to the evidence rather than describing where it is.
                setTab('symbols');
                window.setTimeout(() => {
                  document
                    .querySelector(`[data-symbol="${CSS.escape(citation.qualified_name)}"]`)
                    ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }, 60);
              }}
            />
          </TabsContent>
          <TabsContent value="symbols" className="m-0">
            {composed ? <SymbolsPane symbols={symbols} /> : <PanePreview value="symbols" />}
          </TabsContent>
          <TabsContent value="graph" className="m-0">
            {composed ? (
              <CallGraphPane symbols={symbols} edges={edges} nodeCount={composed.graph_nodes ?? 0} />
            ) : (
              <PanePreview value="graph" />
            )}
          </TabsContent>
          <TabsContent value="memory" className="m-0">
            {composed ? (
              <MemoryPane memories={memories} links={links} recallUnavailable={recallUnavailable} />
            ) : (
              <PanePreview value="memory" />
            )}
          </TabsContent>
          <TabsContent value="agent" className="m-0">
            {composed ? (
              <div className="relative">
                <CopyButton
                  className="absolute right-2 top-2 h-7 w-7"
                  value={composed.markdown ?? ''}
                  label="Copy the composed markdown"
                />
                <pre className="overflow-auto rounded-xl border border-border/70 bg-background/35 p-4 pr-12 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">
                  {composed.markdown}
                </pre>
              </div>
            ) : (
              <PanePreview value="agent" />
            )}
          </TabsContent>

          {/* The pane strip now describes every pane, so the old "what you get
              back" card grid would say the same thing twice. What stays is the
              part it never covered: a starting point, and what will be searched. */}
          {!composed && !errorMessage && !build.isPending && (
            <div className="mt-6 space-y-6">
              <section className="space-y-3">
                <SectionHeading
                  title="Try one"
                  description="Ranking is seeded from the task's own words, so a question about behaviour composes better context than a bare symbol name."
                />
                <div className="flex flex-wrap gap-2">
                  {EXAMPLE_TASKS.map((example) => (
                    <Button key={example} type="button" variant="outline" size="sm" onClick={() => setTask(example)}>
                      {example}
                    </Button>
                  ))}
                </div>
              </section>

              {selected && (
                <Panel
                  icon={<Network className="h-5 w-5 text-violet-300" />}
                  title={`Will search ${selected.display_name || selected.name}`}
                  description={selected.root_path}
                  alert={selected.status !== 'ready'}
                >
                  <div className="mt-4 grid gap-3 sm:grid-cols-3">
                    <SmallStat label="Graph nodes" value={selected.nodes.toLocaleString()} caption="Files and symbols" />
                    <SmallStat label="Graph edges" value={selected.edges.toLocaleString()} caption="Calls and imports" />
                    <SmallStat
                      label="Index status"
                      value={selected.status}
                      tone={selected.status === 'ready' ? 'good' : 'warn'}
                    />
                  </div>
                </Panel>
              )}
            </div>
          )}
        </div>
        </Tabs>

        <footer className="mt-4 shrink-0 border-t border-border/70 pt-3 text-[11px] text-muted-foreground">
          A high score means a symbol is well connected to the task's seed symbols in the call graph — it does not
          prove the symbol is where a change belongs. A <span className="font-mono">heuristic</span> edge is a name
          match and can bind across module boundaries. The memory pane shows only what someone chose to record;
          silence there is not evidence that nothing was decided.
        </footer>
      </div>
    </div>
  );
}
