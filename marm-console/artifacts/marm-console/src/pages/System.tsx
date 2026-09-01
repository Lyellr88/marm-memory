import { useState, type ReactNode } from 'react';
import { Activity, Archive, BookOpen, Bot, CheckCircle2, CircleAlert, Database, FolderSync, Gauge, HardDrive, Network, Power, RefreshCw, Search, SlidersHorizontal, Stethoscope, Terminal, Trash2, Workflow, Wrench, XCircle } from 'lucide-react';
import { useRuntimeSettings, useUpdateRuntimeAutomation, useUpdateRuntimeProfile, useMaintenance, useDoctor, useRuntimeLogs, useUpgradeCheck, useBackups, useCreateBackup, useDeleteBackup, useStartCompactionDryRun, useCompactionDryRunJob, useStartReloadDocs, useReloadDocsJob } from '@/hooks/use-marm-queries';
import { Button, Input, Label } from '@/components/ui/core';
import type { RuntimeProfile, RuntimeSettings } from '@/lib/marm-types';

type SystemSection = 'health' | 'controls' | 'automation' | 'maintenance' | 'lifecycle' | 'backup' | 'storage' | 'watch';

const SECTIONS: Array<{ id: SystemSection; label: string; icon: typeof Network }> = [
  { id: 'health', label: 'Health', icon: Activity },
  { id: 'controls', label: 'Controls', icon: SlidersHorizontal },
  { id: 'automation', label: 'Automation', icon: Workflow },
  { id: 'maintenance', label: 'Maintenance', icon: Wrench },
  { id: 'lifecycle', label: 'Lifecycle', icon: Power },
  { id: 'backup', label: 'Backup', icon: Archive },
  { id: 'storage', label: 'Storage & models', icon: Database },
  { id: 'watch', label: 'Watch health', icon: FolderSync },
];

