import { useState, type ReactNode } from 'react';
import { Check, CheckCircle2, RefreshCw, XCircle } from 'lucide-react';
import {
  useRuntimeRestartJob,
  useRuntimeSettings,
  useSetupSettings,
  useStartRuntimeRestart,
  useUpdateLlmSettings,
  useUpdateRuntimeAutomation,
  useUpdateRuntimeProfile,
  useUpdateSetupSettings,
} from '@/hooks/use-marm-queries';
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, cn } from '@/components/ui/core';
import { SectionHeading } from '@/components/ui/panels';
import { CopyButton } from '@/components/code-context/shared';
import { MarmApiError } from '@/lib/marm-api';
import type { ConnectionsOverview, RuntimeProfile, SetupSettingItem, SetupSettingValue } from '@/lib/marm-types';
import { AgentsGrid } from './AgentsGrid';
import { ErrorState, NativeSelect, Pill, Toggle, mutationMessage } from './controls';

export const PROFILES: Array<{ id: RuntimeProfile; label: string }> = [
  { id: 'standard', label: 'Standard' },
  { id: 'swarm', label: 'Swarm (200 per minute)' },
  { id: 'swarm-max', label: 'Swarm max (600 per minute)' },
  { id: 'trusted', label: 'Trusted (no limit)' },
];

const RUNTIME_PREFIXES = ['server.', 'auth.'];

type Draft = Record<string, SetupSettingValue>;

function isRuntimeItem(item: SetupSettingItem) {
  return RUNTIME_PREFIXES.some((prefix) => item.key.startsWith(prefix));
}

function isDirty(item: SetupSettingItem, draft: Draft) {
  return item.key in draft && String(draft[item.key]) !== String(item.value);
}

function isValid(item: SetupSettingItem, value: SetupSettingValue) {
  if (item.type !== 'int') return true;
  if (String(value).trim() === '' || !Number.isInteger(Number(value))) return false;
  const number = Number(value);
  return (item.min === undefined || number >= item.min) && (item.max === undefined || number <= item.max);
}

function restartCommand(error: unknown): string | null {
  if (!(error instanceof MarmApiError)) return null;
  const body = error.body as { command?: unknown; detail?: { command?: unknown } } | undefined;
  const command = body?.command ?? body?.detail?.command;
  return typeof command === 'string' ? command : null;
}

