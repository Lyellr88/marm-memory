import { useState, type ReactNode } from 'react';
import { Activity, Archive, BookOpen, Bot, CheckCircle2, CircleAlert, Database, FolderSync, Gauge, HardDrive, Network, Power, RefreshCw, Search, Stethoscope, Terminal, Trash2, Wrench, XCircle } from 'lucide-react';
import { useRuntimeSettings, useUpdateRuntimeAutomation, useUpdateRuntimeProfile, useMaintenance, useDoctor, useRuntimeLogs, useUpgradeCheck, useBackups, useCreateBackup, useDeleteBackup, useStartCompactionDryRun, useCompactionDryRunJob, useStartReloadDocs, useReloadDocsJob } from '@/hooks/use-marm-queries';
import { Button, Input, Label, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/core';
import { Panel, SectionHeading, SmallStat, StatCard } from '@/components/ui/panels';
import type { RuntimeProfile, RuntimeSettings } from '@/lib/marm-types';

type SystemTab = 'health' | 'controls' | 'maintenance' | 'diagnostics';

export function SystemPage() {
  const [tab, setTab] = useState<SystemTab>('health');
  const runtime = useRuntimeSettings();
  const updateAutomation = useUpdateRuntimeAutomation();
  const updateProfile = useUpdateRuntimeProfile();
  const [rpmDraft, setRpmDraft] = useState('');
  const [sessionDraft, setSessionDraft] = useState('');
  const [logLines, setLogLines] = useState(200);
  const [upgradeAsked, setUpgradeAsked] = useState(false);
  const maintenance = useMaintenance(tab === 'maintenance');
  const doctor = useDoctor(tab === 'diagnostics');
  const logs = useRuntimeLogs(logLines, tab === 'diagnostics');
  const upgrade = useUpgradeCheck(upgradeAsked);
  const backups = useBackups(tab === 'maintenance');
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
    <div className="page-enter flex h-full flex-col overflow-hidden p-7 xl:p-8">
      <div className="mb-6 shrink-0">
        <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">System control plane</div>
        <h1 className="text-[1.8rem] font-semibold tracking-[-0.045em]">System</h1>
        <p className="mt-1 text-sm text-muted-foreground">Runtime health, rate-limit controls, maintenance jobs, and local data.</p>
      </div>

      <Tabs value={tab} onValueChange={(value) => setTab(value as SystemTab)} className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <TabsList className="mb-4 h-auto w-full shrink-0 justify-start self-start rounded-none border-x-0 border-t-0 border-b bg-transparent p-0">
          <TabsTrigger value="health" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent py-3 px-5">Health</TabsTrigger>
          <TabsTrigger value="controls" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent py-3 px-5">Controls</TabsTrigger>
          <TabsTrigger value="maintenance" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent py-3 px-5">Maintenance</TabsTrigger>
          <TabsTrigger value="diagnostics" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent py-3 px-5">Diagnostics</TabsTrigger>
        </TabsList>

        <div className="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
          <TabsContent value="health" className="system-panel m-0 space-y-8">
            <section className="space-y-5">
              <SectionHeading title="Runtime health" description="Live diagnostics from the connected MARM runtime. This page refreshes while it is open." />
              {runtime.isLoading && <LoadingState label="Reading runtime health…" />}
              {runtime.isError && <ErrorState message={errorMessage} />}
              {data && <>
                <div className="grid gap-3 sm:grid-cols-3">
                  <StatCard tone="emerald" delay={0} icon={<CheckCircle2 className="h-5 w-5" />} label="Runtime" value={data.status === 'ready' ? 'Ready' : data.status} detail={`v${data.version} · ${data.profile}`} />
                  <StatCard tone="cyan" delay={55} icon={<Activity className="h-5 w-5" />} label="Write queue" value={data.write_queue.running ? 'Running' : 'Stopped'} detail={`${data.write_queue.depth} of ${data.write_queue.capacity} queued`} />
                  <StatCard tone="violet" delay={110} icon={<Network className="h-5 w-5" />} label="Graph engine" value={String(data.graph.state || 'Unknown')} detail={data.runtime_id ? `runtime ${data.runtime_id}` : `process ${data.pid}`} />
                </div>
                <div className="grid gap-4 lg:grid-cols-2">
                  <Panel
                    icon={<Gauge className={`h-5 w-5 ${data.rate_limit.enforced ? 'text-primary' : 'text-amber-400'}`} />}
                    title="Rate limit"
                    description={<>{data.rate_limit.enforced ? `${data.rate_limit.requests_per_minute} requests per minute, per IP.` : 'Not enforced. Every request is allowed.'}</>}
                    alert={!data.rate_limit.enforced}
                  >
                    <div className="mt-4 grid gap-3 sm:grid-cols-3">
                      <SmallStat label="Profile" value={data.profile} />
                      <SmallStat label="Block for" value={`${data.rate_limit.block_seconds}s`} />
                      <SmallStat label="Env default" value={String(data.rate_limit.environment_default)} tone={data.rate_limit.requests_per_minute === data.rate_limit.environment_default ? undefined : 'warn'} />
                    </div>
                  </Panel>
                  <Panel
                    icon={<Search className="h-5 w-5 text-violet-400" />}
                    title="Semantic search"
                    description={<>{semanticSummary(data.search)}</>}
                  >
                    <div className="mt-4 grid gap-3 sm:grid-cols-3">
                      <SmallStat label="Turned on" value={data.search.semantic_enabled ? 'Yes' : 'No'} tone={data.search.semantic_enabled ? 'good' : 'warn'} />
                      <SmallStat label="Model installed" value={data.search.semantic_available ? 'Yes' : 'No'} tone={data.search.semantic_available ? 'good' : 'warn'} />
                      <SmallStat label="Model" value={MODEL_STATE_LABEL[data.search.model_state] ?? data.search.model_state} tone={MODEL_STATE_TONE[data.search.model_state]} />
                    </div>
                  </Panel>
                </div>
                <Panel
                  title="Runtime identity"
                  description={<>The Console reports state only; it does not start, stop, or restart the runtime from this screen.</>}
                  action={<span className="font-mono text-xs text-muted-foreground">PID {data.pid}</span>}
                />
              </>}
            </section>

            <section className="space-y-5">
              <SectionHeading title="Storage & models" description="Read-only diagnostics for the local stores and semantic retrieval model." />
              {runtime.isLoading && <LoadingState label="Reading storage diagnostics…" />}
              {runtime.isError && <ErrorState message={errorMessage} />}
              {data && <>
                <div className="grid gap-4 lg:grid-cols-2">
                  <StorageCard icon={<HardDrive className="h-5 w-5 text-primary" />} title="Memory database" data={data.storage.memory} />
                  <StorageCard icon={<Database className="h-5 w-5 text-violet-400" />} title="Concept database" data={data.storage.concept} />
                </div>
                <Panel
                  icon={<Bot className="h-5 w-5 text-primary" />}
                  title="Embedding model"
                  description={<span className="block break-all font-mono text-xs text-muted-foreground">{data.embedding.model}</span>}
                >
                  <div className="mt-4 grid gap-3 sm:grid-cols-4">
                    <SmallStat label="Dimensions" value={String(data.embedding.dimension)} />
                    <SmallStat label="Compatibility" value={data.embedding.compatible ? 'Compatible' : 'Needs migration'} tone={data.embedding.compatible ? 'good' : 'warn'} />
                    <SmallStat label="Old vectors" value={String(data.embedding.incompatible_vectors)} />
                    <SmallStat label="Model marker" value={data.embedding.marker || 'Not recorded'} />
                  </div>
                  {data.embedding.errors.length > 0 && <p className="mt-4 rounded-lg border border-amber-400/20 bg-amber-400/[0.05] p-3 text-xs text-amber-200">{data.embedding.errors.join(' ')}</p>}
                </Panel>
              </>}
            </section>
          </TabsContent>
          <TabsContent value="controls" className="system-panel m-0 space-y-8">
            <section className="space-y-5">
              <SectionHeading title="Runtime controls" description="Rate-limit profile for the connected runtime. Changes apply immediately and are saved for the next start." />
              {runtime.isLoading && <LoadingState label="Reading runtime controls…" />}
              {runtime.isError && <ErrorState message={errorMessage} />}
              {data && <>
                <div className="grid gap-4 lg:grid-cols-2">
                  <Panel
                    icon={<Gauge className="h-5 w-5 text-primary" />}
                    title="Profile"
                    description={<>Presets that trade request throttling against throughput for multi-agent work.</>}
                    action={<span className="rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary-highlight">{data.rate_limit.enforced ? `${data.rate_limit.requests_per_minute} rpm` : 'Unlimited'}</span>}
                  >
                    <div className="mt-5 grid gap-3 sm:grid-cols-2">
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
                  </Panel>

                  <Panel
                    icon={<Gauge className="h-5 w-5 text-primary" />}
                    title="Custom rate limit"
                    description={<>Override the requests-per-minute cap directly. Zero disables throttling entirely.</>}
                  >
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
                  </Panel>
                </div>
                {updateProfile.error && <ErrorState message={updateProfile.error instanceof Error ? updateProfile.error.message : 'Could not change the runtime profile.'} />}
              </>}
            </section>

            <section className="space-y-5">
              <SectionHeading title="Background automation" description="These settings persist in MARM’s runtime database and take effect on each worker’s next cycle." />
              {runtime.isLoading && <LoadingState label="Reading automatic-indexing state…" />}
              {runtime.isError && <ErrorState message={errorMessage} />}
              {data && <div className="grid gap-4 lg:grid-cols-2">
                <AutomationCard icon={<FolderSync className="h-5 w-5 text-primary" />} title="Code graph re-indexing" description="Watches indexed repositories for committed and working-tree changes." state={data.automation.graph} pending={updateAutomation.isPending} onChange={(enabled) => updateAutomation.mutate({ scope: 'graph', enabled })} />
                <AutomationCard icon={<Bot className="h-5 w-5 text-violet-400" />} title="Concept extraction" description="Processes the durable memory outbox into the isolated concept graph." state={data.automation.concept} pending={updateAutomation.isPending} onChange={(enabled) => updateAutomation.mutate({ scope: 'concept', enabled })} />
              </div>}
              {updateAutomation.error && <ErrorState message={updateAutomation.error instanceof Error ? updateAutomation.error.message : 'Could not update automatic indexing.'} />}
            </section>

            <section className="space-y-5">
              <SectionHeading title="Project watch health" description="Reasons the automatic code watcher intentionally leaves a repository alone." />
              {runtime.isLoading && <LoadingState label="Reading project watch health…" />}
              {runtime.isError && <ErrorState message={errorMessage} />}
              {data && <>
                <div className="grid gap-4 lg:grid-cols-2">
                  <WatchList title="Suppressed projects" description="These paths were removed from the graph and are guarded from being immediately re-created by a watcher." items={data.automation.graph.suppressed_projects || []} />
                  <WatchList title="Unindexable projects" description="These paths have a durable indexing block, such as a Windows path-length limitation. A successful manual reindex clears the block." items={data.automation.graph.unindexable_projects || []} tone="warn" />
                </div>
              </>}
            </section>
          </TabsContent>
          <TabsContent value="maintenance" className="system-panel m-0 space-y-8">
            <section className="space-y-5">
              <SectionHeading title="Maintenance" description="Scans and rebuilds for the local stores. Some of this cannot run while the runtime is serving." />
              {maintenance.isLoading && <LoadingState label="Checking what can run…" />}
              {maintenance.isError && <ErrorState message={maintenance.error instanceof Error ? maintenance.error.message : 'Maintenance state is unavailable.'} />}
              {maintenance.data && <>
                <div className="grid gap-4 lg:grid-cols-2">
                  <Panel
                    icon={<Search className="h-5 w-5 text-primary" />}
                    title="Compaction dry run"
                    description={<>Read-only scan for memories a session could compact. Changes nothing.</>}
                  >
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
                    {dryRunJob.data && <JobPanel
                      status={dryRunJob.data.status}
                      running="Scanning. Larger sessions take longer, and this keeps running if you leave the page."
                      success={dryRunJob.data.candidates.length === 0 ? 'No compaction candidates found for that session.' : `${dryRunJob.data.candidates.length} candidate group(s) found. Review them on the Memories tab.`}
                      error={dryRunJob.data.error}
                    />}
                    {startDryRun.error && <div className="mt-4"><ErrorState message={startDryRun.error instanceof Error ? startDryRun.error.message : 'Could not start the scan.'} /></div>}
                    <CommandHint command={maintenance.data.actions.compaction_dry_run.command} />
                  </Panel>

                  <Panel
                    icon={<BookOpen className="h-5 w-5 text-violet-400" />}
                    title="Reload documentation"
                    description={<>Re-reads MARM's bundled docs into the memory system. Safe to run at any time.</>}
                    action={<Button
                        isLoading={startReloadDocs.isPending || reloadJob.data?.status === 'queued' || reloadJob.data?.status === 'running'}
                        onClick={() => { setReloadJobId(null); startReloadDocs.mutate(undefined, { onSuccess: (job) => setReloadJobId(job.job_id) }); }}
                      >Reload</Button>}
                  >
                    {reloadJob.data && <JobPanel
                      status={reloadJob.data.status}
                      running="Reloading. Each document goes through the write queue, so a busy runtime takes longer."
                      success={reloadJob.data.message || 'Documentation reloaded.'}
                      error={reloadJob.data.error}
                    />}
                    {startReloadDocs.error && <div className="mt-4"><ErrorState message={startReloadDocs.error instanceof Error ? startReloadDocs.error.message : 'Could not start the reload.'} /></div>}
                  </Panel>
                </div>

                <Panel
                  icon={<Wrench className="h-5 w-5 text-amber-400" />}
                  title="Rebuilds that need a stopped runtime"
                  description={<>These rewrite rows the live connection pool holds open, so they refuse to run while a server is answering. Run them from your terminal.</>}
                >
                  <div className="mt-5 space-y-3">
                    <BlockedAction title="Re-embed stored vectors" action={maintenance.data.actions.embeddings_migrate} />
                    <BlockedAction title="Re-chunk stored memories" action={maintenance.data.actions.chunks_rechunk} />
                  </div>
                </Panel>
              </>}
            </section>

            <section className="space-y-5">
              <SectionHeading title="Backup" description="Point-in-time snapshots of the memory database. Taken online, so nothing needs to stop." />
              <Panel
                icon={<Archive className="h-5 w-5 text-primary" />}
                title="Snapshots"
                description={<span className="block truncate font-mono text-xs text-muted-foreground" title={backups.data?.directory}>{backups.data?.directory || 'Snapshot directory'}</span>}
                action={<Button isLoading={createBackup.isPending} onClick={() => createBackup.mutate()}>Take snapshot</Button>}
              >
                {createBackup.error && <div className="mt-5"><ErrorState message={createBackup.error instanceof Error ? createBackup.error.message : 'The snapshot failed.'} /></div>}
                {deleteBackup.error && <div className="mt-5"><ErrorState message={deleteBackup.error instanceof Error ? deleteBackup.error.message : 'Could not delete that snapshot.'} /></div>}
                {backups.isLoading && <div className="mt-5"><LoadingState label="Reading snapshots…" /></div>}
                {backups.isError && <div className="mt-5"><ErrorState message={backups.error instanceof Error ? backups.error.message : 'Snapshots are unavailable.'} /></div>}
                {backups.data && (backups.data.items.length === 0
                  ? <p className="mt-5 rounded-lg border border-dashed border-border/70 bg-background/25 p-4 text-sm text-muted-foreground">No snapshots yet.</p>
                  : <div className="mt-5 space-y-2">
                      {backups.data.items.map((item) => (
                        <div key={item.name} className={`flex items-center justify-between gap-3 rounded-lg border p-3 transition-colors duration-200 ${item.name === createBackup.data?.backup.name ? 'concept-run-new border-emerald-400/30 bg-emerald-400/[0.06]' : 'border-border/70 bg-background/35 hover:border-primary/25'}`}>
                          <div className="min-w-0">
                            <p className="truncate font-mono text-xs">{item.name}</p>
                            <p className="mt-1 text-xs text-muted-foreground">{formatBytes(item.size_bytes)} · {new Date(item.created_at).toLocaleString()}</p>
                          </div>
                          <Button size="sm" variant="ghost" isLoading={deleteBackup.isPending && deleteBackup.variables === item.name} onClick={() => deleteBackup.mutate(item.name)} aria-label={`Delete ${item.name}`}><Trash2 className="h-3.5 w-3.5" /></Button>
                        </div>
                      ))}
                    </div>)}
                <p className="mt-4 border-t border-border/60 pt-4 text-xs text-muted-foreground">Restoring is not available here. Stop the runtime, replace the database file, then start it again.</p>
              </Panel>
            </section>
          </TabsContent>
          <TabsContent value="diagnostics" className="system-panel m-0 space-y-8">
            <section className="space-y-5">
              <SectionHeading title="Lifecycle" description="Diagnostics, runtime logs, and release checks. The Console runs on its own port, so it stays up independently of the runtime." />
              <div className="grid gap-4 lg:grid-cols-2">
                <Panel
                  icon={<Stethoscope className="h-5 w-5 text-primary" />}
                  title="Doctor"
                  description={<>Environment checks for this installation.</>}
                  action={<Button size="sm" variant="outline" onClick={() => doctor.refetch()} isLoading={doctor.isFetching}><RefreshCw className="mr-2 h-3.5 w-3.5" />Re-run</Button>}
                >
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
                </Panel>

                <Panel
                  icon={<Power className="h-5 w-5 text-violet-400" />}
                  title="Release"
                  description={<>Check PyPI for a newer MARM release. Nothing is installed from here.</>}
                  action={<Button size="sm" variant="outline" isLoading={upgrade.isFetching} onClick={() => { setUpgradeAsked(true); upgrade.refetch(); }}>Check for updates</Button>}
                >
                  <div className="mt-5 grid gap-3 sm:grid-cols-3">
                    <SmallStat label="Installed" value={upgrade.data?.installed_version ?? data?.version ?? '—'} />
                    <SmallStat label="Latest" value={upgrade.data?.latest_version ?? 'Not checked'} tone={upgrade.data ? (upgrade.data.state === 'current' ? 'good' : 'warn') : undefined} />
                    <SmallStat label="Installer" value={upgrade.data ? (upgrade.data.editable ? 'editable' : upgrade.data.installer || 'unknown') : '—'} />
                  </div>
                  {upgrade.isError && <div className="mt-3"><ErrorState message={upgrade.error instanceof Error ? upgrade.error.message : 'Could not reach PyPI.'} /></div>}
                  {upgrade.data && upgrade.data.state !== 'current' && <CommandHint command={upgrade.data.command} />}
                  {!upgrade.data && !upgrade.isError && (
                    <p className="mt-4 text-xs text-muted-foreground">Check for updates to compare against the latest release on PyPI.</p>
                  )}
                </Panel>
              </div>

              <Panel
                icon={<Terminal className="h-5 w-5 text-primary" />}
                title="Runtime log"
                description={<span className="block truncate font-mono text-xs text-muted-foreground" title={logs.data?.path}>{logs.data?.path || 'Managed runtime log'}</span>}
                action={<div className="flex items-center gap-2">
                    {[100, 200, 500, 1000].map((count) => (
                      <button key={count} type="button" onClick={() => setLogLines(count)} className="project-explorer-tab !min-h-0 px-2 py-1 text-xs" data-state={logLines === count ? 'active' : 'inactive'}>{count}</button>
                    ))}
                  </div>}
              >
                {logs.isError && <div className="mt-5"><ErrorState message={logs.error instanceof Error ? logs.error.message : 'The runtime log is unavailable.'} /></div>}
                {logs.data && (logs.data.exists
                  ? <pre className="mt-5 max-h-96 overflow-auto rounded-lg border border-border/60 bg-background/60 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">{logs.data.lines.join('\n') || 'The log is empty.'}</pre>
                  : <p className="mt-5 rounded-lg border border-dashed border-border/70 bg-background/25 p-4 text-sm text-muted-foreground">No managed runtime log exists yet. It appears once the runtime is started by the CLI.</p>)}
                <p className="mt-3 text-xs text-muted-foreground">Refreshes every 5 seconds while this section is open.</p>
              </Panel>
            </section>
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}

function JobPanel({ status, running, success, error }: { status: 'queued' | 'running' | 'success' | 'error'; running: string; success: string; error: string | null }) {
  const active = status === 'queued' || status === 'running';
  const tone = active
    ? 'status-pulse border-primary/35 bg-primary/[0.06]'
    : status === 'success'
      ? 'success-pop border-emerald-500/30 bg-emerald-500/[0.06]'
      : 'border-destructive/35 bg-destructive/[0.06]';
  return (
    <div className={`mt-4 flex items-start gap-3 rounded-lg border p-3 text-sm ${tone}`} role="status" aria-live="polite">
      {active ? <RefreshCw className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-primary" /> : status === 'success' ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />}
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{status === 'queued' ? 'Queued' : status === 'running' ? 'Running' : status === 'success' ? 'Finished' : 'Failed'}</p>
        <p className={`mt-1 ${status === 'error' ? 'text-destructive' : status === 'success' ? 'text-emerald-200' : 'text-muted-foreground'}`}>{status === 'queued' ? 'Waiting to start…' : status === 'running' ? running : status === 'success' ? success : error || 'The job failed.'}</p>
      </div>
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

function LoadingState({ label }: { label: string }) { return <div className="flex min-h-40 items-center justify-center rounded-xl border border-dashed border-border/80 text-sm text-muted-foreground"><RefreshCw className="mr-2 h-4 w-4 animate-spin" />{label}</div>; }
function ErrorState({ message }: { message: string }) { return <div className="rounded-xl border border-destructive/25 bg-destructive/[0.05] p-4 text-sm text-destructive"><XCircle className="mr-2 inline h-4 w-4" />{message}</div>; }
function AutomationCard({ icon, title, description, state, pending, onChange }: { icon: ReactNode; title: string; description: string; state: { enabled: boolean; source: string; environment_default: boolean }; pending: boolean; onChange: (enabled: boolean) => void }) { return <Panel icon={icon} title={title} description={description} action={<span className={state.enabled ? 'rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2 py-0.5 text-xs font-semibold text-emerald-300' : 'rounded-full border border-border px-2 py-0.5 text-xs font-semibold text-muted-foreground'}>{state.enabled ? 'On' : 'Off'}</span>}><div className="mt-5 flex items-center justify-between gap-3 border-t border-border/60 pt-4"><p className="text-xs text-muted-foreground">{state.source === 'saved_override' ? 'Saved override' : 'Environment default'} · default {state.environment_default ? 'on' : 'off'}</p><Button size="sm" variant={state.enabled ? 'outline' : 'default'} isLoading={pending} onClick={() => onChange(!state.enabled)}>{state.enabled ? 'Pause' : 'Enable'}</Button></div></Panel>; }
function StorageCard({ icon, title, data }: { icon: ReactNode; title: string; data: { path?: string; exists: boolean; size_bytes?: number } }) { return <Panel icon={icon} title={title} description={<span className={data.exists ? 'block text-xs text-emerald-300' : 'block text-xs text-amber-300'}>{data.exists ? 'Available' : 'Not found'}</span>}><p className="mt-5 break-all rounded-lg border border-border/60 bg-background/35 p-3 font-mono text-xs text-muted-foreground">{data.path || 'Path unavailable'}</p>{typeof data.size_bytes === 'number' && <p className="mt-3 text-xs text-muted-foreground">{formatBytes(data.size_bytes)}</p>}</Panel>; }
function WatchList({ title, description, items, tone }: { title: string; description: string; items: string[]; tone?: 'warn' }) { return <Panel icon={<CircleAlert className={`h-5 w-5 ${tone === 'warn' ? 'text-amber-400' : 'text-primary'}`} />} title={title} description={description}>{items.length === 0 ? <p className="mt-5 rounded-lg border border-dashed border-border/70 bg-background/25 p-4 text-sm text-muted-foreground">Nothing needs attention.</p> : <div className="mt-5 space-y-2">{items.map((item) => <p key={item} className="break-all rounded-lg border border-border/70 bg-background/35 p-3 font-mono text-xs">{item}</p>)}</div>}</Panel>; }
function formatBytes(bytes: number) { if (bytes < 1024) return `${bytes} B`; if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`; return `${(bytes / (1024 * 1024)).toFixed(1)} MB`; }
