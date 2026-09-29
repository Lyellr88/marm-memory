import { AlertTriangle } from 'lucide-react';
import { useAgents } from '@/hooks/use-marm-queries';
import { Button, Card, CardContent } from '@/components/ui/core';
import { SectionHeading } from '@/components/ui/panels';
import { LoadingState } from '@/components/code-context/shared';
import type { AgentTarget, AgentTransport } from '@/lib/marm-types';
import { AgentCard } from './AgentCard';
import { ErrorState } from './controls';

const GROUPS = [
  { id: 'cli', label: 'CLI tools' },
  { id: 'app', label: 'Apps' },
  { id: 'ide', label: 'IDEs' },
  { id: 'other', label: 'Other' },
] as const;

const GROUP_BY_ID: Record<string, (typeof GROUPS)[number]['id']> = {
  claude: 'cli',
  codex: 'cli',
  grok: 'cli',
  antigravity: 'cli',
  qwen: 'cli',
  'claude-desktop': 'app',
  cursor: 'ide',
  vscode: 'ide',
  windsurf: 'ide',
  kiro: 'ide',
};

const groupOf = (id: string) => GROUP_BY_ID[id] ?? 'other';

export function AgentsGrid({ onRequest, allowedTransports, target, title = 'Agents' }: { onRequest: () => void; allowedTransports: AgentTransport[]; target?: AgentTarget; title?: string }) {
  const agents = useAgents(target);
  const data = agents.data;
  const errorMessage = agents.error instanceof Error ? agents.error.message : 'Agents are unavailable.';
  const visible = data?.clients.filter((client) => client.transports.some((t) => allowedTransports.includes(t))) ?? [];

  return (
    <section className="space-y-5">
      <SectionHeading title={title} description="MARM adds its entry to each tool's config and leaves everything else in the file alone." />
      {agents.isLoading && <LoadingState label="Reading agent state…" />}
      {agents.isError && <ErrorState message={errorMessage} />}

      {data && <>
        {!data.configure_allowed && (
          <div className="flex items-start gap-3 rounded-xl border border-amber-400/30 bg-amber-400/[0.05] p-4 text-sm text-amber-200">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <p>{data.configure_blocked_reason || 'Configuring agents is turned off.'}</p>
          </div>
        )}

        {GROUPS.map((group) => {
          const agents = visible.filter((agent) => groupOf(agent.id) === group.id);
          const last = group.id === 'other';
          if (!agents.length && !last) return null;
          return (
            <div key={group.id} className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{group.label}</h3>
              <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(300px,1fr))]">
                {agents.map((agent) => (
                  <AgentCard key={agent.id} agent={agent} allowedTransports={allowedTransports} configureAllowed={data.configure_allowed} target={target} />
                ))}
                {last && (
                  <Card className="flex flex-col items-center justify-center border-dashed bg-transparent text-center">
                    <CardContent className="flex flex-col items-center gap-2 p-5">
                      <p className="font-medium">Don't see your tool?</p>
                      <p className="text-xs text-muted-foreground">Tell us which one and we'll add it.</p>
                      <Button size="sm" variant="outline" onClick={onRequest}>Request a connection</Button>
                    </CardContent>
                  </Card>
                )}
              </div>
            </div>
          );
        })}
      </>}
    </section>
  );
}
