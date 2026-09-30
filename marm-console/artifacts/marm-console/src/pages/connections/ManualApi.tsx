import { useMemo, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { useConnectionsOverview, useManualEndpoints } from '@/hooks/use-marm-queries';
import { CopyButton } from '@/components/code-context/shared';
import { cn } from '@/components/ui/core';
import type { ManualRoute } from '@/lib/marm-types';
import { ErrorState, Pill, mutationMessage } from './controls';
import { CodeBlock, SearchBox } from './manualShared';

type Language = 'curl' | 'python' | 'javascript';

const LANGUAGES: Array<{ id: Language; label: string }> = [
  { id: 'curl', label: 'curl' },
  { id: 'python', label: 'Python' },
  { id: 'javascript', label: 'JavaScript' },
];

const BODY_METHODS = ['POST', 'PUT', 'PATCH'];

export function baseUrlOf(mcpUrl: string) {
  return mcpUrl.replace(/\/mcp\/?$/, '').replace(/\/$/, '');
}

export function buildRequest(language: Language, route: Pick<ManualRoute, 'method' | 'path'>, baseUrl: string, withKey: boolean) {
  const method = route.method.toUpperCase();
  const url = `${baseUrl}${route.path}`;
  const hasBody = BODY_METHODS.includes(method);

  if (language === 'curl') {
    const lines = [`curl${method === 'GET' ? '' : ` -X ${method}`} "${url}"`];
    if (withKey) lines.push('  -H "Authorization: Bearer $MARM_API_KEY"');
    if (hasBody) lines.push('  -H "Content-Type: application/json"', "  -d '{}'");
    return lines.join(' \\\n');
  }

  if (language === 'python') {
    const headers = [
      ...(withKey ? ['        "Authorization": f"Bearer {os.environ[\'MARM_API_KEY\']}",'] : []),
      ...(hasBody ? ['        "Content-Type": "application/json",'] : []),
    ];
    return [
      ...(withKey ? ['import os', ''] : []),
      'import requests',
      '',
      'response = requests.request(',
      `    "${method}",`,
      `    "${url}",`,
      ...(headers.length ? ['    headers={', ...headers, '    },'] : []),
      ...(hasBody ? ['    json={},'] : []),
      ')',
      'print(response.json())',
    ].join('\n');
  }

  const headers = [
    ...(withKey ? ['    Authorization: `Bearer ${process.env.MARM_API_KEY}`,'] : []),
    ...(hasBody ? ['    "Content-Type": "application/json",'] : []),
  ];
  return [
    `const response = await fetch("${url}", {`,
    `  method: "${method}",`,
    ...(headers.length ? ['  headers: {', ...headers, '  },'] : []),
    ...(hasBody ? ['  body: JSON.stringify({}),'] : []),
    '});',
    'console.log(await response.json());',
  ].join('\n');
}

const METHOD_TONE: Record<string, 'good' | 'info' | 'warn' | 'bad' | 'neutral'> = { GET: 'good', POST: 'info', PUT: 'warn', PATCH: 'warn', DELETE: 'bad' };

function RouteRow({ route, selected, onSelect }: { route: ManualRoute; selected: boolean; onSelect?: () => void }) {
  return (
    <tr
      onClick={onSelect}
      className={cn('border-t border-border/50', onSelect && 'cursor-pointer hover:bg-accent/40', selected && 'bg-primary/10')}
    >
      <td className="w-20 px-3 py-1.5 align-top"><Pill tone={METHOD_TONE[route.method.toUpperCase()] ?? 'neutral'}>{route.method.toUpperCase()}</Pill></td>
      <td className="px-3 py-1.5 align-top font-mono text-xs">
        {onSelect ? <button type="button" aria-pressed={selected} onClick={onSelect} className="text-left">{route.path}</button> : route.path}
      </td>
      <td className="px-3 py-1.5 align-top text-xs text-muted-foreground">{route.summary}</td>
    </tr>
  );
}

export function ApiSection() {
  const endpoints = useManualEndpoints();
  const overview = useConnectionsOverview();
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<{ method: string; path: string } | null>(null);
  const [language, setLanguage] = useState<Language>('curl');
  const [consoleOpen, setConsoleOpen] = useState(false);

  const data = endpoints.data;
  const needle = query.trim().toLowerCase();
  const groups = useMemo(() => {
    if (!data) return [];
    return data.groups
      .map((group) => ({ ...group, routes: group.routes.filter((route) => !needle || `${route.method} ${route.path} ${route.summary}`.toLowerCase().includes(needle)) }))
      .filter((group) => group.routes.length > 0);
  }, [data, needle]);

  if (endpoints.isLoading) return <p className="text-sm text-muted-foreground">Loading endpoints...</p>;
  if (endpoints.isError || !data) return <ErrorState message={mutationMessage(endpoints.error)} />;

  const withKey = overview.data?.auth.mode === 'key';
  const isSelected = (route: { method: string; path: string }) => selected?.method === route.method && selected?.path === route.path;

  return (
    <div className="space-y-4">
      <div>
        <div className="mb-1.5 text-xs font-medium text-muted-foreground">MCP URL</div>
        <div className="flex items-center gap-2 rounded-lg border border-border/70 bg-background/60 px-3 py-1.5">
          <code className="flex-1 truncate font-mono text-xs">{data.mcp_url}</code>
          <CopyButton value={data.mcp_url} label="Copy MCP URL" className="h-7 w-7" />
        </div>
      </div>

      {!data.runtime_available && (
        <div className="rounded-lg border border-amber-400/25 bg-amber-400/[0.06] p-3 text-xs text-amber-300">
          {data.reason ?? 'The MARM runtime is not running, so its routes cannot be listed.'}
        </div>
      )}

      {data.runtime_available && (
        <>
          <SearchBox value={query} onChange={setQuery} label="Search endpoints" />
          <div className="overflow-x-auto rounded-lg border border-border/60">
            <table className="w-full text-sm">
              <tbody>
                {groups.length === 0 && <tr><td className="px-3 py-3 text-xs text-muted-foreground">No endpoints match.</td></tr>}
                {groups.map((group) => (
                  <GroupRows key={group.name} name={group.name} routes={group.routes} isSelected={isSelected} onSelect={setSelected} />
                ))}
              </tbody>
            </table>
          </div>

          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div role="tablist" aria-label="Snippet language" className="flex gap-1">
                {LANGUAGES.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    role="tab"
                    aria-selected={language === item.id}
                    onClick={() => setLanguage(item.id)}
                    className={cn('rounded-md border px-3 py-1 text-xs', language === item.id ? 'border-primary/45 bg-primary/15 text-primary' : 'border-border/70 text-muted-foreground hover:text-foreground')}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              {withKey && <span className="text-xs text-muted-foreground">Set MARM_API_KEY in your environment first.</span>}
            </div>
            {selected ? (
              <CodeBlock text={buildRequest(language, selected, baseUrlOf(data.mcp_url), withKey)} label="request" />
            ) : (
              <p className="rounded-lg border border-dashed border-border/70 p-4 text-xs text-muted-foreground">Select an endpoint above to see a ready-to-run request.</p>
            )}
          </div>
        </>
      )}

      {data.console.length > 0 && (
        <div>
          <button type="button" aria-expanded={consoleOpen} onClick={() => setConsoleOpen((open) => !open)} className="flex items-center gap-1.5 text-sm font-semibold">
            <ChevronDown className={cn('h-4 w-4 transition-transform', !consoleOpen && '-rotate-90')} />
            Console API ({data.console.length})
          </button>
          {consoleOpen && (
            <div className="mt-2 overflow-x-auto rounded-lg border border-border/60">
              <table className="w-full text-sm">
                <tbody>{data.console.map((route) => <RouteRow key={`${route.method} ${route.path}`} route={route} selected={false} />)}</tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function GroupRows({ name, routes, isSelected, onSelect }: { name: string; routes: ManualRoute[]; isSelected: (route: ManualRoute) => boolean; onSelect: (route: ManualRoute) => void }) {
  return (
    <>
      <tr className="bg-muted/30"><th colSpan={3} className="px-3 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{name}</th></tr>
      {routes.map((route) => <RouteRow key={`${route.method} ${route.path}`} route={route} selected={isSelected(route)} onSelect={() => onSelect(route)} />)}
    </>
  );
}