export function SystemPage() {
  const [section, setSection] = useState<SystemSection>('health');
  const runtime = useRuntimeSettings();
  const updateAutomation = useUpdateRuntimeAutomation();
  const updateProfile = useUpdateRuntimeProfile();
  const [rpmDraft, setRpmDraft] = useState('');
  const [sessionDraft, setSessionDraft] = useState('');
  const [logLines, setLogLines] = useState(200);
  const [upgradeAsked, setUpgradeAsked] = useState(false);
  const maintenance = useMaintenance(section === 'maintenance');
  const doctor = useDoctor(section === 'lifecycle');
  const logs = useRuntimeLogs(logLines, section === 'lifecycle');
  const upgrade = useUpgradeCheck(upgradeAsked);
  const backups = useBackups(section === 'backup');
  const createBackup = useCreateBackup();
  const deleteBackup = useDeleteBackup();
  const [dryRunJobId, setDryRunJobId] = useState<string | null>(null);
  const startDryRun = useStartCompactionDryRun();
  const dryRunJob = useCompactionDryRunJob(dryRunJobId);
  const [reloadJobId, setReloadJobId] = useState<string | null>(null);
  const startReloadDocs = useStartReloadDocs();
  const reloadJob = useReloadDocsJob(reloadJobId);

  const data = runtime.data;
  const errorMessage = runtime.error instanceof Error ? runtime.error.message : 'Runtime diagnostics are unavailable.';

  return (
    <div className="page-enter flex h-full min-h-0 gap-6 p-6">
      <nav className="settings-dialog-nav w-48 shrink-0 space-y-1" aria-label="System sections">
        {SECTIONS.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" onClick={() => setSection(id)} className="settings-dialog-nav-item" data-active={section === id} aria-current={section === id ? 'page' : undefined}>
            <Icon className="h-3.5 w-3.5" /> {label}
          </button>
        ))}
      </nav>

      <main className="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
        {section === 'health' && <section className="space-y-5">
          <SectionHeading title="Runtime health" description="Live diagnostics from the connected MARM runtime. This page refreshes while it is open." />
          {runtime.isLoading && <LoadingState label="Reading runtime health…" />}
          {runtime.isError && <ErrorState message={errorMessage} />}
          {data && <>
            <div className="grid gap-3 sm:grid-cols-3">
              <StatusCard icon={<CheckCircle2 className="h-4 w-4 text-emerald-400" />} label="Runtime" value={data.status === 'ready' ? 'Ready' : data.status} detail={`v${data.version} · ${data.profile}`} />
              <StatusCard icon={<Activity className="h-4 w-4 text-primary" />} label="Write queue" value={data.write_queue.running ? 'Running' : 'Stopped'} detail={`${data.write_queue.depth} of ${data.write_queue.capacity} queued`} />
              <StatusCard icon={<Network className="h-4 w-4 text-violet-400" />} label="Graph engine" value={String(data.graph.state || 'Unknown')} detail={data.runtime_id ? `runtime ${data.runtime_id}` : `process ${data.pid}`} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl border border-border/80 bg-card/45 p-5">
                <div className="flex items-start gap-3">
                  <Gauge className="mt-0.5 h-5 w-5 text-primary" />
                  <div>
                    <p className="font-medium">Rate limit</p>
                    <p className="mt-1 text-sm text-muted-foreground">{data.rate_limit.enforced ? `${data.rate_limit.requests_per_minute} requests per minute, per IP.` : 'Not enforced. Every request is allowed.'}</p>
                  </div>
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                  <SmallStat label="Profile" value={data.profile} />
                  <SmallStat label="Block for" value={`${data.rate_limit.block_seconds}s`} />
                  <SmallStat label="Env default" value={String(data.rate_limit.environment_default)} tone={data.rate_limit.requests_per_minute === data.rate_limit.environment_default ? undefined : 'warn'} />
                </div>
              </div>
              <div className="rounded-xl border border-border/80 bg-card/45 p-5">
                <div className="flex items-start gap-3">
                  <Search className="mt-0.5 h-5 w-5 text-violet-400" />
                  <div>
                    <p className="font-medium">Semantic search</p>
                    <p className="mt-1 text-sm text-muted-foreground">{semanticSummary(data.search)}</p>
                  </div>
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                  <SmallStat label="Turned on" value={data.search.semantic_enabled ? 'Yes' : 'No'} tone={data.search.semantic_enabled ? 'good' : 'warn'} />
                  <SmallStat label="Model installed" value={data.search.semantic_available ? 'Yes' : 'No'} tone={data.search.semantic_available ? 'good' : 'warn'} />
                  <SmallStat label="Model" value={MODEL_STATE_LABEL[data.search.model_state] ?? data.search.model_state} tone={MODEL_STATE_TONE[data.search.model_state]} />
                </div>
              </div>
            </div>
            <div className="rounded-xl border border-border/80 bg-card/45 p-5 text-sm">
              <div className="flex items-center justify-between gap-4"><span className="font-medium">Runtime identity</span><span className="font-mono text-xs text-muted-foreground">PID {data.pid}</span></div>
              <p className="mt-2 text-sm text-muted-foreground">The Console reports state only; it does not start, stop, or restart the runtime from this screen.</p>
            </div>
          </>}
        </section>}

        {section === 'controls' && <section className="space-y-5">
          <SectionHeading title="Runtime controls" description="Rate-limit profile for the connected runtime. Changes apply immediately and are saved for the next start." />
          {runtime.isLoading && <LoadingState label="Reading runtime controls…" />}
          {runtime.isError && <ErrorState message={errorMessage} />}
          {data && <>
            <div className="rounded-xl border border-border/80 bg-card/45 p-5">
              <div className="flex items-start justify-between gap-4">
                <div><p className="font-medium">Profile</p><p className="mt-1 text-sm text-muted-foreground">Presets that trade request throttling against throughput for multi-agent work.</p></div>
                <span className="rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary-highlight">{data.rate_limit.enforced ? `${data.rate_limit.requests_per_minute} rpm` : 'Unlimited'}</span>
              </div>
              <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {PROFILES.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    disabled={updateProfile.isPending}
                    onClick={() => { setRpmDraft(''); updateProfile.mutate({ profile: option.id }); }}
                    className="project-explorer-tab !min-h-0 !flex-col !items-start gap-1 p-3 text-left disabled:opacity-60"
                    data-state={data.profile === option.id ? 'active' : 'inactive'}
                  >
                    <span className="text-sm font-semibold">{option.label}</span>
                    <span className="text-xs text-muted-foreground">{option.detail}</span>
                  </button>
                ))}
              </div>
              <p className="mt-4 border-t border-border/60 pt-4 text-xs text-muted-foreground">Saved like the automation toggles. The runtime picks this up on its next start unless you pass an explicit <span className="font-mono">--profile</span> flag, which always wins.</p>
            </div>

            <div className="rounded-xl border border-border/80 bg-card/45 p-5">
              <div className="flex items-start gap-3">
                <Gauge className="mt-0.5 h-5 w-5 text-primary" />
                <div><p className="font-medium">Custom rate limit</p><p className="mt-1 text-sm text-muted-foreground">Override the requests-per-minute cap directly. Zero disables throttling entirely.</p></div>
              </div>
              <div className="mt-5 flex flex-wrap items-end gap-3">
                <div className="grid gap-2">
                  <Label htmlFor="rpm">Requests per minute</Label>
                  <Input id="rpm" type="number" min={0} inputMode="numeric" value={rpmDraft} onChange={(event) => setRpmDraft(event.target.value)} placeholder={String(data.rate_limit.requests_per_minute)} className="w-40 font-mono text-xs" />
                </div>
                <Button
                  isLoading={updateProfile.isPending}
                  disabled={!isValidRpm(rpmDraft)}
                  onClick={() => updateProfile.mutate({ profile: (data.profile as RuntimeProfile) || 'standard', rateLimitRpm: Number(rpmDraft) })}
                >Apply limit</Button>
                {rpmDraft !== '' && !isValidRpm(rpmDraft) && <p className="text-xs text-amber-300">Enter a whole number of zero or more.</p>}
              </div>
              {data.profile === 'trusted' && <p className="mt-4 rounded-lg border border-amber-400/20 bg-amber-400/[0.05] p-3 text-xs text-amber-200">Trusted means no limit, so applying a number here switches the profile to Standard with that limit.</p>}
              {updateProfile.data && updateProfile.data.profile !== updateProfile.data.requested_profile && <p className="mt-4 rounded-lg border border-border/70 bg-background/35 p-3 text-xs text-muted-foreground">Profile switched to <span className="font-mono">{updateProfile.data.profile}</span> so the limit of {updateProfile.data.rate_limit.requests_per_minute} could apply.</p>}
            </div>
            {updateProfile.error && <ErrorState message={updateProfile.error instanceof Error ? updateProfile.error.message : 'Could not change the runtime profile.'} />}
          </>}
        </section>}

        {section === 'automation' && <section className="space-y-5">
          <SectionHeading title="Background automation" description="These settings persist in MARM’s runtime database and take effect on each worker’s next cycle." />
          {runtime.isLoading && <LoadingState label="Reading automatic-indexing state…" />}
          {runtime.isError && <ErrorState message={errorMessage} />}
          {data && <div className="grid gap-4 lg:grid-cols-2">
            <AutomationCard icon={<FolderSync className="h-5 w-5 text-primary" />} title="Code graph re-indexing" description="Watches indexed repositories for committed and working-tree changes." state={data.automation.graph} pending={updateAutomation.isPending} onChange={(enabled) => updateAutomation.mutate({ scope: 'graph', enabled })} />
            <AutomationCard icon={<Bot className="h-5 w-5 text-violet-400" />} title="Concept extraction" description="Processes the durable memory outbox into the isolated concept graph." state={data.automation.concept} pending={updateAutomation.isPending} onChange={(enabled) => updateAutomation.mutate({ scope: 'concept', enabled })} />
          </div>}
          {updateAutomation.error && <ErrorState message={updateAutomation.error instanceof Error ? updateAutomation.error.message : 'Could not update automatic indexing.'} />}
        </section>}

        {section === 'maintenance' && <section className="space-y-5">
          <SectionHeading title="Maintenance" description="Scans and rebuilds for the local stores. Some of this cannot run while the runtime is serving." />
          {maintenance.isLoading && <LoadingState label="Checking what can run…" />}
          {maintenance.isError && <ErrorState message={maintenance.error instanceof Error ? maintenance.error.message : 'Maintenance state is unavailable.'} />}
          {maintenance.data && <>
            <div className="rounded-xl border border-border/80 bg-card/45 p-5">
              <div className="flex items-start gap-3">
                <Search className="mt-0.5 h-5 w-5 text-primary" />
                <div><p className="font-medium">Compaction dry run</p><p className="mt-1 text-sm text-muted-foreground">Read-only scan for memories a session could compact. Changes nothing.</p></div>
              </div>
              <div className="mt-5 flex flex-wrap items-end gap-3">
                <div className="grid gap-2">
                  <Label htmlFor="dry-session">Session name</Label>
                  <Input id="dry-session" value={sessionDraft} onChange={(event) => setSessionDraft(event.target.value)} placeholder="general" className="w-56 font-mono text-xs" />
                </div>
                <Button
                  isLoading={startDryRun.isPending || dryRunJob.data?.status === 'queued' || dryRunJob.data?.status === 'running'}
                  disabled={!sessionDraft.trim()}
                  onClick={() => { setDryRunJobId(null); startDryRun.mutate(sessionDraft.trim(), { onSuccess: (job) => setDryRunJobId(job.job_id) }); }}
                >Scan session</Button>
              </div>
              {dryRunJob.data?.status === 'queued' && <p className="mt-4 text-sm text-muted-foreground">Queued…</p>}
              {dryRunJob.data?.status === 'running' && <p className="mt-4 flex items-center text-sm text-muted-foreground"><RefreshCw className="mr-2 h-3.5 w-3.5 animate-spin" />Scanning. Larger sessions take longer, and this keeps running if you leave the page.</p>}
              {dryRunJob.data?.status === 'success' && <p className="mt-4 rounded-lg border border-border/70 bg-background/35 p-3 text-sm text-muted-foreground">{dryRunJob.data.candidates.length === 0 ? 'No compaction candidates found for that session.' : `${dryRunJob.data.candidates.length} candidate group(s) found. Review them on the Memories tab.`}</p>}
              {dryRunJob.data?.status === 'error' && <div className="mt-4"><ErrorState message={dryRunJob.data.error || 'The scan failed.'} /></div>}
              {startDryRun.error && <div className="mt-4"><ErrorState message={startDryRun.error instanceof Error ? startDryRun.error.message : 'Could not start the scan.'} /></div>}
              <CommandHint command={maintenance.data.actions.compaction_dry_run.command} />
            </div>

            <div className="rounded-xl border border-border/80 bg-card/45 p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex gap-3">
                  <BookOpen className="mt-0.5 h-5 w-5 text-violet-400" />
                  <div><p className="font-medium">Reload documentation</p><p className="mt-1 text-sm text-muted-foreground">Re-reads MARM's bundled docs into the memory system. Safe to run at any time.</p></div>
                </div>
                <Button
                  isLoading={startReloadDocs.isPending || reloadJob.data?.status === 'queued' || reloadJob.data?.status === 'running'}
                  onClick={() => { setReloadJobId(null); startReloadDocs.mutate(undefined, { onSuccess: (job) => setReloadJobId(job.job_id) }); }}
                >Reload</Button>
              </div>
              {reloadJob.data?.status === 'queued' && <p className="mt-4 text-sm text-muted-foreground">Queued…</p>}
              {reloadJob.data?.status === 'running' && <p className="mt-4 flex items-center text-sm text-muted-foreground"><RefreshCw className="mr-2 h-3.5 w-3.5 animate-spin" />Reloading. Each document goes through the write queue, so a busy runtime takes longer.</p>}
              {reloadJob.data?.status === 'success' && <p className="mt-4 rounded-lg border border-emerald-400/20 bg-emerald-400/[0.05] p-3 text-sm text-emerald-200">{reloadJob.data.message || 'Documentation reloaded.'}</p>}
              {reloadJob.data?.status === 'error' && <div className="mt-4"><ErrorState message={reloadJob.data.error || 'The reload failed.'} /></div>}
              {startReloadDocs.error && <div className="mt-4"><ErrorState message={startReloadDocs.error instanceof Error ? startReloadDocs.error.message : 'Could not start the reload.'} /></div>}
            </div>

            <div className="rounded-xl border border-border/80 bg-card/45 p-5">
              <div className="flex items-start gap-3">
                <Wrench className="mt-0.5 h-5 w-5 text-amber-400" />
                <div><p className="font-medium">Rebuilds that need a stopped runtime</p><p className="mt-1 text-sm text-muted-foreground">These rewrite rows the live connection pool holds open, so they refuse to run while a server is answering. Run them from your terminal.</p></div>
              </div>
              <div className="mt-5 space-y-3">
                <BlockedAction title="Re-embed stored vectors" action={maintenance.data.actions.embeddings_migrate} />
                <BlockedAction title="Re-chunk stored memories" action={maintenance.data.actions.chunks_rechunk} />
              </div>
            </div>
          </>}
        </section>}

        {section === 'lifecycle' && <section className="space-y-5">
          <SectionHeading title="Lifecycle" description="Diagnostics, runtime logs, and release checks. The Console runs on its own port, so it stays up independently of the runtime." />
          <div className="rounded-xl border border-border/80 bg-card/45 p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="flex gap-3">
                <Stethoscope className="mt-0.5 h-5 w-5 text-primary" />
                <div><p className="font-medium">Doctor</p><p className="mt-1 text-sm text-muted-foreground">Environment checks for this installation.</p></div>
              </div>
              <Button size="sm" variant="outline" onClick={() => doctor.refetch()} isLoading={doctor.isFetching}><RefreshCw className="mr-2 h-3.5 w-3.5" />Re-run</Button>
            </div>
            {doctor.isLoading && <div className="mt-5"><LoadingState label="Running checks…" /></div>}
            {doctor.isError && <div className="mt-5"><ErrorState message={doctor.error instanceof Error ? doctor.error.message : 'Doctor is unavailable.'} /></div>}
            {doctor.data && <div className="mt-5 space-y-2">
              {doctor.data.checks.map((check) => (
                <div key={check.name} className="flex items-start gap-3 rounded-lg border border-border/70 bg-background/35 p-3">
                  {check.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />}
                  <div className="min-w-0"><p className="font-mono text-xs">{check.name}</p><p className="mt-1 text-xs text-muted-foreground">{check.detail}</p></div>
                </div>
              ))}
            </div>}
          </div>

          <div className="rounded-xl border border-border/80 bg-card/45 p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="flex gap-3">
                <Terminal className="mt-0.5 h-5 w-5 text-primary" />
                <div><p className="font-medium">Runtime log</p><p className="mt-1 truncate font-mono text-xs text-muted-foreground" title={logs.data?.path}>{logs.data?.path || 'Managed runtime log'}</p></div>
              </div>
              <div className="flex items-center gap-2">
                {[100, 200, 500, 1000].map((count) => (
                  <button key={count} type="button" onClick={() => setLogLines(count)} className="project-explorer-tab !min-h-0 px-2 py-1 text-xs" data-state={logLines === count ? 'active' : 'inactive'}>{count}</button>
                ))}
              </div>
            </div>
            {logs.isError && <div className="mt-5"><ErrorState message={logs.error instanceof Error ? logs.error.message : 'The runtime log is unavailable.'} /></div>}
            {logs.data && (logs.data.exists
              ? <pre className="mt-5 max-h-96 overflow-auto rounded-lg border border-border/60 bg-background/60 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">{logs.data.lines.join('\n') || 'The log is empty.'}</pre>
              : <p className="mt-5 rounded-lg border border-dashed border-border/70 bg-background/25 p-4 text-sm text-muted-foreground">No managed runtime log exists yet. It appears once the runtime is started by the CLI.</p>)}
            <p className="mt-3 text-xs text-muted-foreground">Refreshes every 5 seconds while this section is open.</p>
          </div>

          <div className="rounded-xl border border-border/80 bg-card/45 p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="flex gap-3">
                <Power className="mt-0.5 h-5 w-5 text-violet-400" />
                <div><p className="font-medium">Release</p><p className="mt-1 text-sm text-muted-foreground">Check PyPI for a newer MARM release. Nothing is installed from here.</p></div>
              </div>
              <Button size="sm" variant="outline" isLoading={upgrade.isFetching} onClick={() => { setUpgradeAsked(true); upgrade.refetch(); }}>Check for updates</Button>
            </div>
            {upgrade.isError && <div className="mt-5"><ErrorState message={upgrade.error instanceof Error ? upgrade.error.message : 'Could not reach PyPI.'} /></div>}
            {upgrade.data && <>
              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                <SmallStat label="Installed" value={upgrade.data.installed_version} />
                <SmallStat label="Latest" value={upgrade.data.latest_version} tone={upgrade.data.state === 'current' ? 'good' : 'warn'} />
                <SmallStat label="Installer" value={upgrade.data.editable ? 'editable' : upgrade.data.installer || 'unknown'} />
              </div>
              {upgrade.data.state !== 'current' && <CommandHint command={upgrade.data.command} />}
            </>}
          </div>

          <div className="rounded-xl border border-dashed border-border/70 bg-background/25 p-5">
            <p className="font-medium">Stopping and restarting stays in the terminal</p>
            <p className="mt-1 text-sm text-muted-foreground">The Console does not stop or restart the runtime. The shutdown route does not reliably stop a server it did not launch, so a button here could report success while the runtime kept serving.</p>
            <CommandHint command={'marm-memory stop    marm-memory restart'} />
          </div>
        </section>}

        {section === 'backup' && <section className="space-y-5">
          <SectionHeading title="Backup" description="Point-in-time snapshots of the memory database. Taken online, so nothing needs to stop." />
          <div className="rounded-xl border border-border/80 bg-card/45 p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="flex gap-3">
                <Archive className="mt-0.5 h-5 w-5 text-primary" />
                <div><p className="font-medium">Snapshots</p><p className="mt-1 truncate font-mono text-xs text-muted-foreground" title={backups.data?.directory}>{backups.data?.directory || 'Snapshot directory'}</p></div>
              </div>
              <Button isLoading={createBackup.isPending} onClick={() => createBackup.mutate()}>Take snapshot</Button>
            </div>
            {createBackup.error && <div className="mt-5"><ErrorState message={createBackup.error instanceof Error ? createBackup.error.message : 'The snapshot failed.'} /></div>}
            {deleteBackup.error && <div className="mt-5"><ErrorState message={deleteBackup.error instanceof Error ? deleteBackup.error.message : 'Could not delete that snapshot.'} /></div>}
            {backups.isLoading && <div className="mt-5"><LoadingState label="Reading snapshots…" /></div>}
            {backups.isError && <div className="mt-5"><ErrorState message={backups.error instanceof Error ? backups.error.message : 'Snapshots are unavailable.'} /></div>}
            {backups.data && (backups.data.items.length === 0
              ? <p className="mt-5 rounded-lg border border-dashed border-border/70 bg-background/25 p-4 text-sm text-muted-foreground">No snapshots yet.</p>
              : <div className="mt-5 space-y-2">
                  {backups.data.items.map((item) => (
                    <div key={item.name} className="flex items-center justify-between gap-3 rounded-lg border border-border/70 bg-background/35 p-3">
                      <div className="min-w-0">
                        <p className="truncate font-mono text-xs">{item.name}</p>
                        <p className="mt-1 text-xs text-muted-foreground">{formatBytes(item.size_bytes)} · {new Date(item.created_at).toLocaleString()}</p>
                      </div>
                      <Button size="sm" variant="ghost" isLoading={deleteBackup.isPending && deleteBackup.variables === item.name} onClick={() => deleteBackup.mutate(item.name)} aria-label={`Delete ${item.name}`}><Trash2 className="h-3.5 w-3.5" /></Button>
                    </div>
                  ))}
                </div>)}
            <p className="mt-4 border-t border-border/60 pt-4 text-xs text-muted-foreground">Restoring is not available here. Stop the runtime, replace the database file, then start it again.</p>
          </div>
        </section>}

        {section === 'storage' && <section className="space-y-5">
          <SectionHeading title="Storage & models" description="Read-only diagnostics for the local stores and semantic retrieval model." />
          {runtime.isLoading && <LoadingState label="Reading storage diagnostics…" />}
          {runtime.isError && <ErrorState message={errorMessage} />}
          {data && <>
            <div className="grid gap-4 lg:grid-cols-2">
              <StorageCard icon={<HardDrive className="h-5 w-5 text-primary" />} title="Memory database" data={data.storage.memory} />
              <StorageCard icon={<Database className="h-5 w-5 text-violet-400" />} title="Concept database" data={data.storage.concept} />
            </div>
            <div className="rounded-xl border border-border/80 bg-card/45 p-5">
              <div className="flex items-start gap-3">
                <Bot className="mt-0.5 h-5 w-5 text-primary" />
                <div><p className="font-medium">Embedding model</p><p className="mt-1 break-all font-mono text-xs text-muted-foreground">{data.embedding.model}</p></div>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-4">
                <SmallStat label="Dimensions" value={String(data.embedding.dimension)} />
                <SmallStat label="Compatibility" value={data.embedding.compatible ? 'Compatible' : 'Needs migration'} tone={data.embedding.compatible ? 'good' : 'warn'} />
                <SmallStat label="Old vectors" value={String(data.embedding.incompatible_vectors)} />
                <SmallStat label="Model marker" value={data.embedding.marker || 'Not recorded'} />
              </div>
              {data.embedding.errors.length > 0 && <p className="mt-4 rounded-lg border border-amber-400/20 bg-amber-400/[0.05] p-3 text-xs text-amber-200">{data.embedding.errors.join(' ')}</p>}
            </div>
          </>}
        </section>}

        {section === 'watch' && <section className="space-y-5">
          <SectionHeading title="Project watch health" description="Reasons the automatic code watcher intentionally leaves a repository alone." />
          {runtime.isLoading && <LoadingState label="Reading project watch health…" />}
          {runtime.isError && <ErrorState message={errorMessage} />}
          {data && <>
            <WatchList title="Suppressed projects" description="These paths were removed from the graph and are guarded from being immediately re-created by a watcher." items={data.automation.graph.suppressed_projects || []} />
            <WatchList title="Unindexable projects" description="These paths have a durable indexing block, such as a Windows path-length limitation. A successful manual reindex clears the block." items={data.automation.graph.unindexable_projects || []} tone="warn" />
          </>}
        </section>}
      </main>
    </div>
  );
}

