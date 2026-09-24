import { useEffect, useMemo, useState } from 'react';
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
import { StatCard } from '@/components/ui/panels';
import { ActionNoticePanel, MemoryEmptyState } from '@/components/memory/shared';
import { FlaskConical, Inbox, Sparkles, CircleCheck, CircleAlert, Layers, Wand2, ScanText } from 'lucide-react';
import {
  useDistillApply,
  useDistillDiscard,
  useDistillPending,
  useDistillPropose,
  useLogs,
  useSessions,
} from '@/hooks/use-marm-queries';
import { MarmApiError } from '@/lib/marm-api';
import { LoadingState } from '@/components/code-context/shared';
import { ProposalCard } from '@/components/distill/ProposalCard';
import type { DistillProposal } from '@/lib/marm-types';

/** The API request cap. Surfaced in the UI when it is actually reached. */
const SESSION_LOG_LIMIT = 200;

const PLACEHOLDER =
  'Paste a conversation. MARM selects the sentences in it that already read like durable facts — it does not write new ones.';

/** Described once and rendered twice, as the tab strip and as the empty state,
 *  so the page cannot advertise a pane it does not then show. */
const PANES = [
  {
    value: 'queue',
    icon: Inbox,
    label: 'Review queue',
    tone: 'console-tab-cyan',
    blurb:
      'Proposals waiting for a decision, including ones an agent staged from its own sessions. Best-scoring first.',
  },
  {
    value: 'run',
    icon: Sparkles,
    label: 'Last run',
    tone: 'console-tab-violet',
    blurb:
      'What the most recent distil found, including the duplicates it declined to stage — the part that tells you the store already knew something.',
  },
] as const;

