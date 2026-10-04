import { useState } from 'react';
import { Badge, Button, Input, cn } from '@/components/ui/core';
import { Panel, SmallStat } from '@/components/ui/panels';
import { FolderOpen, FolderPlus, HardDrive, RefreshCw, Trash2 } from 'lucide-react';
import {
  useBrowseLlmModels,
  useLlmModels,
  useUpdateLlmRoots,
  useUpdateLlmSettings,
} from '@/hooks/use-marm-queries';
import { formatBytes } from './gpu';
import type { LocalLlmStatus } from '@/lib/marm-types';

function BrowseDialog({ onPick, onClose }: { onPick: (path: string) => void; onClose: () => void }) {
  const [path, setPath] = useState<string | null>(null);
  const browse = useBrowseLlmModels(path);
  const listing = browse.data;

  return (
    <div className="mt-3 rounded-lg border border-border/70 bg-background/30 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          {listing?.path ?? 'Model directories'}
        </span>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>

      {listing?.error && <p className="mb-2 text-[11px] text-amber-200">{listing.error}</p>}

      <div className="max-h-64 space-y-1 overflow-auto [scrollbar-gutter:stable]">
        {/* At the top level the reader picks a root; inside one they walk it.
            `parent` is null at a root boundary, so Browse cannot be walked
            upward out of the directories it is scoped to. */}
        {!listing?.path &&
          (listing?.roots ?? []).map((root) => (
            <button
              key={root}
              type="button"
              onClick={() => setPath(root)}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left font-mono text-[11px] transition-colors hover:bg-card/60"
            >
              <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-400" />
              <span className="truncate">{root}</span>
            </button>
          ))}
        {listing?.parent && (
          <button
            type="button"
            onClick={() => setPath(listing.parent)}
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left font-mono text-[11px] text-muted-foreground transition-colors hover:bg-card/60"
          >
            <FolderOpen className="h-3.5 w-3.5 shrink-0" />
            ..
          </button>
        )}
        {(listing?.entries ?? []).map((entry) => (
          <button
            key={entry.path}
            type="button"
            onClick={() => (entry.kind === 'directory' ? setPath(entry.path) : onPick(entry.path))}
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left font-mono text-[11px] transition-colors hover:bg-card/60"
          >
            {entry.kind === 'directory' ? (
              <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-400" />
            ) : (
              <HardDrive className="h-3.5 w-3.5 shrink-0 text-cyan-300" />
            )}
            <span className="flex-1 truncate">{entry.name}</span>
            {entry.kind === 'model' && (
              <span className="shrink-0 tabular-nums text-muted-foreground">
                {formatBytes(entry.size_bytes)}
              </span>
            )}
          </button>
        ))}
        {listing && !listing.error && listing.entries.length === 0 && listing.path && (
          <p className="px-2 py-3 text-[11px] text-muted-foreground">
            Nothing here that MARM recognises as a model.
          </p>
        )}
      </div>
    </div>
  );
}