function CommandHint({ command }: { command: string | null }) {
  if (!command) return null;
  return <p className="mt-4 overflow-x-auto rounded-lg border border-border/60 bg-background/60 p-3 font-mono text-[11px] text-muted-foreground">{command}</p>;
}

function BlockedAction({ title, action }: { title: string; action: { runnable: boolean; command: string | null; reason?: string } }) {
  return (
    <div className="rounded-lg border border-border/70 bg-background/35 p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium">{title}</p>
        <span className="rounded-full border border-amber-400/25 bg-amber-400/10 px-2 py-0.5 text-[10px] font-medium text-amber-200">CLI only</span>
      </div>
      {action.reason && <p className="mt-1 text-xs text-muted-foreground">{action.reason}</p>}
      <CommandHint command={action.command} />
    </div>
  );
}

const PROFILES: Array<{ id: RuntimeProfile; label: string; detail: string }> = [
  { id: 'standard', label: 'Standard', detail: 'Default throttling' },
  { id: 'swarm', label: 'Swarm', detail: '200 rpm' },
  { id: 'swarm-max', label: 'Swarm max', detail: '600 rpm' },
  { id: 'trusted', label: 'Trusted', detail: 'No limit' },
];

function isValidRpm(draft: string) {
  return /^\d+$/.test(draft.trim());
}

