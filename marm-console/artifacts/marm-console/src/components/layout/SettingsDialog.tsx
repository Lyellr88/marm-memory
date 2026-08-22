import { useEffect, useState, type ReactNode } from 'react';
import { Activity, Bot, CheckCircle2, CircleAlert, Database, FolderSync, HardDrive, KeyRound, Network, RefreshCw, ServerCog, Workflow, XCircle } from 'lucide-react';
import { useConnection } from '@/lib/marm-connection';
import { useRuntimeSettings, useUpdateRuntimeAutomation } from '@/hooks/use-marm-queries';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Button, Input, Label } from '@/components/ui/core';

type SettingsSection = 'connection' | 'runtime' | 'automation' | 'data' | 'watch';

const SECTIONS: Array<{ id: SettingsSection; label: string; icon: typeof Network }> = [
  { id: 'connection', label: 'Connection', icon: Network },
  { id: 'runtime', label: 'Runtime', icon: Activity },
  { id: 'automation', label: 'Automation', icon: Workflow },
  { id: 'data', label: 'Data & models', icon: Database },
  { id: 'watch', label: 'Watch health', icon: FolderSync },
];

export function SettingsDialog({ open, onOpenChange }: { open: boolean, onOpenChange: (open: boolean) => void }) {
  const { baseUrl, apiKey, clearApiKey, setBaseUrl, setApiKey } = useConnection();
  const [section, setSection] = useState<SettingsSection>('connection');
  const [localUrl, setLocalUrl] = useState(baseUrl);
  const [localKey, setLocalKey] = useState(apiKey || '');
  const runtime = useRuntimeSettings(open);
  const updateAutomation = useUpdateRuntimeAutomation();

  useEffect(() => {
    if (open) {
      setLocalUrl(baseUrl);
      setLocalKey(apiKey || '');
    }
  }, [open, baseUrl, apiKey]);

  const handleSave = () => {
    setBaseUrl(localUrl);
    setApiKey(localKey || null);
    onOpenChange(false);
  };

  const runtimeData = runtime.data;
  const errorMessage = runtime.error instanceof Error ? runtime.error.message : 'Runtime diagnostics are unavailable.';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="settings-dialog !flex !h-[40rem] !max-h-[calc(100vh-2rem)] !max-w-5xl !flex-col !gap-0 !p-0">
        <DialogHeader className="settings-dialog-header shrink-0 border-b border-border/70 px-6 py-5 pr-16">
          <div className="flex items-start gap-3">
            <div className="settings-dialog-mark"><ServerCog className="h-4 w-4" /></div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">Local control plane</p>
              <DialogTitle className="mt-1">MARM settings</DialogTitle>
              <DialogDescription className="mt-1">Connection, runtime health, and durable background automation.</DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 overflow-hidden">
          <nav className="settings-dialog-nav w-44 shrink-0 border-r border-border/70 bg-background/20 p-3" aria-label="Settings sections">
            {SECTIONS.map(({ id, label, icon: Icon }) => (
              <button key={id} type="button" onClick={() => setSection(id)} className="settings-dialog-nav-item" data-active={section === id} aria-current={section === id ? 'page' : undefined}>
                <Icon className="h-3.5 w-3.5" /> {label}
              </button>
            ))}
          </nav>

          <main className="min-h-0 flex-1 overflow-y-auto p-6 [scrollbar-gutter:stable]">
            {section === 'connection' && <section className="max-w-2xl space-y-6">
              <SectionHeading title="Connection" description="Where this browser reaches your local MARM Console." />
              <div className="grid gap-4 rounded-xl border border-border/80 bg-card/45 p-5">
                <div className="grid gap-2"><Label htmlFor="base-url">Console base URL</Label><Input id="base-url" value={localUrl} onChange={(event) => setLocalUrl(event.target.value)} placeholder="http://127.0.0.1:8002" className="font-mono text-xs" /><p className="text-xs text-muted-foreground">Saved locally in this browser. The Console then securely talks to the MCP runtime.</p></div>
                <div className="grid gap-2"><Label htmlFor="api-key">API key (Bearer token)</Label><Input id="api-key" type="password" value={localKey} onChange={(event) => setLocalKey(event.target.value)} placeholder="Optional" className="font-mono text-xs" /><div className="flex items-center justify-between gap-3 text-xs text-muted-foreground"><span>{apiKey ? 'A token is held only in this browser tab.' : 'No token is held in this browser tab.'}</span>{apiKey && <Button size="sm" variant="ghost" onClick={() => { clearApiKey(); setLocalKey(''); }}>Clear token</Button>}</div></div>
              </div>
            </section>}

            {section === 'runtime' && <section className="space-y-5">
              <SectionHeading title="Runtime health" description="Live diagnostics from the connected MARM runtime. This page refreshes while it is open." />
              {runtime.isLoading && <LoadingState label="Reading runtime health…" />}
              {runtime.isError && <ErrorState message={errorMessage} />}
              {runtimeData && <><div className="grid gap-3 sm:grid-cols-3"><StatusCard icon={<CheckCircle2 className="h-4 w-4 text-emerald-400" />} label="Runtime" value={runtimeData.status === 'ready' ? 'Ready' : runtimeData.status} detail={`v${runtimeData.version} · ${runtimeData.profile}`} /><StatusCard icon={<Activity className="h-4 w-4 text-primary" />} label="Write queue" value={runtimeData.write_queue.running ? 'Running' : 'Stopped'} detail={`${runtimeData.write_queue.depth} of ${runtimeData.write_queue.capacity} queued`} /><StatusCard icon={<Network className="h-4 w-4 text-violet-400" />} label="Graph engine" value={String(runtimeData.graph.state || 'Unknown')} detail={runtimeData.runtime_id ? `runtime ${runtimeData.runtime_id}` : `process ${runtimeData.pid}`} /></div><div className="rounded-xl border border-border/80 bg-card/45 p-5 text-sm"><div className="flex items-center justify-between gap-4"><span className="font-medium">Runtime identity</span><span className="font-mono text-xs text-muted-foreground">PID {runtimeData.pid}</span></div><p className="mt-2 text-sm text-muted-foreground">The Console reports state only; it does not start, stop, or restart the runtime from this screen.</p></div></>}
            </section>}

            {section === 'automation' && <section className="space-y-5">
              <SectionHeading title="Background automation" description="These settings persist in MARM’s runtime database and take effect on each worker’s next cycle." />
              {runtime.isLoading && <LoadingState label="Reading automatic-indexing state…" />}
              {runtime.isError && <ErrorState message={errorMessage} />}
              {runtimeData && <div className="grid gap-4 lg:grid-cols-2"><AutomationCard icon={<FolderSync className="h-5 w-5 text-primary" />} title="Code graph re-indexing" description="Watches indexed repositories for committed and working-tree changes." state={runtimeData.automation.graph} pending={updateAutomation.isPending} onChange={(enabled) => updateAutomation.mutate({ scope: 'graph', enabled })} /><AutomationCard icon={<Bot className="h-5 w-5 text-violet-400" />} title="Concept extraction" description="Processes the durable memory outbox into the isolated concept graph." state={runtimeData.automation.concept} pending={updateAutomation.isPending} onChange={(enabled) => updateAutomation.mutate({ scope: 'concept', enabled })} /></div>}
              {updateAutomation.error && <ErrorState message={updateAutomation.error instanceof Error ? updateAutomation.error.message : 'Could not update automatic indexing.'} />}
            </section>}

            {section === 'data' && <section className="space-y-5">
              <SectionHeading title="Data & models" description="Read-only diagnostics for the local stores and semantic retrieval model." />
              {runtime.isLoading && <LoadingState label="Reading storage diagnostics…" />}
              {runtime.isError && <ErrorState message={errorMessage} />}
              {runtimeData && <><div className="grid gap-4 lg:grid-cols-2"><StorageCard icon={<HardDrive className="h-5 w-5 text-primary" />} title="Memory database" data={runtimeData.storage.memory} /><StorageCard icon={<Database className="h-5 w-5 text-violet-400" />} title="Concept database" data={runtimeData.storage.concept} /></div><div className="rounded-xl border border-border/80 bg-card/45 p-5"><div className="flex items-start gap-3"><Bot className="mt-0.5 h-5 w-5 text-primary" /><div><p className="font-medium">Embedding model</p><p className="mt-1 break-all font-mono text-xs text-muted-foreground">{runtimeData.embedding.model}</p></div></div><div className="mt-4 grid gap-3 sm:grid-cols-3"><SmallStat label="Compatibility" value={runtimeData.embedding.compatible ? 'Compatible' : 'Needs migration'} tone={runtimeData.embedding.compatible ? 'good' : 'warn'} /><SmallStat label="Old vectors" value={String(runtimeData.embedding.incompatible_vectors)} /><SmallStat label="Model marker" value={runtimeData.embedding.marker || 'Not recorded'} /></div>{runtimeData.embedding.errors.length > 0 && <p className="mt-4 rounded-lg border border-amber-400/20 bg-amber-400/[0.05] p-3 text-xs text-amber-200">{runtimeData.embedding.errors.join(' ')}</p>}</div></>}
            </section>}

            {section === 'watch' && <section className="space-y-5">
              <SectionHeading title="Project watch health" description="Reasons the automatic code watcher intentionally leaves a repository alone." />
              {runtime.isLoading && <LoadingState label="Reading project watch health…" />}
              {runtime.isError && <ErrorState message={errorMessage} />}
              {runtimeData && <><WatchList title="Suppressed projects" description="These paths were removed from the graph and are guarded from being immediately re-created by a watcher." items={runtimeData.automation.graph.suppressed_projects || []} /><WatchList title="Unindexable projects" description="These paths have a durable indexing block, such as a Windows path-length limitation. A successful manual reindex clears the block." items={runtimeData.automation.graph.unindexable_projects || []} tone="warn" /></>}
            </section>}
          </main>
        </div>

        <DialogFooter className="shrink-0 border-t border-border/70 px-6 py-4"><Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>{section === 'connection' && <Button onClick={handleSave}><KeyRound className="mr-2 h-4 w-4" />Save connection</Button>}</DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SectionHeading({ title, description }: { title: string; description: string }) { return <div><h2 className="text-base font-semibold">{title}</h2><p className="mt-1 text-sm text-muted-foreground">{description}</p></div>; }
function LoadingState({ label }: { label: string }) { return <div className="flex min-h-40 items-center justify-center rounded-xl border border-dashed border-border/80 text-sm text-muted-foreground"><RefreshCw className="mr-2 h-4 w-4 animate-spin" />{label}</div>; }
function ErrorState({ message }: { message: string }) { return <div className="rounded-xl border border-destructive/25 bg-destructive/[0.05] p-4 text-sm text-destructive"><XCircle className="mr-2 inline h-4 w-4" />{message}</div>; }
function StatusCard({ icon, label, value, detail }: { icon: ReactNode; label: string; value: string; detail: string }) { return <div className="rounded-xl border border-border/80 bg-card/45 p-4"><div className="flex items-center gap-2 text-xs text-muted-foreground">{icon}{label}</div><p className="mt-3 text-lg font-semibold capitalize">{value}</p><p className="mt-1 truncate text-xs text-muted-foreground" title={detail}>{detail}</p></div>; }
function AutomationCard({ icon, title, description, state, pending, onChange }: { icon: ReactNode; title: string; description: string; state: { enabled: boolean; source: string; environment_default: boolean }; pending: boolean; onChange: (enabled: boolean) => void }) { return <div className="rounded-xl border border-border/80 bg-card/45 p-5"><div className="flex items-start justify-between gap-4"><div className="flex gap-3">{icon}<div><p className="font-medium">{title}</p><p className="mt-1 text-sm text-muted-foreground">{description}</p></div></div><span className={state.enabled ? 'rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2 py-0.5 text-xs font-semibold text-emerald-300' : 'rounded-full border border-border px-2 py-0.5 text-xs font-semibold text-muted-foreground'}>{state.enabled ? 'On' : 'Off'}</span></div><div className="mt-5 flex items-center justify-between gap-3 border-t border-border/60 pt-4"><p className="text-xs text-muted-foreground">{state.source === 'saved_override' ? 'Saved override' : 'Environment default'} · default {state.environment_default ? 'on' : 'off'}</p><Button size="sm" variant={state.enabled ? 'outline' : 'default'} isLoading={pending} onClick={() => onChange(!state.enabled)}>{state.enabled ? 'Pause' : 'Enable'}</Button></div></div>; }
function StorageCard({ icon, title, data }: { icon: ReactNode; title: string; data: { path?: string; exists: boolean; size_bytes?: number } }) { return <div className="rounded-xl border border-border/80 bg-card/45 p-5"><div className="flex items-center gap-3">{icon}<div><p className="font-medium">{title}</p><p className={data.exists ? 'mt-1 text-xs text-emerald-300' : 'mt-1 text-xs text-amber-300'}>{data.exists ? 'Available' : 'Not found'}</p></div></div><p className="mt-5 break-all rounded-lg border border-border/60 bg-background/35 p-3 font-mono text-xs text-muted-foreground">{data.path || 'Path unavailable'}</p>{typeof data.size_bytes === 'number' && <p className="mt-3 text-xs text-muted-foreground">{formatBytes(data.size_bytes)}</p>}</div>; }
function SmallStat({ label, value, tone }: { label: string; value: string; tone?: 'good' | 'warn' }) { return <div className="rounded-lg border border-border/70 bg-background/30 p-3"><p className="text-xs text-muted-foreground">{label}</p><p className={`mt-1 text-sm font-semibold ${tone === 'good' ? 'text-emerald-300' : tone === 'warn' ? 'text-amber-300' : ''}`}>{value}</p></div>; }
function WatchList({ title, description, items, tone }: { title: string; description: string; items: string[]; tone?: 'warn' }) { return <section className="rounded-xl border border-border/80 bg-card/45 p-5"><div className="flex items-start gap-3"><CircleAlert className={`mt-0.5 h-5 w-5 ${tone === 'warn' ? 'text-amber-400' : 'text-primary'}`} /><div><h3 className="font-medium">{title}</h3><p className="mt-1 text-sm text-muted-foreground">{description}</p></div></div>{items.length === 0 ? <p className="mt-5 rounded-lg border border-dashed border-border/70 bg-background/25 p-4 text-sm text-muted-foreground">Nothing needs attention.</p> : <div className="mt-5 space-y-2">{items.map((item) => <p key={item} className="break-all rounded-lg border border-border/70 bg-background/35 p-3 font-mono text-xs">{item}</p>)}</div>}</section>; }
function formatBytes(bytes: number) { if (bytes < 1024) return `${bytes} B`; if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`; return `${(bytes / (1024 * 1024)).toFixed(1)} MB`; }
