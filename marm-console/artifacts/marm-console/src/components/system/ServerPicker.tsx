import { useState } from 'react';
import { Badge, Button, Input, cn } from '@/components/ui/core';
import { CircleAlert, Plug, RefreshCw, Search } from 'lucide-react';
import { useLlmServers, useUpdateLlmSettings } from '@/hooks/use-marm-queries';
import type { LocalLlmStatus } from '@/lib/marm-types';

/** Which local server answers, chosen from the ones actually running.
 *
 *  WHY THIS SCANS RATHER THAN ASKING THE READER FOR A URL
 *      The endpoint was a single environment variable, so a reader whose
 *      llama.cpp had stopped and whose LM Studio was running had no way to
 *      find that out from this page — the pane simply said nothing answered.
 *      Every one of these servers speaks the same `/v1/chat/completions`, so
 *      the only real question is which port, and that is answerable.
 *
 *  WHY IT IS LOOPBACK ONLY, AND WHY THAT IS NOT A DEFAULT
 *      The same rule the client enforces: this deployment exists to keep the
 *      data on one machine. Nothing off 127.0.0.1 is scanned, and a typed URL
 *      that is not loopback is refused with a reason rather than saved and
 *      quietly ignored.
 */
export function ServerPicker({ llm }: { llm: LocalLlmStatus }) {
  const servers = useLlmServers();
  const update = useUpdateLlmSettings();
  const [custom, setCustom] = useState('');
  const data = servers.data;
  const found = data?.servers ?? [];
  const configuredDead = data ? !data.configured_reachable : false;

  const choose = (url: string) => update.mutate({ endpoint: url });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          Server
        </span>
        <Button
          size="sm"
          variant="outline"
          className="h-7"
          isLoading={servers.isFetching}
          onClick={() => servers.refetch()}
        >
          <Search className="mr-1.5 h-3 w-3" />
          Scan for servers
        </Button>
        {data && (
          <span className="text-[11px] tabular-nums text-muted-foreground">
            {found.length === 0
              ? `nothing found on ${data.scanned_ports.length} known ports`
              : `${found.length} found in ${(data.scan_seconds * 1000).toFixed(0)} ms`}
          </span>
        )}
      </div>

      {/* The single most useful thing this pane can say. */}
      {configuredDead && llm.configured && (
        <div className="flex items-start gap-2.5 rounded-lg border border-amber-500/25 bg-amber-500/[0.05] p-3">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
          <p className="text-xs text-amber-100">
            Nothing is answering at{' '}
            <code className="font-mono text-[11px]">{data?.configured}</code>
            {found.length > 0
              ? ' — but another local server is running. Pick it below.'
              : '. Start a local model server, or enter its address below.'}
          </p>
        </div>
      )}

      {found.length > 0 && (
        <div className="space-y-1">
          {found.map((server) => {
            const active = server.url === llm.endpoint;
            return (
              <button
                key={server.url}
                type="button"
                disabled={update.isPending || active}
                onClick={() => choose(server.url)}
                className={cn(
                  'flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-left transition-colors',
                  active
                    ? 'border-primary/40 bg-primary/[0.06]'
                    : 'border-border/60 bg-card/35 hover:border-primary/40',
                  update.isPending && 'opacity-60',
                )}
                title={active ? 'Currently in use' : `Use ${server.runtime} on port ${server.port}`}
              >
                <Plug
                  className={cn('h-3.5 w-3.5 shrink-0', active ? 'text-primary' : 'text-cyan-300')}
                />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-xs font-semibold">{server.runtime}</span>
                    <code className="font-mono text-[10px] text-muted-foreground">
                      127.0.0.1:{server.port}
                    </code>
                    {/* Anyone may run llama.cpp on 1234; say what answered, not
                        what the port conventionally belongs to. */}
                    {server.expected !== server.runtime && server.expected !== 'configured' && (
                      <span className="text-[10px] text-muted-foreground">
                        (port usually {server.expected})
                      </span>
                    )}
                  </span>
                  <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
                    {server.model_count === 1
                      ? server.models[0]
                      : `${server.model_count} models · ${server.models.slice(0, 2).join(', ')}${
                          server.model_count > 2 ? '…' : ''
                        }`}
                  </span>
                </span>
                {active && (
                  <Badge
                    variant="outline"
                    className="shrink-0 border-primary/40 text-[9px] text-primary-highlight"
                  >
                    in use
                  </Badge>
                )}
                {!server.can_switch && (
                  <Badge variant="outline" className="shrink-0 text-[9px]">
                    one model
                  </Badge>
                )}
              </button>
            );
          })}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={custom}
          onChange={(event) => setCustom(event.target.value)}
          placeholder="http://127.0.0.1:1234"
          aria-label="Model server address"
          className="h-8 min-w-[15rem] flex-1 font-mono text-xs"
        />
        <Button
          size="sm"
          variant="outline"
          disabled={!custom.trim()}
          isLoading={update.isPending}
          onClick={() => choose(custom.trim())}
        >
          Use this address
        </Button>
        {llm.endpoint && llm.endpoint !== data?.configured && (
          <Button size="sm" variant="ghost" onClick={() => update.mutate({ endpoint: '' })}>
            Reset
          </Button>
        )}
      </div>

      {update.data?.llm?.rejected && (
        <p className="text-[11px] text-amber-200">{update.data.llm.rejected}</p>
      )}
      <p className="text-[11px] text-muted-foreground">
        Only addresses on this machine are accepted, and only loopback ports are scanned —
        nothing here reaches the network.
      </p>
    </div>
  );
}