const MODEL_STATE_LABEL: Record<RuntimeSettings['search']['model_state'], string> = {
  loaded: 'Loaded',
  loading: 'Loading',
  failed: 'Failed',
  not_loaded: 'Not loaded yet',
};

const MODEL_STATE_TONE: Record<RuntimeSettings['search']['model_state'], 'good' | 'warn' | undefined> = {
  loaded: 'good',
  loading: undefined,
  failed: 'warn',
  not_loaded: undefined,
};

function semanticSummary(search: RuntimeSettings['search']) {
  if (!search.semantic_enabled) return 'Turned off. Recall uses keyword search only.';
  if (!search.semantic_available) return 'Turned on, but fastembed is not installed. Recall uses keyword search only.';
  if (search.model_state === 'failed') return 'The embedding model failed to load. Recall has fallen back to keyword search.';
  if (search.model_state === 'loading') return 'The embedding model is loading. Recall uses keyword search until it finishes.';
  if (search.model_state === 'not_loaded') return 'Ready. The model loads on the first recall that needs it.';
  return 'Recall ranks by meaning as well as keywords.';
}

function SectionHeading({ title, description }: { title: string; description: string }) { return <div><h2 className="text-base font-semibold">{title}</h2><p className="mt-1 text-sm text-muted-foreground">{description}</p></div>; }
function LoadingState({ label }: { label: string }) { return <div className="flex min-h-40 items-center justify-center rounded-xl border border-dashed border-border/80 text-sm text-muted-foreground"><RefreshCw className="mr-2 h-4 w-4 animate-spin" />{label}</div>; }
function ErrorState({ message }: { message: string }) { return <div className="rounded-xl border border-destructive/25 bg-destructive/[0.05] p-4 text-sm text-destructive"><XCircle className="mr-2 inline h-4 w-4" />{message}</div>; }
function StatusCard({ icon, label, value, detail }: { icon: ReactNode; label: string; value: string; detail: string }) { return <div className="rounded-xl border border-border/80 bg-card/45 p-4"><div className="flex items-center gap-2 text-xs text-muted-foreground">{icon}{label}</div><p className="mt-3 text-lg font-semibold capitalize">{value}</p><p className="mt-1 truncate text-xs text-muted-foreground" title={detail}>{detail}</p></div>; }
function AutomationCard({ icon, title, description, state, pending, onChange }: { icon: ReactNode; title: string; description: string; state: { enabled: boolean; source: string; environment_default: boolean }; pending: boolean; onChange: (enabled: boolean) => void }) { return <div className="rounded-xl border border-border/80 bg-card/45 p-5"><div className="flex items-start justify-between gap-4"><div className="flex gap-3">{icon}<div><p className="font-medium">{title}</p><p className="mt-1 text-sm text-muted-foreground">{description}</p></div></div><span className={state.enabled ? 'rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2 py-0.5 text-xs font-semibold text-emerald-300' : 'rounded-full border border-border px-2 py-0.5 text-xs font-semibold text-muted-foreground'}>{state.enabled ? 'On' : 'Off'}</span></div><div className="mt-5 flex items-center justify-between gap-3 border-t border-border/60 pt-4"><p className="text-xs text-muted-foreground">{state.source === 'saved_override' ? 'Saved override' : 'Environment default'} · default {state.environment_default ? 'on' : 'off'}</p><Button size="sm" variant={state.enabled ? 'outline' : 'default'} isLoading={pending} onClick={() => onChange(!state.enabled)}>{state.enabled ? 'Pause' : 'Enable'}</Button></div></div>; }
function StorageCard({ icon, title, data }: { icon: ReactNode; title: string; data: { path?: string; exists: boolean; size_bytes?: number } }) { return <div className="rounded-xl border border-border/80 bg-card/45 p-5"><div className="flex items-center gap-3">{icon}<div><p className="font-medium">{title}</p><p className={data.exists ? 'mt-1 text-xs text-emerald-300' : 'mt-1 text-xs text-amber-300'}>{data.exists ? 'Available' : 'Not found'}</p></div></div><p className="mt-5 break-all rounded-lg border border-border/60 bg-background/35 p-3 font-mono text-xs text-muted-foreground">{data.path || 'Path unavailable'}</p>{typeof data.size_bytes === 'number' && <p className="mt-3 text-xs text-muted-foreground">{formatBytes(data.size_bytes)}</p>}</div>; }
function SmallStat({ label, value, tone }: { label: string; value: string; tone?: 'good' | 'warn' }) { return <div className="rounded-lg border border-border/70 bg-background/30 p-3"><p className="text-xs text-muted-foreground">{label}</p><p className={`mt-1 truncate text-sm font-semibold capitalize ${tone === 'good' ? 'text-emerald-300' : tone === 'warn' ? 'text-amber-300' : ''}`} title={value}>{value}</p></div>; }
function WatchList({ title, description, items, tone }: { title: string; description: string; items: string[]; tone?: 'warn' }) { return <section className="rounded-xl border border-border/80 bg-card/45 p-5"><div className="flex items-start gap-3"><CircleAlert className={`mt-0.5 h-5 w-5 ${tone === 'warn' ? 'text-amber-400' : 'text-primary'}`} /><div><h3 className="font-medium">{title}</h3><p className="mt-1 text-sm text-muted-foreground">{description}</p></div></div>{items.length === 0 ? <p className="mt-5 rounded-lg border border-dashed border-border/70 bg-background/25 p-4 text-sm text-muted-foreground">Nothing needs attention.</p> : <div className="mt-5 space-y-2">{items.map((item) => <p key={item} className="break-all rounded-lg border border-border/70 bg-background/35 p-3 font-mono text-xs">{item}</p>)}</div>}</section>; }
function formatBytes(bytes: number) { if (bytes < 1024) return `${bytes} B`; if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`; return `${(bytes / (1024 * 1024)).toFixed(1)} MB`; }