export function SetupTab({ overview, onRequestConnection }: { overview: ConnectionsOverview | undefined; onRequestConnection: () => void }) {
  const settings = useSetupSettings();
  const updateSettings = useUpdateSetupSettings();
  const startRestart = useStartRuntimeRestart();
  const [jobId, setJobId] = useState<string | null>(null);
  const restartJob = useRuntimeRestartJob(jobId);
  const runtime = useRuntimeSettings();
  const updateProfile = useUpdateRuntimeProfile();
  const updateAutomation = useUpdateRuntimeAutomation();
  const updateLlm = useUpdateLlmSettings();

  const [draft, setDraft] = useState<Draft>({});
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [rpmDraft, setRpmDraft] = useState('');
  const [blocked, setBlocked] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [manualCommand, setManualCommand] = useState<string | null>(null);

  const groups = settings.data?.groups ?? [];
  const items = groups.flatMap((group) => group.items);
  const dirtyItems = items.filter((item) => isDirty(item, draft));
  const allValid = dirtyItems.every((item) => isValid(item, draft[item.key]));
  const restarting = startRestart.isPending || restartJob.data?.status === 'queued' || restartJob.data?.status === 'running';
  const locked = blocked !== null;

  function noteFailure(err: unknown) {
    if (err instanceof MarmApiError && err.status === 403) setBlocked(mutationMessage(err));
  }

  function setValue(item: SetupSettingItem, value: SetupSettingValue) {
    setDraft((prev) => {
      const next = { ...prev };
      if (String(value) === String(item.value)) delete next[item.key];
      else next[item.key] = value;
      return next;
    });
  }

  function saveAndApply() {
    setConfirmOpen(false);
    setSaveError(null);
    setManualCommand(null);
    setJobId(null);
    const values: Draft = {};
    for (const item of dirtyItems) values[item.key] = item.type === 'int' ? Number(draft[item.key]) : draft[item.key];
    updateSettings.mutate(values, {
      onSuccess: () => {
        setDraft({});
        startRestart.mutate(undefined, {
          onSuccess: (job) => setJobId(job.job_id),
          onError: (err) => {
            noteFailure(err);
            const command = err instanceof MarmApiError && err.status === 409 ? restartCommand(err) : null;
            if (command) setManualCommand(command);
            else setSaveError(mutationMessage(err));
          },
        });
      },
      onError: (err) => {
        noteFailure(err);
        setSaveError(mutationMessage(err));
      },
    });
  }

  const live = runtime.data;
  const liveError = updateProfile.error ?? updateAutomation.error ?? updateLlm.error;
  const runtimeItems = items.filter(isRuntimeItem);
  const featureGroups = groups.map((group) => ({ ...group, items: group.items.filter((item) => !isRuntimeItem(item)) })).filter((group) => group.items.length > 0);

  function bootRow(item: SetupSettingItem) {
    const value = item.key in draft ? draft[item.key] : item.value;
    const invalid = isDirty(item, draft) && !isValid(item, value);
    let control: ReactNode;
    if (item.type === 'bool') {
      control = <Toggle label={item.label} checked={Boolean(value)} disabled={locked} onChange={(next) => setValue(item, next)} />;
    } else if (item.type === 'int') {
      control = <Input aria-label={item.label} type="number" inputMode="numeric" min={item.min} max={item.max} value={String(value)} disabled={locked} onChange={(event) => setValue(item, event.target.value)} className={cn('h-8 w-28 font-mono text-xs', invalid && 'border-destructive/60')} />;
    } else {
      control = (
        <NativeSelect aria-label={item.label} value={String(value)} disabled={locked} onChange={(event) => setValue(item, event.target.value)} className="h-8 w-32 text-xs">
          {(item.choices ?? []).map((choice) => <option key={choice} value={choice}>{choice}</option>)}
        </NativeSelect>
      );
    }
    return (
      <SettingRow
        key={item.key}
        title={<>{item.label}{item.overrides_env && <span className="ml-2 text-[10.5px] font-normal text-amber-300">overrides env</span>}</>}
        help={invalid ? `Enter a whole number${item.min !== undefined && item.max !== undefined ? ` from ${item.min} to ${item.max}` : ''}.` : item.help}
        helpTone={invalid ? 'bad' : undefined}
        control={control}
        pill={<Pill tone="info">applies on restart</Pill>}
      />
    );
  }

  return (
    <div className="space-y-8">
      <Checklist overview={overview} />

      <section className="space-y-5">
        <SectionHeading title="Server settings" description={`Saved to ${settings.data?.path ?? '~/.marm/settings.json'}. Applies to every way MARM runs.`} />
        {settings.isLoading && <div className="flex min-h-24 items-center justify-center rounded-xl border border-dashed border-border/80 text-sm text-muted-foreground"><RefreshCw className="mr-2 h-4 w-4 animate-spin" />Reading settings…</div>}
        {settings.isError && <ErrorState message={settings.error instanceof Error ? settings.error.message : 'Settings are unavailable.'} />}
        {locked && <div className="rounded-xl border border-amber-400/30 bg-amber-400/[0.05] p-4 text-sm text-amber-200">Changes are turned off here. {blocked}</div>}

        {settings.data && (
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border/80 bg-card/45 p-5">
              <h3 className="mb-1 font-medium">Runtime</h3>
              <SettingRow
                title="Profile"
                help="How strictly requests are throttled."
                control={
                  <NativeSelect aria-label="Profile" value={live?.profile ?? ''} disabled={locked || !live || updateProfile.isPending} onChange={(event) => { setRpmDraft(''); updateProfile.mutate({ profile: event.target.value as RuntimeProfile }, { onError: noteFailure }); }} className="h-8 w-44 text-xs">
                    {live && !PROFILES.some((profile) => profile.id === live.profile) && <option value={live.profile}>{live.profile}</option>}
                    {PROFILES.map((profile) => <option key={profile.id} value={profile.id}>{profile.label}</option>)}
                  </NativeSelect>
                }
                pill={<Pill tone="good">applies now</Pill>}
              />
              <SettingRow
                title="Rate limit per minute"
                help="Zero turns throttling off."
                control={
                  <div className="flex items-center gap-2">
                    <Input aria-label="Rate limit per minute" type="number" min={0} inputMode="numeric" value={rpmDraft} placeholder={live ? String(live.rate_limit.requests_per_minute) : ''} disabled={locked || !live} onChange={(event) => setRpmDraft(event.target.value)} className="h-8 w-24 font-mono text-xs" />
                    <Button size="sm" variant="outline" disabled={locked || !live || !/^\d+$/.test(rpmDraft.trim())} isLoading={updateProfile.isPending} onClick={() => updateProfile.mutate({ profile: (live?.profile as RuntimeProfile) || 'standard', rateLimitRpm: Number(rpmDraft) }, { onError: noteFailure, onSuccess: () => setRpmDraft('') })}>Apply</Button>
                  </div>
                }
                pill={<Pill tone="good">applies now</Pill>}
              />
              {runtimeItems.map(bootRow)}
            </div>

            <div className="space-y-3 rounded-xl border border-border/80 bg-card/45 p-5">
              <h3 className="font-medium">Features</h3>
              <details className="rounded-lg border border-border/70 bg-background/30 px-3">
                <summary className="cursor-pointer py-2.5 text-sm font-medium">Live switches</summary>
                <SettingRow title="Auto-index code projects" help="Re-indexes when files change." control={<Toggle label="Auto-index code projects" checked={Boolean(live?.automation.graph.enabled)} disabled={locked || !live || updateAutomation.isPending} onChange={(enabled) => updateAutomation.mutate({ scope: 'graph', enabled }, { onError: noteFailure })} />} pill={<Pill tone="good">applies now</Pill>} />
                <SettingRow title="Auto-extract concepts" help="Builds the knowledge graph from memories." control={<Toggle label="Auto-extract concepts" checked={Boolean(live?.automation.concept.enabled)} disabled={locked || !live || updateAutomation.isPending} onChange={(enabled) => updateAutomation.mutate({ scope: 'concept', enabled }, { onError: noteFailure })} />} pill={<Pill tone="good">applies now</Pill>} />
                <SettingRow title="Local generation" help="Answers and fact writing from a model on this machine." control={<Toggle label="Local generation" checked={Boolean(live?.llm?.enabled)} disabled={locked || !live || updateLlm.isPending} onChange={(enabled) => updateLlm.mutate({ enabled }, { onError: noteFailure })} />} pill={<Pill tone="good">applies now</Pill>} />
              </details>
              {featureGroups.map((group) => (
                <details key={group.id} className="rounded-lg border border-border/70 bg-background/30 px-3">
                  <summary className="cursor-pointer py-2.5 text-sm font-medium">{group.label}</summary>
                  {group.items.map(bootRow)}
                </details>
              ))}
            </div>
          </div>
        )}
        {liveError && <ErrorState message={mutationMessage(liveError)} />}

        <div className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/80 bg-background/90 p-3 backdrop-blur">
          <p className="text-sm text-muted-foreground" role="status">
            {dirtyItems.length === 0 ? 'No unsaved changes.' : `${dirtyItems.length} unsaved ${dirtyItems.length === 1 ? 'change' : 'changes'}. Save and apply restarts the runtime.`}
          </p>
          <div className="flex items-center gap-2">
            <Button variant="ghost" disabled={dirtyItems.length === 0} onClick={() => setDraft({})}>Discard</Button>
            <Button disabled={dirtyItems.length === 0 || !allValid || locked || restarting || updateSettings.isPending} isLoading={updateSettings.isPending} onClick={() => setConfirmOpen(true)}>Save and apply</Button>
          </div>
        </div>

        <RestartStatus
          restarting={restarting}
          started={jobId !== null || startRestart.isPending}
          job={restartJob.data}
          saveError={saveError}
          manualCommand={manualCommand}
        />
      </section>

      <AgentsGrid onRequest={onRequestConnection} allowedTransports={['http', 'stdio']} />

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save and apply?</DialogTitle>
            <DialogDescription>Saves to {settings.data?.path ?? '~/.marm/settings.json'} and restarts the MARM runtime. Connected agents reconnect on their next request. The Console stays open.</DialogDescription>
          </DialogHeader>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {dirtyItems.map((item) => <li key={item.key}><span className="text-foreground">{item.label}</span>: {String(item.value)} to {String(draft[item.key])}</li>)}
          </ul>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>Cancel</Button>
            <Button onClick={saveAndApply}>Save and restart</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SettingRow({ title, help, helpTone, control, pill }: { title: ReactNode; help: string; helpTone?: 'bad'; control: ReactNode; pill: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-t border-border/60 py-3 first:border-t-0">
      <div className="min-w-0">
        <p className="text-sm">{title}</p>
        <p className={cn('text-xs', helpTone === 'bad' ? 'text-destructive' : 'text-muted-foreground')}>{help}</p>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1.5">
        {control}
        {pill}
      </div>
    </div>
  );
}

function RestartStatus({ restarting, started, job, saveError, manualCommand }: { restarting: boolean; started: boolean; job: { status: string; seconds?: number; detail?: string } | undefined; saveError: string | null; manualCommand: string | null }) {
  if (manualCommand) {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-400/30 bg-amber-400/[0.05] p-3 text-sm text-amber-200" role="status">
        <span>Saved. Restart with:</span>
        <span className="select-all font-mono text-xs">{manualCommand}</span>
        <CopyButton value={manualCommand} label="Copy restart command" />
      </div>
    );
  }
  if (saveError) return <ErrorState message={saveError} />;
  if (!started) return null;
  const failed = job?.status === 'error';
  const done = job?.status === 'done';
  return (
    <div className={cn('flex items-start gap-3 rounded-lg border p-3 text-sm', failed ? 'border-destructive/35 bg-destructive/[0.06]' : done ? 'border-emerald-500/30 bg-emerald-500/[0.06]' : 'status-pulse border-primary/35 bg-primary/[0.06]')} role="status" aria-live="polite">
      {restarting || !job ? <RefreshCw className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-primary" /> : failed ? <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" /> : <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />}
      <p className={failed ? 'text-destructive' : done ? 'text-emerald-200' : 'text-muted-foreground'}>
        {failed ? job?.detail || 'The restart failed.' : done ? `Runtime restarted in ${(job?.seconds ?? 0).toFixed(1)} s` : 'Restarting the runtime…'}
      </p>
    </div>
  );
}

function Checklist({ overview }: { overview: ConnectionsOverview | undefined }) {
  if (!overview) return null;
  const nextIndex = overview.checklist.findIndex((step) => !step.done);
  return (
    <ol className="grid auto-cols-[minmax(150px,1fr)] grid-flow-col gap-2 overflow-x-auto" aria-label="Setup checklist">
      {overview.checklist.map((step, index) => {
        const state = step.done ? 'done' : index === nextIndex ? 'next' : 'todo';
        return (
          <li key={step.id} data-state={state} aria-current={state === 'next' ? 'step' : undefined} className={cn('flex items-start gap-2.5 rounded-lg border p-3 text-xs', state === 'next' ? 'border-primary/45 bg-primary/[0.05]' : 'border-border bg-card/45')}>
            <span className={cn('mt-0.5 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full text-[11px] font-bold', state === 'done' ? 'border border-emerald-400/25 bg-emerald-400/10 text-emerald-300' : state === 'next' ? 'bg-primary text-primary-foreground' : 'border border-input text-muted-foreground')}>
              {state === 'done' ? <Check className="h-3 w-3" /> : index + 1}
            </span>
            <div className="min-w-0">
              <b className="block truncate text-[12.5px]" title={step.label}>{step.label}</b>
              <span className="block truncate text-muted-foreground" title={step.detail}>{step.detail}</span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
