import { useState } from 'react';
import { CheckCircle2, XCircle } from 'lucide-react';
import { useAgentScope, useConfigureAgent, useInstallAgentSkill, useProjects, useRemoveAgent, useTestAgent } from '@/hooks/use-marm-queries';
import { Button, Card, CardContent, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, cn } from '@/components/ui/core';
import { CopyButton } from '@/components/code-context/shared';
import type { Agent, AgentConfigureResult, AgentScopeName, AgentState, AgentTestErrorKind, AgentTarget, AgentTestResult, AgentTransport } from '@/lib/marm-types';
import { NativeSelect, Pill, mutationMessage } from './controls';

const TRANSPORT_LABEL: Record<AgentTransport, string> = {
  http: 'HTTP',
  stdio: 'STDIO',
  'docker-stdio': 'Docker STDIO',
};

const STATE_PILL: Record<AgentState, { label: string; tone: 'neutral' | 'good' | 'warn' | 'bad' }> = {
  missing: { label: 'Not connected', tone: 'neutral' },
  configured: { label: 'Connected', tone: 'good' },
  different: { label: 'Needs update', tone: 'warn' },
  unreadable: { label: "Can't read file", tone: 'bad' },
};

const ACTION_LABEL: Record<string, string> = {
  create: 'Create file',
  add: 'Add entry',
  replace: 'Replace existing entry',
  none: 'Already set up',
};

const TEST_ERROR_TEXT: Partial<Record<AgentTestErrorKind, string>> = {
  refused: 'MARM is not running at that address.',
  timeout: 'MARM did not answer in time.',
  unauthorized: 'MARM rejected the key. Check MARM_API_KEY.',
  missing_entry: 'No MARM entry in this file yet. Connect first.',
  spawn_failed: 'Could not start MARM from this entry.',
};

const OTHER_FOLDER = '__other__';

type Outcome = { ok: boolean; text: string };

function testOutcome(result: AgentTestResult): Outcome {
  if (result.ok) return { ok: true, text: `MARM answered: ${result.tools ?? 0} tools in ${result.latency_ms ?? 0} ms` };
  const kind = result.error?.kind;
  return { ok: false, text: (kind && TEST_ERROR_TEXT[kind]) || result.error?.detail || 'The test failed.' };
}

function initials(label: string) {
  return label.split(/\s+/).filter(Boolean).slice(0, 2).map((word) => word[0]).join('').toUpperCase();
}

export function AgentCard({ agent, allowedTransports, configureAllowed, target }: { agent: Agent; allowedTransports: AgentTransport[]; configureAllowed: boolean; target?: AgentTarget }) {
  if (agent.id === 'xai') return <InfoCard agent={agent} />;
  return <ControlCard agent={agent} allowedTransports={allowedTransports} configureAllowed={configureAllowed} target={target} />;
}

function InfoCard({ agent }: { agent: Agent }) {
  const payload = JSON.stringify(agent.user.expected_entry ?? null, null, 2);
  return (
    <Card className="flex flex-col">
      <CardContent className="flex flex-1 flex-col gap-3 p-5">
        <p className="font-medium">{agent.label}</p>
        {agent.notes.map((note) => <p key={note} className="text-xs text-muted-foreground">{note}</p>)}
        <div className="relative">
          <pre className="max-h-48 overflow-auto rounded-lg border border-border/60 bg-background/60 p-3 pr-10 font-mono text-[11px] leading-relaxed text-muted-foreground">{payload}</pre>
          <CopyButton value={payload} label="Copy payload" className="absolute right-1 top-1" />
        </div>
      </CardContent>
    </Card>
  );
}

