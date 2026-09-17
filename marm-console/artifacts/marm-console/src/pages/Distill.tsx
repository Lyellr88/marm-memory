import { useMemo, useState } from 'react';
import {
  Button,
  Input,
  Label,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  cn,
} from '@/components/ui/core';
import { StatCard } from '@/components/ui/panels';
import { ActionNoticePanel, MemoryEmptyState } from '@/components/memory/shared';
import { FlaskConical, Inbox, Sparkles, CircleCheck, CircleAlert, Layers } from 'lucide-react';
import {
  useDistillApply,
  useDistillDiscard,
  useDistillPending,
  useDistillPropose,
} from '@/hooks/use-marm-queries';
import { MarmApiError } from '@/lib/marm-api';
import { LoadingState } from '@/components/code-context/shared';
import { ProposalCard } from '@/components/distill/ProposalCard';
import type { DistillProposal } from '@/lib/marm-types';

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

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const body = text.trim();
    if (!body || !sessionName.trim()) return;
    propose.mutate(
      {
        action: 'propose',
        text: body,
        session_name: sessionName.trim(),
        project: project.trim() || null,
      },
      { onSuccess: () => setTab('run') },
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

  const lastAction =
    apply.isSuccess && apply.data?.memory_id
      ? `Kept. Written to memory as ${apply.data.memory_id}.`
      : discard.isSuccess
        ? 'Discarded. It will not be proposed again.'
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
            Turn raw conversation into memory proposals, each resolved against what is already stored. MARM{' '}
            <strong className="font-semibold text-foreground/90">selects</strong> sentences rather than writing them —
            it runs no generative model — and nothing reaches memory until you keep it. The same answer an agent
            receives from <code className="font-mono text-xs">marm_distill</code>.
          </p>
        </header>

        <form onSubmit={submit} className="mb-6 shrink-0 space-y-3">
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
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[14rem] flex-1">
              <Label htmlFor="distill-session">Session</Label>
              <Input
                id="distill-session"
                value={sessionName}
                onChange={(event) => setSessionName(event.target.value)}
                placeholder="Which session these belong to"
                maxLength={256}
                className="mt-1.5"
              />
            </div>
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
            <Button type="submit" isLoading={propose.isPending} disabled={!text.trim() || !sessionName.trim()}>
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
              label="In the queue"
              value={queue.length.toLocaleString()}
              detail="Across every session"
              icon={<CircleAlert className="h-5 w-5" />}
              tone="amber"
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
          A high score means a sentence <em>reads</em> like a durable fact — it is not a claim that the fact is true.
          A <span className="text-amber-300">near</span> verdict means the encoder found something close and cannot
          say whether this refines it or contradicts it; that judgement is the reason this queue exists.
        </p>
      </div>
    </div>
  );
}
