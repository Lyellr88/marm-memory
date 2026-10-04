import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'wouter';
import { Button, Tabs, TabsContent } from '@/components/ui/core';
import { Panel } from '@/components/ui/panels';
import { ActionNoticePanel } from '@/components/memory/shared';
import { Sparkles, AlertTriangle } from 'lucide-react';
import { useBuildCodeContext, useProjects, useRuntimeSettings, useStreamingAnswer } from '@/hooks/use-marm-queries';
import { MarmApiError } from '@/lib/marm-api';
import type { AnalystMode } from '@/lib/marm-types';
import { CopyButton, LoadingState } from '@/components/code-context/shared';
import { SymbolsPane } from '@/components/code-context/SymbolsPane';
import { MemoryPane } from '@/components/code-context/MemoryPane';
import { CallGraphPane } from '@/components/code-context/CallGraphPane';
import { AnswerPane } from '@/components/code-context/AnswerPane';
import { AnswerEngineBar } from '@/components/code-context/AnswerEngineBar';
import { PaneTabs, PanePreview } from '@/components/code-context/panes';
import { ComposeForm, DEFAULT_BUDGET, MAX_BUDGET, AUTO_PROJECT } from '@/components/code-context/ComposeForm';
import { CompositionSummary } from '@/components/code-context/CompositionSummary';
import { ComposeStarter } from '@/components/code-context/ComposeStarter';

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

export function CodeContextPage() {
  const [params, setParams] = useSearchParams();
  // Asking is opt-in per composition: generation is the slow step, a reader
  // who only wants the ranked symbols should not wait for it, and a running
  // model must not make it part of the workflow by default.
  const [wantAnswer, setWantAnswer] = useState(false);
  // What happens to the answer's results. Read-only is the default: the
  // other two stage proposals, and under guardrails MARM may apply them.
  const [analystMode, setAnalystMode] = useState<AnalystMode>('read_only');
  const [tab, setTab] = useState('answer');
  const [task, setTask] = useState(() => params.get('task') ?? '');
  const [project, setProject] = useState(() => params.get('project') ?? '');
  const [budget, setBudget] = useState(() => Number(params.get('budget')) || DEFAULT_BUDGET);
  // The budget the DISPLAYED result was composed under, which is not `budget`:
  // that box stays editable afterwards. Pinned when the result lands rather
  // than when it is requested, so the two always move together.
  const [composedBudget, setComposedBudget] = useState<number | null>(null);
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
  // Which request produced what is on screen. An answered composition arrives
  // on the answer stream, so the panes and the answer come from one retrieval.
  const [answered, setAnswered] = useState(false);
  const result = answered ? answer.context : build.data;
  const composing = answered
    ? answer.status === 'streaming' && !answer.context
    : build.isPending;
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

  const compose = (
    nextTask: string,
    nextProject: string,
    nextBudget: number,
    withAnswer = wantAnswer,
  ) => {
    setComposedBudget(nextBudget);
    const scopedProject =
      nextProject && nextProject !== AUTO_PROJECT ? nextProject : null;
    const request = {
      task: nextTask,
      project: scopedProject,
      budget: nextBudget,
      include_graph: true,
      // The page lays out symbols, source and memory bodies separately, so it
      // needs the structured fields the markdown duplicates. An agent does not,
      // which is why the server default is 1 rather than this.
      detail: 3,
    };
    setAnswered(withAnswer);
    if (withAnswer) {
      // One request. The stream's first event is the composition, which fills
      // the panes before generation starts; the answer is written from it.
      answer.start({ ...request, analyst_mode: analystMode });
    } else {
      answer.reset();
      build.mutate(
        { ...request, answer: false },
        { onSuccess: () => setComposedBudget(nextBudget) },
      );
    }
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

  const errorMessage = answered
    ? // A stream that failed before sending its composition composed nothing.
      answer.status === 'error' && !answer.context
      ? (answer.message ?? 'Composing code context failed.')
      : null
    : build.error instanceof MarmApiError
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
          <PaneTabs result={result} symbols={symbols} memories={memories} links={links} />

        <ComposeForm
          task={task}
          setTask={setTask}
          project={project}
          setProject={setProject}
          sortedProjects={sortedProjects}
          budget={budget}
          setBudget={setBudget}
          wantAnswer={wantAnswer}
          setWantAnswer={setWantAnswer}
          analystMode={analystMode}
          setAnalystMode={setAnalystMode}
          composing={composing}
          onSubmit={submit}
        />

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
            <CompositionSummary composed={composed} symbols={symbols} memories={memories} links={links} />

            {truncated && (
              <div className="mb-4 flex shrink-0 flex-wrap items-center gap-3 rounded-lg border border-amber-400/30 bg-amber-400/[0.05] px-4 py-3 text-sm">
                <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
                <span>
                  Output was truncated at {(composedBudget ?? budget).toLocaleString()} characters, so lower-ranked symbols were left out.
                </span>
                {/* The note was already the right diagnosis; it just was not
                    wired to the control that fixes it, 300px above. */}
                {(composedBudget ?? budget) < MAX_BUDGET && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="ml-auto"
                    onClick={() => {
                      const raised = Math.min((composedBudget ?? budget) * 2, MAX_BUDGET);
                      setBudget(raised);
                      // The request that produced THIS result, not whatever is
                      // in the form now. The control says "recompose", so
                      // editing the box first must not silently change what is
                      // re-run under that label -- including the budget, which
                      // a lowered box would otherwise turn into a cut.
                      compose(composed.task || task.trim(), composed.project?.name || project, raised);
                    }}
                  >
                    Raise to {Math.min((composedBudget ?? budget) * 2, MAX_BUDGET).toLocaleString()} and recompose
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
          {composing && !composed && <LoadingState label="Composing code context…" />}

          <TabsContent value="answer" className="m-0">
            <AnswerPane
              result={composed}
              symbols={symbols}
              stream={answer}
              asking={composing || answer.status === 'streaming'}
              canAsk={Boolean(task.trim())}
              onAsk={() => {
                setWantAnswer(true);
                compose(task.trim() || composed?.task || '', project, budget, true);
              }}
              onCite={(citation) => {
                // Jump to the evidence rather than describing where it is.
                const jump = (selector: string) =>
                  window.setTimeout(() => {
                    document
                      .querySelector(selector)
                      ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                  }, 60);
                if (citation.kind === 'memory' || !citation.qualified_name) {
                  setTab('memory');
                  if (citation.memory_id) jump(`[data-memory="${CSS.escape(citation.memory_id)}"]`);
                  return;
                }
                setTab('symbols');
                jump(`[data-symbol="${CSS.escape(citation.qualified_name)}"]`);
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
          {!composed && !errorMessage && !composing && (
            <ComposeStarter setTask={setTask} selected={selected} />
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