/** Every model this machine has, where it came from, and how big it is. */
export function InstalledModels({ llm }: { llm: LocalLlmStatus }) {
  const models = useLlmModels();
  const roots = useUpdateLlmRoots();
  const update = useUpdateLlmSettings();
  const [browsing, setBrowsing] = useState(false);
  const [newRoot, setNewRoot] = useState('');
  const data = models.data;

  return (
    <Panel
      icon={<HardDrive className="h-5 w-5 text-cyan-300" />}
      title="Models on this machine"
      description={
        <>
          Found by scanning where LM Studio, Ollama, HuggingFace, llama.cpp, GPT4All and Jan keep
          weights, plus any directory you add. Nothing is opened — only names, sizes and paths are
          read.
        </>
      }
      action={
        <Button
          size="sm"
          variant="outline"
          onClick={() => models.refetch()}
          isLoading={models.isFetching}
        >
          <RefreshCw className="mr-1.5 h-3 w-3" />
          Rescan
        </Button>
      }
    >
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <SmallStat label="Found" value={data ? data.total.toLocaleString() : '—'} />
        <SmallStat
          label="Roots searched"
          value={data ? String(data.roots.filter((r) => r.exists).length) : '—'}
        />
        <SmallStat label="Scan" value={data ? `${(data.scan_seconds * 1000).toFixed(0)} ms` : '—'} />
      </div>

      {data?.note && <p className="mt-3 text-[11px] text-amber-200">{data.note}</p>}

      {data && data.models.length > 0 && (
        <div className="mt-4 max-h-72 space-y-1 overflow-auto [scrollbar-gutter:stable]">
          {data.models.map((model) => {
            // Matched on the filename, not the alias: a runtime's alias
            // ("qwen3.6-27b-mtp") is chosen at launch and routinely bears no
            // resemblance to the file it was loaded from.
            const inUse =
              llm.model_path && model.path.endsWith(llm.model_path.split('/').pop() ?? '\0');
            // Selectable only when the runtime can switch AND already knows
            // this model. A file the runtime has never seen cannot be loaded
            // by naming it, however switchable the runtime is in general.
            const selectable = data.can_switch && !!model.served_id;
            const selected = !!model.served_id && model.served_id === llm.preferred_model;
            // Setting the flag replaces whatever was there, so picking a new
            // row clears the old selection by construction.
            const pick = () => model.served_id && update.mutate({ model: model.served_id });

            const body = (
              <>
                <span className="min-w-0 flex-1 truncate font-mono text-[11px]" title={model.path}>
                  {model.name}
                </span>
                {inUse && (
                  <Badge variant="outline" className="shrink-0 border-primary/40 text-[9px] text-primary-highlight">
                    serving
                  </Badge>
                )}
                {selected && !inUse && (
                  <Badge variant="outline" className="shrink-0 border-primary/40 text-[9px] text-primary-highlight">
                    selected
                  </Badge>
                )}
                <Badge variant="outline" className="shrink-0 text-[9px]">
                  {model.source}
                </Badge>
                {model.shards && model.shards > 1 && (
                  <span className="shrink-0 text-[10px] text-muted-foreground">{model.shards} shards</span>
                )}
                <span className="shrink-0 tabular-nums text-[11px] text-muted-foreground">
                  {formatBytes(model.size_bytes)}
                </span>
              </>
            );

            const shell = cn(
              'flex w-full items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left',
              inUse || selected ? 'border-primary/40 bg-primary/[0.06]' : 'border-border/60 bg-card/35',
            );

            if (!selectable) {
              return (
                <div
                  key={model.path}
                  className={shell}
                  // The row says why it is inert rather than just being dead:
                  // "nothing happens when I click it" is the complaint this
                  // whole panel exists to prevent.
                  title={
                    data.can_switch
                      ? `${model.name} is on disk but not loaded in ${data.runtime ?? 'this runtime'}, so it cannot be selected by name.`
                      : data.switch_blocked_reason ?? undefined
                  }
                >
                  {body}
                </div>
              );
            }
            return (
              <button
                key={model.path}
                type="button"
                onClick={pick}
                disabled={update.isPending}
                className={cn(shell, 'transition-colors hover:border-primary/50 disabled:opacity-60')}
                title={selected ? `${model.name} is already selected` : `Use ${model.name} for answers`}
              >
                {body}
              </button>
            );
          })}
        </div>
      )}

      {data && data.models.length === 0 && (
        <p className="mt-4 text-[11px] text-muted-foreground">
          No models found. If you keep them somewhere unusual, add that directory below.
        </p>
      )}

      <div className="mt-4 border-t border-border/60 pt-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => setBrowsing((open) => !open)}>
            <FolderOpen className="mr-1.5 h-3 w-3" />
            Browse
          </Button>
          <Input
            value={newRoot}
            onChange={(event) => setNewRoot(event.target.value)}
            placeholder="/path/to/your/models"
            aria-label="Add a model directory"
            className="h-8 min-w-[16rem] flex-1 text-xs"
          />
          <Button
            size="sm"
            variant="outline"
            disabled={!newRoot.trim()}
            isLoading={roots.isPending}
            onClick={() => roots.mutate({ path: newRoot.trim() }, { onSuccess: () => setNewRoot('') })}
          >
            <FolderPlus className="mr-1.5 h-3 w-3" />
            Add root
          </Button>
        </div>
        {roots.isError && (
          <p className="mt-2 text-[11px] text-amber-200">
            {roots.error instanceof Error ? roots.error.message : 'That directory could not be added.'}
          </p>
        )}

        {browsing && (
          <BrowseDialog
            onClose={() => setBrowsing(false)}
            onPick={(path) => {
              setNewRoot(path);
              setBrowsing(false);
            }}
          />
        )}

        {data && data.roots.some((r) => r.configured) && (
          <div className="mt-3 space-y-1">
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              Directories you added
            </div>
            {data.roots
              .filter((r) => r.configured)
              .map((root) => (
                <div key={root.path} className="flex items-center gap-2">
                  <span
                    className={cn(
                      'min-w-0 flex-1 truncate font-mono text-[11px]',
                      !root.exists && 'text-amber-200',
                    )}
                    title={root.exists ? root.path : `${root.path} — not found`}
                  >
                    {root.path}
                    {!root.exists && ' — not found'}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 w-6 shrink-0 p-0"
                    title="Stop searching this directory"
                    onClick={() => roots.mutate({ path: root.path, remove: true })}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              ))}
          </div>
        )}
      </div>
    </Panel>
  );
}
