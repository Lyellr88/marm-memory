import { useMemo, useState } from 'react';
import { useSearchParams } from 'wouter';
import { useAgents, useConnectionsOverview, useManualAgentCommands, useManualEnv, useManualSnippet } from '@/hooks/use-marm-queries';
import { Button, cn } from '@/components/ui/core';
import type { AgentScopeName, AgentTransport, ManualOs, ManualSnippetParams, ManualTarget } from '@/lib/marm-types';
import { ApiSection } from './ManualApi';
import { CliSection } from './ManualCli';
import { ErrorState, Pill, mutationMessage } from './controls';
import { CodeBlock, SearchBox, SelectField, SendToTerminal } from './manualShared';

type SectionId = 'config' | 'commands' | 'cli' | 'api' | 'env';

const SECTIONS: Array<{ id: SectionId; label: string; hint: string }> = [
  { id: 'config', label: 'Config files', hint: 'Text to paste into an agent config file' },
  { id: 'commands', label: 'Agent commands', hint: "Each agent's own command to add MARM" },
  { id: 'cli', label: 'MARM CLI', hint: 'Build a marm-memory command' },
  { id: 'api', label: 'API endpoints', hint: 'Routes with ready-to-run requests' },
  { id: 'env', label: 'Environment', hint: 'Variables MARM reads' },
];

const OS_OPTIONS: Array<{ value: ManualOs; label: string }> = [
  { value: 'windows', label: 'Windows' },
  { value: 'macos', label: 'macOS' },
  { value: 'linux', label: 'Linux' },
];

const TRANSPORT_LABEL: Record<AgentTransport, string> = { http: 'HTTP', stdio: 'STDIO', 'docker-stdio': 'Docker STDIO' };
const SCOPE_LABEL: Record<AgentScopeName, string> = { user: 'Every project', project: 'One project' };
const TARGET_OPTIONS: Array<{ value: ManualTarget; label: string }> = [
  { value: 'local', label: 'This machine' },
  { value: 'docker', label: 'Docker' },
];


export function detectOs(label: string | undefined): ManualOs {
  const text = (label ?? '').toLowerCase();
  if (text.includes('mac') || text.includes('darwin')) return 'macos';
  if (text.includes('win')) return 'windows';
  return text ? 'linux' : 'windows';
}

function pick<T extends string>(value: T | '', allowed: T[]): T | undefined {
  return value && allowed.includes(value) ? value : allowed[0];
}

export function ManualTab() {
  const [section, setSection] = useState<SectionId>('config');

  return (
    <div className="flex flex-col gap-5 md:flex-row">
      <nav aria-label="Manual sections" className="flex shrink-0 gap-1 overflow-x-auto md:w-52 md:flex-col md:overflow-visible">
        {SECTIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-current={section === item.id ? 'page' : undefined}
            onClick={() => setSection(item.id)}
            className={cn(
              'whitespace-nowrap rounded-lg border px-3 py-2 text-left text-sm transition-colors md:whitespace-normal',
              section === item.id ? 'border-primary/40 bg-primary/10 text-primary' : 'border-transparent text-muted-foreground hover:bg-accent/40 hover:text-foreground',
            )}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="min-w-0 flex-1 pb-6">
        <h2 className="text-base font-semibold">{SECTIONS.find((item) => item.id === section)?.label}</h2>
        <p className="mb-4 mt-1 text-sm text-muted-foreground">{SECTIONS.find((item) => item.id === section)?.hint}. Nothing here changes your machine.</p>
        {section === 'config' && <ConfigSection />}
        {section === 'commands' && <CommandsSection />}
        {section === 'cli' && <CliSection />}
        {section === 'api' && <ApiSection />}
        {section === 'env' && <EnvSection />}
      </div>
    </div>
  );
}

function ConfigSection() {
  const agents = useAgents();
  const overview = useConnectionsOverview();
  const clients = useMemo(() => agents.data?.clients ?? [], [agents.data]);
  const [clientId, setClientId] = useState('');
  const [os, setOs] = useState<ManualOs | ''>('');
  const [transport, setTransport] = useState<AgentTransport | ''>('');
  const [scope, setScope] = useState<AgentScopeName | ''>('');
  const [target, setTarget] = useState<ManualTarget>('local');

  const client = clients.find((item) => item.id === clientId) ?? clients[0];
  const effectiveTransport = client ? pick(transport, client.transports) : undefined;
  const effectiveScope = client ? pick(scope, client.scopes) : undefined;
  const params: ManualSnippetParams | null = client && effectiveTransport && effectiveScope
    ? { client: client.id, os: os || detectOs(overview.data?.os), transport: effectiveTransport, scope: effectiveScope, target }
    : null;
  const snippet = useManualSnippet(params);

  if (agents.isLoading) return <p className="text-sm text-muted-foreground">Loading agents...</p>;
  if (agents.isError) return <ErrorState message={mutationMessage(agents.error)} />;

  const notes = snippet.data?.notes;
  const noteList = Array.isArray(notes) ? notes : notes ? [notes] : [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <SelectField label="Agent" value={client?.id ?? ''} onChange={setClientId} options={clients.map((item) => ({ value: item.id, label: item.label }))} />
        <SelectField label="Your system" value={params?.os ?? ''} onChange={(next) => setOs(next as ManualOs)} options={OS_OPTIONS} />
        <SelectField label="Transport" value={effectiveTransport ?? ''} onChange={(next) => setTransport(next as AgentTransport)} options={(client?.transports ?? []).map((item) => ({ value: item, label: TRANSPORT_LABEL[item] }))} />
        <SelectField label="Scope" value={effectiveScope ?? ''} onChange={(next) => setScope(next as AgentScopeName)} options={(client?.scopes ?? []).map((item) => ({ value: item, label: SCOPE_LABEL[item] }))} />
        <SelectField label="Target" value={target} onChange={(next) => setTarget(next as ManualTarget)} options={TARGET_OPTIONS} />
      </div>

      {snippet.isError && <ErrorState message={mutationMessage(snippet.error)} />}
      {snippet.data && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>Add this to</span>
            <code className="font-mono text-foreground">{snippet.data.path}</code>
            <Pill>{snippet.data.format.toUpperCase()}</Pill>
          </div>
          <CodeBlock text={snippet.data.text} label="config" />
          {noteList.map((note) => <p key={note} className="text-xs text-muted-foreground">{note}</p>)}
        </div>
      )}
    </div>
  );
}

