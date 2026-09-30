import { useState, type ReactNode } from 'react';
import { CheckCircle2, Plus, RefreshCw, X, XCircle } from 'lucide-react';
import {
  useDocker,
  useDockerAction,
  useDockerCompose,
  useDockerControl,
  useDockerJob,
  useDockerLogs,
  useUpdateDockerConfig,
  useWriteDockerCompose,
} from '@/hooks/use-marm-queries';
import { Button, Card, CardContent, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, cn } from '@/components/ui/core';
import { SectionHeading } from '@/components/ui/panels';
import { CopyButton, LoadingState } from '@/components/code-context/shared';
import { MarmApiError } from '@/lib/marm-api';
import type { DockerConfig, DockerContainer } from '@/lib/marm-types';
import { AgentsGrid } from './AgentsGrid';
import { ErrorState, NativeSelect, Pill, Toggle, mutationMessage } from './controls';
import { PROFILES } from './SetupTab';

type JobKind = 'pull' | 'start' | 'recreate';

const JOB_TEXT: Record<JobKind, { running: string; done: string; failed: string }> = {
  pull: { running: 'Pulling image...', done: 'Image pulled', failed: 'The pull failed.' },
  start: { running: 'Starting container...', done: 'Container started', failed: 'The container did not start.' },
  recreate: { running: 'Recreating container...', done: 'Container recreated', failed: 'The container was not recreated.' },
};

interface Form {
  tag: string;
  port: string;
  memory: string;
  cpus: string;
  data_dir: string;
  repos: string[];
  profile: string;
  rate: string;
  expose: boolean;
}

function toForm(config: DockerConfig): Form {
  return {
    tag: config.tag,
    port: String(config.port),
    memory: config.memory ?? '',
    cpus: config.cpus ?? '',
    data_dir: config.data_dir,
    repos: config.repos,
    profile: config.profile,
    rate: config.rate_limit_rpm === null ? '' : String(config.rate_limit_rpm),
    expose: config.expose_network,
  };
}

function toConfig(form: Form): DockerConfig {
  return {
    tag: form.tag.trim(),
    port: Number(form.port),
    memory: form.memory.trim() || null,
    cpus: form.cpus.trim() || null,
    data_dir: form.data_dir.trim(),
    repos: form.repos.map((repo) => repo.trim()).filter(Boolean),
    profile: form.profile,
    rate_limit_rpm: form.rate.trim() === '' ? null : Number(form.rate),
    expose_network: form.expose,
  };
}

function formValid(form: Form) {
  const port = Number(form.port);
  const rate = form.rate.trim();
  return form.tag.trim() !== '' && Number.isInteger(port) && port >= 1 && port <= 65535 && (rate === '' || (Number.isInteger(Number(rate)) && Number(rate) >= 0));
}

function stateDisplay(state: string): { label: string; tone: 'good' | 'warn' | 'neutral' } {
  if (state === 'running') return { label: 'Running', tone: 'good' };
  if (state === 'absent') return { label: 'Not created', tone: 'neutral' };
  if (state === 'conflict') return { label: 'Name in use', tone: 'warn' };
  return { label: state.charAt(0).toUpperCase() + state.slice(1), tone: 'warn' };
}

function portBindings(container: DockerContainer) {
  return Object.entries(container.ports ?? {}).flatMap(([inner, bindings]) => (bindings ?? []).map((binding) => `${binding.HostIp || '0.0.0.0'}:${binding.HostPort} to ${inner}`));
}

function existingFilePath(err: unknown): string | null | undefined {
  if (!(err instanceof MarmApiError) || err.status !== 409) return undefined;
  const body = err.body as { detail?: { reason?: unknown; path?: unknown } } | undefined;
  if (body?.detail?.reason !== 'exists') return undefined;
  return typeof body.detail.path === 'string' ? body.detail.path : null;
}