function ControlCard({ agent, allowedTransports, configureAllowed, target }: { agent: Agent; allowedTransports: AgentTransport[]; configureAllowed: boolean; target?: AgentTarget }) {
  const projects = useProjects();
  const configure = useConfigureAgent();
  const remove = useRemoveAgent();
  const test = useTestAgent();
  const installSkill = useInstallAgentSkill();

  const [scopeChoice, setScopeChoice] = useState('user');
  const [folderDraft, setFolderDraft] = useState('');
  const [folder, setFolder] = useState('');
  const [picked, setPicked] = useState<AgentTransport | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [preview, setPreview] = useState<AgentConfigureResult | null>(null);
  const [removeOpen, setRemoveOpen] = useState(false);
  const [busy, setBusy] = useState<'test' | 'skill' | null>(null);

  const supportsProject = agent.scopes.includes('project');
  const scope: AgentScopeName = scopeChoice === 'user' ? 'user' : 'project';
  const project = scope === 'project' ? (scopeChoice === OTHER_FOLDER ? folder : scopeChoice) || undefined : undefined;
  const awaitingFolder = scope === 'project' && !project;

  const scopeQuery = useAgentScope(agent.id, scope, project, scope === 'project' && !!project, target);
  const scopeState = scope === 'user' ? agent.user : scopeQuery.data;
  const scopeError = scope === 'project' && scopeQuery.isError ? mutationMessage(scopeQuery.error) : null;

  const transports = allowedTransports.filter((t) => agent.transports.includes(t));
  const usable = transports.filter((t) => !agent.unavailable[t]);
  const detected = scopeState?.transport_detected;
  const defaultTransport = detected && usable.includes(detected) ? detected : usable[0] ?? transports[0];
  const transport = picked && transports.includes(picked) ? picked : defaultTransport;
  const transportBlocked = !transport || !!agent.unavailable[transport];

  const state = scopeState?.state ?? 'missing';
  const configured = state === 'configured';
  const pill = STATE_PILL[state];
  const scopeBody = { scope, ...(project ? { project } : {}), ...(target ? { target } : {}) };
  const ready = configureAllowed && !awaitingFolder && !!scopeState;

  function changeScope(next: string) {
    setScopeChoice(next);
    setOutcome(null);
  }

  function openPreview() {
    if (!transport) return;
    setOutcome(null);
    configure.mutate(
      { id: agent.id, body: { ...scopeBody, transport, dry_run: true } },
      {
        onSuccess: (data) => setPreview(data),
        onError: (err) => setOutcome({ ok: false, text: mutationMessage(err) }),
      },
    );
  }

  function confirmWrite() {
    if (!transport) return;
    configure.mutate(
      { id: agent.id, body: { ...scopeBody, transport, dry_run: false } },
      {
        onSuccess: (data) => {
          setPreview(null);
          if (data.written && data.verified) setOutcome({ ok: true, text: `Written and verified. Restart ${agent.label} to load it.` });
          else if (data.written) setOutcome({ ok: false, text: 'Written but not verified. Run Test to check it.' });
          else setOutcome({ ok: true, text: 'Nothing to change. Already set up.' });
        },
        onError: (err) => {
          setPreview(null);
          setOutcome({ ok: false, text: mutationMessage(err) });
        },
      },
    );
  }

  function confirmRemove() {
    remove.mutate(
      { id: agent.id, body: { ...scopeBody, dry_run: false } },
      {
        onSuccess: (data) => {
          setRemoveOpen(false);
          if (data.action === 'none') setOutcome({ ok: true, text: 'No MARM entry to remove.' });
          else setOutcome({ ok: true, text: data.backup_path ? 'Removed. Backup saved.' : 'Removed.' });
        },
        onError: (err) => {
          setRemoveOpen(false);
          setOutcome({ ok: false, text: mutationMessage(err) });
        },
      },
    );
  }

  function runTest() {
    setOutcome(null);
    setBusy('test');
    test.mutate(
      { id: agent.id, body: scopeBody },
      {
        onSuccess: (data) => { setBusy(null); setOutcome(testOutcome(data)); },
        onError: (err) => { setBusy(null); setOutcome({ ok: false, text: mutationMessage(err) }); },
      },
    );
  }

  function runInstallSkill() {
    setOutcome(null);
    setBusy('skill');
    installSkill.mutate(agent.id, {
      onSuccess: (data) => {
        setBusy(null);
        if (data.state === 'error') setOutcome({ ok: false, text: data.detail || 'The skill could not be installed.' });
        else setOutcome({ ok: true, text: `MARM skill ${data.state} for ${agent.label}.` });
      },
      onError: (err) => { setBusy(null); setOutcome({ ok: false, text: mutationMessage(err) }); },
    });
  }

  const unavailableReasons = transports.filter((t) => agent.unavailable[t]);
  const previewLoading = configure.isPending && configure.variables?.body.dry_run === true;
  const confirmLoading = configure.isPending && configure.variables?.body.dry_run === false;

  return (
    <Card className="flex flex-col">
      <CardContent className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-border bg-background/60 text-[11px] font-bold text-primary-highlight">{initials(agent.label)}</span>
            <div>
              <p className="font-medium leading-tight">{agent.label}</p>
              <p className="text-xs text-muted-foreground">{agent.detected ? 'Detected' : 'Not found on this machine'}</p>
            </div>
          </div>
          <Pill tone={pill.tone}>{pill.label}</Pill>
        </div>

        <dl className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-2 text-xs">
          <dt className="pt-1 text-muted-foreground">Transport</dt>
          <dd>
            <div role="group" aria-label="Transport" className="inline-flex overflow-hidden rounded-md border border-input">
              {transports.map((t) => (
                <button
                  key={t}
                  type="button"
                  aria-pressed={t === transport}
                  disabled={!!agent.unavailable[t]}
                  title={agent.unavailable[t]}
                  onClick={() => setPicked(t)}
                  className={cn('px-2.5 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-40', t === transport ? 'bg-primary/15 text-primary-highlight' : 'text-muted-foreground hover:text-foreground')}
                >
                  {TRANSPORT_LABEL[t]}
                </button>
              ))}
            </div>
            {unavailableReasons.map((t) => <p key={t} className="mt-1 text-[11px] text-muted-foreground">{TRANSPORT_LABEL[t]}: {agent.unavailable[t]}</p>)}
          </dd>

          <dt className="pt-2 text-muted-foreground">Scope</dt>
          <dd className="space-y-2">
            <NativeSelect aria-label="Scope" value={scopeChoice} onChange={(e) => changeScope(e.target.value)} disabled={!supportsProject}>
              <option value="user">Every project</option>
              {supportsProject && projects.data?.map((p) => <option key={p.root_path} value={p.root_path}>One project: {p.display_name || p.name}</option>)}
              {supportsProject && <option value={OTHER_FOLDER}>Another folder...</option>}
            </NativeSelect>
            {scopeChoice === OTHER_FOLDER && (
              <div className="flex gap-2">
                <Input aria-label="Folder path" placeholder="Path to a project folder" value={folderDraft} onChange={(e) => setFolderDraft(e.target.value)} />
                <Button size="sm" variant="outline" disabled={!folderDraft.trim()} onClick={() => { setFolder(folderDraft.trim()); setOutcome(null); }}>Apply</Button>
              </div>
            )}
          </dd>

          <dt className="text-muted-foreground">File</dt>
          <dd className="relative min-w-0">
            {scopeError ? <p className="text-destructive">{scopeError}</p>
              : awaitingFolder ? <p className="text-muted-foreground">Choose a folder to see its file.</p>
              : scopeState?.config_path ? (
                <>
                  <p className="break-all pr-8 font-mono text-muted-foreground">{scopeState.config_path}</p>
                  <CopyButton value={scopeState.config_path} label="Copy config path" className="absolute right-0 top-0" />
                </>
              ) : <p className="text-muted-foreground">{scopeQuery.isLoading && scope === 'project' ? 'Reading…' : 'No file yet.'}</p>}
          </dd>

          <dt className="text-muted-foreground">Skill</dt>
          <dd>{!agent.skill.supported ? <Pill>not supported</Pill> : agent.skill.installed ? <Pill tone="good">installed</Pill> : <Pill>not installed</Pill>}</dd>
        </dl>

        {agent.notes.length > 0 && (
          <div className="space-y-1">
            {agent.notes.map((note) => <p key={note} className="text-xs text-muted-foreground">{note}</p>)}
          </div>
        )}

        <div className="mt-auto space-y-3 pt-2">
          {outcome && (
            outcome.ok
              ? <p className="flex items-center gap-2 text-xs text-emerald-300"><CheckCircle2 className="h-3.5 w-3.5 shrink-0" />{outcome.text}</p>
              : <p className="flex items-center gap-2 text-xs text-amber-300"><XCircle className="h-3.5 w-3.5 shrink-0" />{outcome.text}</p>
          )}
          <div className="flex flex-wrap gap-2">
            {configured ? (
              <>
                <Button size="sm" isLoading={busy === 'test'} disabled={!ready} onClick={runTest}>Test</Button>
                <Button size="sm" variant="outline" isLoading={previewLoading} disabled={!ready || transportBlocked} onClick={openPreview}>Update</Button>
                <Button size="sm" variant="outline" disabled={!ready} onClick={() => setRemoveOpen(true)}>Remove</Button>
              </>
            ) : (
              <>
                <Button size="sm" isLoading={previewLoading} disabled={!ready || transportBlocked} onClick={openPreview}>Connect</Button>
                <Button size="sm" variant="outline" isLoading={busy === 'test'} disabled={!ready} onClick={runTest}>Test</Button>
              </>
            )}
            {agent.skill.supported && !agent.skill.installed && (
              <Button size="sm" variant="ghost" isLoading={busy === 'skill'} disabled={!configureAllowed} onClick={runInstallSkill}>Install skill</Button>
            )}
          </div>
        </div>
      </CardContent>

      <Dialog open={!!preview} onOpenChange={(open) => { if (!open) setPreview(null); }}>
        <DialogContent>
          {preview && (
            <>
              <DialogHeader>
                <DialogTitle>{configured ? 'Update' : 'Connect'} {agent.label}</DialogTitle>
                <DialogDescription>{ACTION_LABEL[preview.action] || preview.action}</DialogDescription>
              </DialogHeader>
              {preview.config_path && <p className="break-all font-mono text-xs text-muted-foreground">{preview.config_path}</p>}
              <pre className="max-h-64 overflow-auto rounded-lg border border-border/60 bg-background/60 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">{JSON.stringify(preview.entry, null, 2)}</pre>
              {preview.backup_path && <p className="text-xs text-muted-foreground">A backup of the current file will be saved to <span className="break-all font-mono">{preview.backup_path}</span>.</p>}
              {preview.notes?.map((note) => <p key={note} className="text-xs text-muted-foreground">{note}</p>)}
              <DialogFooter>
                <Button variant="outline" onClick={() => setPreview(null)}>Cancel</Button>
                <Button isLoading={confirmLoading} onClick={confirmWrite}>Confirm</Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={removeOpen} onOpenChange={setRemoveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove MARM from {agent.label}?</DialogTitle>
            <DialogDescription>Only MARM's entry is removed. Other servers in the file stay. A backup is kept.</DialogDescription>
          </DialogHeader>
          {scopeState?.config_path && <p className="break-all font-mono text-xs text-muted-foreground">{scopeState.config_path}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemoveOpen(false)}>Cancel</Button>
            <Button variant="destructive" isLoading={remove.isPending} onClick={confirmRemove}>Remove</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