function CommandsSection() {
  const [transport, setTransport] = useState<AgentTransport>('http');
  const [scope, setScope] = useState<AgentScopeName>('user');
  const [target, setTarget] = useState<ManualTarget>('local');
  const commands = useManualAgentCommands({ transport, scope, target });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <SelectField label="Transport" value={transport} onChange={(next) => setTransport(next as AgentTransport)} options={(Object.keys(TRANSPORT_LABEL) as AgentTransport[]).map((item) => ({ value: item, label: TRANSPORT_LABEL[item] }))} />
        <SelectField label="Scope" value={scope} onChange={(next) => setScope(next as AgentScopeName)} options={(Object.keys(SCOPE_LABEL) as AgentScopeName[]).map((item) => ({ value: item, label: SCOPE_LABEL[item] }))} />
        <SelectField label="Target" value={target} onChange={(next) => setTarget(next as ManualTarget)} options={TARGET_OPTIONS} />
      </div>

      {commands.isLoading && <p className="text-sm text-muted-foreground">Loading commands...</p>}
      {commands.isError && <ErrorState message={mutationMessage(commands.error)} />}
      <div className="grid gap-3 lg:grid-cols-2">
        {commands.data?.commands.map((item) => (
          <div key={item.client} className="space-y-2 rounded-xl border border-border/60 bg-background/25 p-4">
            <h3 className="text-sm font-semibold">{item.label}</h3>
            {item.command ? (
              <>
                <CodeBlock text={item.command} label={`${item.label} command`} />
                {item.note && <p className="text-xs text-muted-foreground">{item.note}</p>}
                <SendToTerminal command={item.command} />
              </>
            ) : (
              <p className="text-xs text-muted-foreground">{item.note}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function EnvSection() {
  const env = useManualEnv();
  const [, setParams] = useSearchParams();
  const [query, setQuery] = useState('');

  if (env.isLoading) return <p className="text-sm text-muted-foreground">Loading variables...</p>;
  if (env.isError || !env.data) return <ErrorState message={mutationMessage(env.error)} />;

  const needle = query.trim().toLowerCase();
  const items = env.data.items.filter((item) => !needle || `${item.name} ${item.group} ${item.description}`.toLowerCase().includes(needle));
  const openSetup = () => setParams(new URLSearchParams({ tab: 'setup' }), { replace: true });

  return (
    <div className="space-y-3">
      <SearchBox value={query} onChange={setQuery} label="Search variables" />
      <div className="overflow-x-auto rounded-lg border border-border/60">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-[11px] uppercase tracking-wide text-muted-foreground">
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Group</th>
              <th className="px-3 py-2">Default</th>
              <th className="px-3 py-2">Current</th>
              <th className="px-3 py-2">Source</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={5} className="px-3 py-3 text-xs text-muted-foreground">No variables match.</td></tr>}
            {items.map((item) => {
              const secret = item.name === 'MARM_API_KEY';
              return (
                <tr key={item.name} className="border-t border-border/50 align-top">
                  <td className="px-3 py-2">
                    <div className="font-mono text-xs">{item.name}</div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">{item.description}</div>
                    {item.setting_key && <Button type="button" variant="link" className="h-auto p-0 text-[11px]" onClick={openSetup}>Change in Setup</Button>}
                  </td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">{item.group}</td>
                  <td className="px-3 py-2 font-mono text-xs">{secret ? '' : (item.default ?? '')}</td>
                  <td className="px-3 py-2 font-mono text-xs">{secret ? (item.current ? 'set' : 'not set') : (item.current ?? '')}</td>
                  <td className="px-3 py-2"><Pill tone={item.source === 'default' ? 'neutral' : item.source === 'saved' ? 'info' : 'warn'}>{item.source}</Pill></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