export function DockerTab({ onRequestConnection }: { onRequestConnection: () => void }) {
  const docker = useDocker();
  const updateConfig = useUpdateDockerConfig();
  const pull = useDockerAction('pull');
  const start = useDockerAction('start');
  const recreate = useDockerAction('recreate');
  const stop = useDockerControl('stop');
  const restart = useDockerControl('restart');
  const writeCompose = useWriteDockerCompose();

  const [job, setJob] = useState<{ id: string; kind: JobKind } | null>(null);
  const jobQuery = useDockerJob(job?.id ?? null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [stopOpen, setStopOpen] = useState(false);
  const [recreateOpen, setRecreateOpen] = useState(false);
  const [logsOpen, setLogsOpen] = useState(false);
  const logs = useDockerLogs(logsOpen, 200);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [conflict, setConflict] = useState<{ path: string | null } | null>(null);
  const [written, setWritten] = useState<{ path: string; command: string } | null>(null);
  const compose = useDockerCompose(previewOpen);
  const [draft, setDraft] = useState<Form | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const data = docker.data;
  const readOnly = data?.in_container ?? false;
  const engineUp = !!data && data.engine.available && data.engine.daemon;
  const container = data?.container;
  const form = draft ?? (data ? toForm(data.config) : null);
  const dirty = !!data && !!draft && JSON.stringify(toConfig(draft)) !== JSON.stringify(toConfig(toForm(data.config)));
  const valid = !!form && formValid(form);
  const jobStatus = jobQuery.data?.status;
  const jobRunning = start.isPending || pull.isPending || recreate.isPending || (!!job && (!jobQuery.data || jobStatus === 'queued' || jobStatus === 'running'));
  const busy = jobRunning || stop.isPending || restart.isPending || updateConfig.isPending;

  function edit(patch: Partial<Form>) {
    if (form) setDraft({ ...form, ...patch });
  }

  function runJob(kind: JobKind, mutation: { mutate: (vars: undefined, opts: { onSuccess: (res: { job_id: string }) => void; onError: (err: unknown) => void }) => void }) {
    setActionError(null);
    setJob(null);
    mutation.mutate(undefined, {
      onSuccess: (res) => setJob({ id: res.job_id, kind }),
      onError: (err) => setActionError(mutationMessage(err)),
    });
  }

  function control(mutation: { mutate: (vars: undefined, opts: { onError: (err: unknown) => void }) => void }) {
    setActionError(null);
    mutation.mutate(undefined, { onError: (err) => setActionError(mutationMessage(err)) });
  }

  function save(after?: () => void) {
    if (!form) return;
    setSaveError(null);
    updateConfig.mutate(toConfig(form), {
      onSuccess: () => {
        setDraft(null);
        after?.();
      },
      onError: (err) => setSaveError(mutationMessage(err)),
    });
  }

  function saveAndRecreate() {
    setRecreateOpen(false);
    save(() => runJob('recreate', recreate));
  }

  function writeFile(overwrite: boolean) {
    setConflict(null);
    setWritten(null);
    writeCompose.mutate(overwrite, {
      onSuccess: (res) => setWritten({ path: res.path, command: res.command }),
      onError: (err) => {
        const existing = existingFilePath(err);
        if (existing !== undefined) setConflict({ path: existing ?? compose.data?.path ?? null });
        else setActionError(mutationMessage(err));
      },
    });
  }

  const display = container ? stateDisplay(container.state) : null;
  const absent = container?.state === 'absent';
  const conflicted = container?.state === 'conflict';
  const running = container?.state === 'running';
  const actionsOff = readOnly || !engineUp || busy;

  return (
    <div className="space-y-8">
      <section className="space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <SectionHeading title="MARM in Docker" description="Run MARM as a container, keep its settings here, and connect your agents to it." />
          <Button variant="outline" size="sm" isLoading={docker.isFetching} onClick={() => void docker.refetch()}><RefreshCw className="mr-2 h-3.5 w-3.5" />Refresh</Button>
        </div>

        {docker.isLoading && <LoadingState label="Checking Docker..." />}
        {docker.isError && <ErrorState message={docker.error instanceof Error ? docker.error.message : 'Docker status is unavailable.'} />}

        {data && readOnly && (
          <div className="rounded-xl border border-amber-400/30 bg-amber-400/[0.05] p-4 text-sm text-amber-200">{data.read_only_reason || 'The Console is running inside a container, so Docker controls are read-only.'}</div>
        )}

        {data && !data.engine.available && (
          <div className="rounded-xl border border-border/80 bg-card/45 p-5 text-sm">
            <p>Docker is not installed on this machine.</p>
            <a href="https://docs.docker.com/get-docker/" target="_blank" rel="noreferrer" className="mt-2 inline-block text-primary underline-offset-4 hover:underline">Install Docker Desktop</a>
          </div>
        )}
        {data && data.engine.available && !data.engine.daemon && (
          <div className="rounded-xl border border-amber-400/30 bg-amber-400/[0.05] p-5 text-sm text-amber-200">Docker is installed but not running. Start Docker Desktop, then refresh.</div>
        )}

        {data && container && engineUp && display && (
          <Card>
            <CardContent className="space-y-4 p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-medium">{container.name}</p>
                  <p className="font-mono text-xs text-muted-foreground">{container.image ?? `MARM image, tag ${data.config.tag}`}</p>
                </div>
                <Pill tone={display.tone}>{display.label}</Pill>
              </div>

              {!absent && (
                <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-xs">
                  <dt className="text-muted-foreground">Health</dt>
                  <dd>{container.health ?? 'unknown'}</dd>
                  <dt className="text-muted-foreground">Port</dt>
                  <dd className="font-mono">{portBindings(container).join(', ') || 'none'}</dd>
                  <dt className="text-muted-foreground">Profile</dt>
                  <dd>{container.profile ?? 'unknown'}</dd>
                  <dt className="text-muted-foreground">Folders</dt>
                  <dd className="space-y-0.5">
                    {(container.mounts ?? []).length === 0 && <span>none</span>}
                    {(container.mounts ?? []).map((mount) => <p key={`${mount.source}-${mount.destination}`} className="break-all font-mono">{mount.source} to {mount.destination}</p>)}
                  </dd>
                </dl>
              )}

              <div className="flex flex-wrap gap-2">
                {absent && <Button size="sm" disabled={actionsOff} onClick={() => runJob('start', start)}>Create and start</Button>}
                {conflicted && <p className="basis-full text-xs text-amber-300">{container?.detail ?? 'Another container already uses this name and is not MARM.'}</p>}
                {!absent && !running && !conflicted && <Button size="sm" disabled={actionsOff} onClick={() => runJob('start', start)}>Start</Button>}
                {running && <Button size="sm" variant="outline" disabled={actionsOff} onClick={() => control(restart)}>Restart</Button>}
                {running && <Button size="sm" variant="outline" disabled={actionsOff} onClick={() => setStopOpen(true)}>Stop</Button>}
                <Button size="sm" variant="outline" disabled={actionsOff} onClick={() => runJob('pull', pull)}>Pull latest</Button>
                {!absent && !conflicted && <Button size="sm" variant="ghost" onClick={() => setLogsOpen((open) => !open)}>{logsOpen ? 'Hide logs' : 'Logs'}</Button>}
              </div>

              <JobLine job={job} status={jobQuery.data} />
              {actionError && <ErrorState message={actionError} />}

              {logsOpen && (
                <div className="space-y-2">
                  <Button size="sm" variant="outline" isLoading={logs.isFetching} onClick={() => void logs.refetch()}>Refresh logs</Button>
                  {logs.isError
                    ? <ErrorState message={mutationMessage(logs.error)} />
                    : <pre aria-label="Container logs" className="max-h-72 overflow-auto rounded-lg border border-border/60 bg-background/60 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">{logs.data ? (logs.data.lines.join('\n') || 'No log lines yet.') : 'Loading...'}</pre>}
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </section>

      {data && form && (
        <section className="space-y-5">
          <SectionHeading title="Run configuration" description="How the MARM container is started. Saved here and used every time it is created." />
          <Card>
            <CardContent className="space-y-4 p-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field id="docker-tag" label="Image tag"><Input id="docker-tag" disabled={readOnly} value={form.tag} onChange={(e) => edit({ tag: e.target.value })} className="font-mono text-xs" /></Field>
                <Field id="docker-port" label="Host port"><Input id="docker-port" type="number" inputMode="numeric" disabled={readOnly} value={form.port} onChange={(e) => edit({ port: e.target.value })} className={cn('font-mono text-xs', !formValid(form) && 'border-destructive/60')} /></Field>
                <Field id="docker-memory" label="Memory" help="For example 2g. Leave empty for no limit."><Input id="docker-memory" disabled={readOnly} value={form.memory} onChange={(e) => edit({ memory: e.target.value })} className="font-mono text-xs" /></Field>
                <Field id="docker-cpus" label="CPUs" help="For example 1.5. Leave empty for no limit."><Input id="docker-cpus" disabled={readOnly} value={form.cpus} onChange={(e) => edit({ cpus: e.target.value })} className="font-mono text-xs" /></Field>
                <Field id="docker-data" label="Data folder" help="Where MARM keeps its memories on this machine."><Input id="docker-data" disabled={readOnly} value={form.data_dir} onChange={(e) => edit({ data_dir: e.target.value })} className="font-mono text-xs" /></Field>
                <Field id="docker-profile" label="Profile"><NativeSelect id="docker-profile" disabled={readOnly} value={form.profile} onChange={(e) => edit({ profile: e.target.value })}>
                  {!PROFILES.some((profile) => profile.id === form.profile) && <option value={form.profile}>{form.profile}</option>}
                  {PROFILES.map((profile) => <option key={profile.id} value={profile.id}>{profile.label}</option>)}
                </NativeSelect></Field>
                <Field id="docker-rate" label="Rate limit per minute" help="Empty uses the profile default."><Input id="docker-rate" type="number" min={0} inputMode="numeric" disabled={readOnly} value={form.rate} onChange={(e) => edit({ rate: e.target.value })} className="font-mono text-xs" /></Field>
              </div>

              <div className="space-y-2">
                <p className="text-sm font-medium">Repositories</p>
                <p className="text-xs text-muted-foreground">Mounted read-only so MARM can index them.</p>
                {form.repos.map((repo, index) => (
                  <div key={index} className="flex gap-2">
                    <Input aria-label={`Repository folder ${index + 1}`} disabled={readOnly} value={repo} onChange={(e) => edit({ repos: form.repos.map((item, i) => (i === index ? e.target.value : item)) })} className="font-mono text-xs" />
                    <Button size="icon" variant="ghost" aria-label={`Remove repository ${index + 1}`} disabled={readOnly} onClick={() => edit({ repos: form.repos.filter((_, i) => i !== index) })}><X className="h-4 w-4" /></Button>
                  </div>
                ))}
                <Button size="sm" variant="outline" disabled={readOnly} onClick={() => edit({ repos: [...form.repos, ''] })}><Plus className="mr-2 h-3.5 w-3.5" />Add repository</Button>
              </div>

              <div className="flex items-start justify-between gap-3 border-t border-border/60 pt-4">
                <div>
                  <p className="text-sm">Reachable from other devices</p>
                  <p className="text-xs text-muted-foreground">Requires a key. MARM creates one if needed.</p>
                </div>
                <Toggle label="Reachable from other devices" checked={form.expose} disabled={readOnly} onChange={(next) => edit({ expose: next })} />
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-4">
                <p className="text-sm text-muted-foreground" role="status">{dirty ? 'You have unsaved changes.' : 'No unsaved changes.'}</p>
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="ghost" size="sm" disabled={!draft} onClick={() => { setDraft(null); setSaveError(null); }}>Discard</Button>
                  <Button size="sm" variant="outline" disabled={readOnly || !dirty || !valid || busy} isLoading={updateConfig.isPending} onClick={() => save()}>Save</Button>
                  <Button size="sm" disabled={actionsOff || !valid} onClick={() => setRecreateOpen(true)}>Save and recreate container</Button>
                </div>
              </div>
              {saveError && <ErrorState message={saveError} />}
              {!valid && <p className="text-xs text-destructive">Enter a port from 1 to 65535 and a whole number for the rate limit.</p>}

              <div className="flex flex-wrap gap-2 border-t border-border/60 pt-4">
                <Button size="sm" variant="outline" onClick={() => setPreviewOpen((open) => !open)}>{previewOpen ? 'Hide compose preview' : 'Preview compose'}</Button>
                <Button size="sm" variant="outline" disabled={readOnly} isLoading={writeCompose.isPending} onClick={() => writeFile(false)}>Write compose file</Button>
              </div>

              {previewOpen && (
                compose.isError ? <ErrorState message={mutationMessage(compose.error)} />
                : compose.data ? (
                  <div className="space-y-2">
                    <pre aria-label="Compose file preview" className="max-h-72 overflow-auto rounded-lg border border-border/60 bg-background/60 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">{compose.data.yaml}</pre>
                    <CommandLine command={compose.data.command} />
                  </div>
                ) : <LoadingState label="Building preview..." />
              )}

              {conflict && (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-400/30 bg-amber-400/[0.05] p-3 text-sm text-amber-200" role="alert">
                  <p>A compose file already exists{conflict.path ? ` at ${conflict.path}` : ''}.</p>
                  <Button size="sm" variant="outline" isLoading={writeCompose.isPending} onClick={() => writeFile(true)}>Overwrite</Button>
                </div>
              )}
              {written && (
                <div className="space-y-2 rounded-lg border border-emerald-500/30 bg-emerald-500/[0.06] p-3 text-sm text-emerald-200" role="status">
                  <p className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 shrink-0" />Compose file written to <span className="break-all font-mono text-xs">{written.path}</span></p>
                  <CommandLine command={written.command} />
                </div>
              )}
            </CardContent>
          </Card>
        </section>
      )}

      <AgentsGrid title="Agents on Docker" onRequest={onRequestConnection} allowedTransports={['http', 'docker-stdio']} target="docker" />

      <Dialog open={stopOpen} onOpenChange={setStopOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Stop the MARM container?</DialogTitle>
            <DialogDescription>Agents using Docker lose MARM until you start it again.</DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setStopOpen(false)}>Cancel</Button>
            <Button variant="destructive" onClick={() => { setStopOpen(false); control(stop); }}>Stop</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={recreateOpen} onOpenChange={setRecreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save and recreate?</DialogTitle>
            <DialogDescription>MARM stops and removes the container, then starts a new one with this configuration. Agents lose MARM for a moment. Your data folder is kept.</DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setRecreateOpen(false)}>Cancel</Button>
            <Button onClick={saveAndRecreate}>Save and recreate</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Field({ id, label, help, children }: { id: string; label: string; help?: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-sm font-medium">{label}</label>
      {children}
      {help && <p className="text-xs text-muted-foreground">{help}</p>}
    </div>
  );
}

function CommandLine({ command }: { command: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-background/60 px-3 py-1.5">
      <span className="select-all break-all font-mono text-xs">{command}</span>
      <CopyButton value={command} label="Copy command" />
    </div>
  );
}

function JobLine({ job, status }: { job: { id: string; kind: JobKind } | null; status: { status: string; seconds?: number; detail?: string } | undefined }) {
  if (!job) return null;
  const text = JOB_TEXT[job.kind];
  const failed = status?.status === 'error';
  const done = status?.status === 'done';
  return (
    <div className={cn('flex items-start gap-3 rounded-lg border p-3 text-sm', failed ? 'border-destructive/35 bg-destructive/[0.06]' : done ? 'border-emerald-500/30 bg-emerald-500/[0.06]' : 'status-pulse border-primary/35 bg-primary/[0.06]')} role="status" aria-live="polite">
      {failed ? <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" /> : done ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" /> : <RefreshCw className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-primary" />}
      <p className={failed ? 'text-destructive' : done ? 'text-emerald-200' : 'text-muted-foreground'}>
        {failed ? status?.detail || text.failed : done ? `${text.done} in ${(status?.seconds ?? 0).toFixed(1)} s` : text.running}
      </p>
    </div>
  );
}