export function DistillPage() {
  const [text, setText] = useState('');
  const [sessionName, setSessionName] = useState('');
  const [project, setProject] = useState('');
  const [tab, setTab] = useState<string>('queue');
  const [busyId, setBusyId] = useState<string | null>(null);
  // Pasting a transcript is the fallback, not the main path. MARM already
  // holds session logs, so the common case is "distil what I recorded in
  // session X" — asking a user to go and copy that back out of the tool that
  // stored it is work the page can simply do.
  const [source, setSource] = useState<'session' | 'paste'>('session');
  // Generation is opt-in: a reachable model must not change what a
  // distillation produces unless the reader asks for it.
  const [useLlm, setUseLlm] = useState(false);
  // What the displayed run asked for, captured at submit: a `selected` run
  // means "no model answered" only if generation was requested.
  const [requestedLlm, setRequestedLlm] = useState(false);

  const sessions = useSessions();
  // Default to a real session rather than an empty box, for the same reason
  // Code Context defaults its project: the page is useless until one is
  // chosen, and the most recently touched one is nearly always the right one.
  useEffect(() => {
    if (!sessionName && sessions.data?.length) setSessionName(sessions.data[0].name);
  }, [sessionName, sessions.data]);
  const sessionLogs = useLogs(
    source === 'session' && sessionName ? { session: sessionName, limit: SESSION_LOG_LIMIT } : undefined,
  );
  // The request caps at 200 entries. Saying "N entries will be distilled" while
  // silently dropping older ones is how a long session loses durable facts with
  // no indication, so the cap is surfaced when it actually bites.
  const sessionCapped = (sessionLogs.data?.items?.length ?? 0) >= SESSION_LOG_LIMIT;
  const fromSession = useMemo(() => {
    const entries = sessionLogs.data?.items ?? [];
    return entries
      .map((log) => [log.topic, log.summary, log.entry].filter(Boolean).join(' — '))
      .join('\n');
  }, [sessionLogs.data]);

  const propose = useDistillPropose();
  const apply = useDistillApply();
  const discard = useDistillDiscard();
  const pending = useDistillPending(null);

  const queue = useMemo<DistillProposal[]>(() => pending.data?.pending ?? [], [pending.data]);
  const lastRun = propose.data;
  const ran = Boolean(lastRun);

  const duplicatesDeclined = useMemo(
    () => (lastRun?.proposals ?? []).filter((p) => !p.staged).length,
    [lastRun],
  );

  const body = source === 'session' ? fromSession : text;
  const canSubmit = Boolean(body.trim() && sessionName.trim());

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    const asked = useLlm;
    propose.mutate(
      {
        action: 'propose',
        text: body.trim(),
        session_name: sessionName.trim(),
        project: project.trim() || null,
        use_llm: useLlm,
      },
      {
        onSuccess: () => {
          setRequestedLlm(asked);
          setTab('run');
        },
      },
    );
  };

  const act = (id: string, fn: typeof apply | typeof discard) => {
    setBusyId(id);
    fn.mutate(id, { onSettled: () => setBusyId(null) });
  };

  const mutationError = [propose.error, apply.error, discard.error].find(Boolean);
  const errorMessage = mutationError
    ? mutationError instanceof MarmApiError
      ? mutationError.message
      : 'The distil request failed.'
    : null;

  // useMutation keeps success state, so after an apply succeeds `apply.isSuccess`
  // stays true and would outrank a later discard. Compare when each last
  // settled and report the most recent one.
  const lastAction =
    apply.isSuccess || discard.isSuccess
      ? (apply.submittedAt ?? 0) >= (discard.submittedAt ?? 0)
        ? apply.isSuccess && apply.data?.memory_id
          ? `Kept. Written to memory as ${apply.data.memory_id}.`
          : null
        : discard.isSuccess
          ? 'Discarded. It will not be proposed again.'
          : null
      : null;

  return (
    <div className="page-enter flex h-full flex-col overflow-hidden p-7 xl:p-8">
      <div className="mx-auto flex h-full w-full max-w-[1560px] flex-col overflow-hidden">
        <header className="mb-6 shrink-0">
          <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">
            <FlaskConical className="h-3 w-3" />
            Reviewed distillation
          </div>
          <h1 className="text-[1.8rem] font-semibold tracking-[-0.045em]">Distill</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Turn raw conversation into memory proposals, each resolved against what is already stored. By default MARM{' '}
            <strong className="font-semibold text-foreground/90">selects</strong> sentences verbatim; ask it to use the
            local model and it <strong className="font-semibold text-foreground/90">writes</strong> each fact so it
            stands on its own, keeping the words it came from. Either way
            nothing leaves this machine, and nothing reaches memory until you keep it. The same answer an agent
            receives from <code className="font-mono text-xs">marm_distill</code>.
          </p>
        </header>

        <form onSubmit={submit} className="mb-6 shrink-0 space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[16rem] flex-1">
              <Label htmlFor="distill-session">Session</Label>
              <Select value={sessionName} onValueChange={setSessionName}>
                <SelectTrigger id="distill-session" aria-label="Session" className="mt-1.5">
                  <SelectValue placeholder="Choose a session" />
                </SelectTrigger>
                <SelectContent>
                  {(sessions.data ?? []).map((item) => (
                    <SelectItem key={item.name} value={item.name}>
                      {item.name}
                      <span className="ml-2 font-mono text-[10px] text-muted-foreground">
                        {item.log_count} logs
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex h-10 items-center gap-1 rounded-md border border-border/70 bg-muted/40 p-1">
              {(['session', 'paste'] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setSource(value)}
                  className={cn(
                    'rounded px-2.5 py-1 text-xs transition-colors',
                    source === value
                      ? 'bg-primary/15 text-primary-highlight'
                      : 'text-muted-foreground hover:text-foreground/80',
                  )}
                >
                  {value === 'session' ? 'From its logs' : 'Paste text'}
                </button>
              ))}
            </div>
          </div>

          {source === 'paste' ? (
            <div>
              <Label htmlFor="distill-text">Conversation</Label>
              <Textarea
                id="distill-text"
                value={text}
                onChange={(event) => setText(event.target.value)}
                placeholder={PLACEHOLDER}
                rows={5}
                maxLength={400000}
                className="mt-1.5 font-mono text-[13px]"
              />
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-border/70 bg-background/25 p-3 text-xs text-muted-foreground">
              {!sessionName ? (
                'Choose a session and MARM will distil what it already recorded there — no pasting.'
              ) : sessionLogs.isLoading ? (
                'Reading that session\u2019s log entries\u2026'
              ) : fromSession ? (
                <>
                  <span className="font-mono tabular-nums text-foreground/80">
                    {(sessionLogs.data?.items ?? []).length.toLocaleString()} log entries
                  </span>{' '}
                  ({fromSession.length.toLocaleString()} characters) will be distilled.
                    {sessionCapped && (
                      <span className="text-muted-foreground">
                        {' '}Only the most recent {SESSION_LOG_LIMIT.toLocaleString()} entries are read,
                        so anything older in this session is not included.
                      </span>
                    )}
                </>
              ) : (
                'That session has no log entries. Switch to “Paste text”, or log something first.'
              )}
            </div>
          )}

          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[12rem] flex-1">
              <Label htmlFor="distill-project">Project (optional)</Label>
              <Input
                id="distill-project"
                value={project}
                onChange={(event) => setProject(event.target.value)}
                placeholder="Short scope name, e.g. MARM-Stack"
                maxLength={256}
                className="mt-1.5"
              />
            </div>
            <label
              className="flex h-10 cursor-pointer select-none items-center gap-2 rounded-md border border-border/70 bg-muted/40 px-3 text-xs text-muted-foreground"
              title="Write each fact with the local model, keeping the words it came from. Needs local generation switched on under System; without it MARM selects sentences."
            >
              <input
                type="checkbox"
                checked={useLlm}
                onChange={(event) => setUseLlm(event.target.checked)}
                className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
              />
              Write facts with the local model
            </label>
            <Button type="submit" isLoading={propose.isPending} disabled={!canSubmit}>
              <Sparkles className="mr-2 h-4 w-4" /> Distill
            </Button>
          </div>
        </form>

        {errorMessage && (
          <div className="mb-4 shrink-0">
            <ActionNoticePanel notice={{ kind: 'error', message: errorMessage }} />
          </div>
        )}
        {lastAction && !errorMessage && (
          <div className="mb-4 shrink-0">
            <ActionNoticePanel notice={{ kind: 'success', message: lastAction }} />
          </div>
        )}

        {ran && (
          <section className="mb-4 grid shrink-0 gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Distillation summary">
            <StatCard
              label="Selected"
              value={(lastRun?.extracted ?? 0).toLocaleString()}
              detail="Sentences that read like durable facts"
              icon={<Layers className="h-5 w-5" />}
              tone="cyan"
              delay={0}
            />
            <StatCard
              label="Staged for review"
              value={(lastRun?.staged ?? 0).toLocaleString()}
              detail="Awaiting your decision"
              icon={<Inbox className="h-5 w-5" />}
              tone="violet"
              delay={55}
            />
            <StatCard
              label="Already known"
              value={duplicatesDeclined.toLocaleString()}
              detail="Duplicates, or already proposed before"
              icon={<CircleCheck className="h-5 w-5" />}
              tone="emerald"
              delay={110}
            />
            <StatCard
              label={lastRun?.mode === 'generated' ? 'Written by' : 'Selected by'}
              value={lastRun?.mode === 'generated' ? 'local model' : 'sentence shape'}
              detail={
                lastRun?.mode === 'generated'
                  ? 'Facts rewritten to stand alone, each checked against the transcript'
                  : requestedLlm
                    ? 'No local model reachable — sentences lifted verbatim instead'
                    : 'Sentences lifted verbatim; generation was not requested'
              }
              icon={
                lastRun?.mode === 'generated' ? (
                  <Wand2 className="h-5 w-5" />
                ) : (
                  <ScanText className="h-5 w-5" />
                )
              }
              tone={lastRun?.mode === 'generated' ? 'amber' : 'blue'}
              delay={165}
            />
          </section>
        )}

        <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <TabsList className="mb-4 grid h-auto w-full shrink-0 grid-cols-2 gap-1.5 rounded-xl border border-card-border bg-card/70 p-1.5 shadow-[0_14px_40px_rgba(0,0,0,0.16),inset_0_1px_0_rgba(var(--primary-rgb),0.04)]">
            {PANES.map((pane, index) => {
              const count = pane.value === 'queue' ? queue.length : (lastRun?.proposals?.length ?? null);
              return (
                <TabsTrigger
                  key={pane.value}
                  value={pane.value}
                  title={pane.blurb}
                  className={cn(
                    'console-tab metric-enter group relative h-11 justify-start gap-3 overflow-hidden border border-transparent px-3 text-left data-[state=active]:bg-white/[0.035]',
                    pane.tone,
                  )}
                  style={{ animationDelay: `${index * 45}ms` }}
                >
                  <span className="console-tab-icon flex h-6 w-6 shrink-0 items-center justify-center rounded-md border bg-background/45 transition-transform duration-200 group-hover:scale-105">
                    <pane.icon className="h-3.5 w-3.5" />
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs font-semibold text-foreground">
                    {pane.label}
                  </span>
                  <span className="font-mono text-sm font-semibold tabular-nums text-foreground/90">
                    {count === null ? '—' : count.toLocaleString()}
                  </span>
                </TabsTrigger>
              );
            })}
          </TabsList>

          <div className="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
          <TabsContent value="queue" className="m-0">
            {pending.isLoading ? (
              <LoadingState label="Loading the review queue…" />
            ) : queue.length === 0 ? (
              <MemoryEmptyState
                title="Nothing is waiting for review"
                detail="Proposals appear here when you distil a conversation above, or when an agent runs marm_distill in a session of its own."
              />
            ) : (
              <div className="space-y-3">
                {queue.map((proposal, index) => (
                  <ProposalCard
                    key={proposal.id}
                    proposal={proposal}
                    delay={index * 45}
                    busy={busyId === proposal.id}
                    onApply={(id) => act(id, apply)}
                    onDiscard={(id) => act(id, discard)}
                  />
                ))}
              </div>
            )}
          </TabsContent>

          <TabsContent value="run" className="m-0">
            {!ran ? (
              <MemoryEmptyState
                title="No distillation has been run yet"
                detail={PANES[1].blurb}
              />
            ) : lastRun?.proposals?.length === 0 ? (
              <MemoryEmptyState
                title="Nothing in that text read as a durable fact"
                detail={
                  lastRun?.note ??
                  'That is the usual outcome for a conversation that was mostly doing rather than concluding — it is not an error.'
                }
              />
            ) : (
              <div className="space-y-3">
                {(lastRun?.proposals ?? []).map((proposal, index) => (
                  <ProposalCard
                    key={proposal.id ?? `${index}-${proposal.content.slice(0, 40)}`}
                    proposal={proposal}
                    delay={index * 45}
                    busy={busyId === proposal.id}
                    onApply={proposal.id ? (id) => act(id, apply) : undefined}
                    onDiscard={proposal.id ? (id) => act(id, discard) : undefined}
                  />
                ))}
              </div>
            )}
          </TabsContent>
          </div>
        </Tabs>

        <p className="mt-3 shrink-0 text-[11px] text-muted-foreground">
          {lastRun?.mode === 'selected' && (
            <>
              {requestedLlm ? (
                <>
                  <span className="text-amber-300">No local model was reachable</span>, so these were{' '}
                </>
              ) : (
                'These were '
              )}
              <em>selected</em> from the text rather than written: whole sentences, exactly as
              typed, which means some carry references to whatever preceded them.{' '}
            </>
          )}
          A high score means a sentence <em>reads</em> like a durable fact — it is not a claim that the fact is true.
          A <span className="text-amber-300">near</span> verdict means the encoder found something close and cannot
          say whether this refines it or contradicts it; that judgement is the reason this queue exists.
        </p>
      </div>
    </div>
  );
}
