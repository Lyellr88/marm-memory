import { useEffect, useState } from 'react';
import { TriangleAlert } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, Input } from '@/components/ui/core';

interface CliCommandsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onInsertCommand: (command: string) => boolean;
}

interface CliCommand {
  base: string;
  flag?: string;
  description: string;
}

interface CliCommandGroup {
  label: string;
  commands: CliCommand[];
}

const COMMAND_GROUPS: CliCommandGroup[] = [
  {
    label: 'Daily runtime work',
    commands: [
      { base: 'marm-memory fast-start-http', description: 'Start everything, open browser' },
      { base: 'marm-memory start', description: 'Start or reuse runtime' },
      { base: 'marm-memory start', flag: '--profile swarm', description: 'Use the swarm preset' },
      { base: 'marm-memory stop', description: 'Stop the runtime' },
      { base: 'marm-memory restart', description: 'Restart the runtime' },
      { base: 'marm-memory status', description: 'Check runtime status' },
      { base: 'marm-memory logs', flag: '--follow', description: 'Follow live logs' },
      { base: 'marm-memory console', description: 'Open the local Console' },
    ],
  },
  {
    label: 'Transports and setup',
    commands: [
      { base: 'marm-memory http', description: 'Run HTTP in foreground' },
      { base: 'marm-memory stdio', description: 'Run STDIO transport' },
      { base: 'marm-memory init', description: 'Install skill, scan project' },
      { base: 'marm-memory init', flag: '--g-claude', description: 'Install skill home-wide' },
      { base: 'marm-memory doctor', description: 'Diagnose the local install' },
      { base: 'marm-memory key', flag: 'init', description: 'Create key file quietly' },
      { base: 'marm-memory key', flag: 'path', description: 'Print key file path' },
      { base: 'marm-memory console', flag: '--import-key', description: 'Open authenticated session' },
      { base: 'marm-memory upgrade', flag: '--check', description: 'Check for a newer version' },
    ],
  },
  {
    label: 'Knowledge, projects, and maintenance',
    commands: [
      { base: 'marm-memory knowledge', flag: 'status', description: 'Check indexing status' },
      { base: 'marm-memory knowledge', flag: 'build --all', description: 'Rebuild the concept graph' },
      { base: 'marm-memory knowledge', flag: 'auto off', description: 'Toggle auto indexing' },
      { base: 'marm-memory projects', flag: 'list', description: 'List tracked workspaces' },
      { base: 'marm-memory projects', flag: 'index <path>', description: 'Index a repo' },
      { base: 'marm-memory projects', flag: 'status', description: 'Check graph readiness' },
      { base: 'marm-memory projects', flag: 'auto off', description: 'Toggle auto re-indexing' },
      { base: 'marm-memory maintenance', flag: 'status', description: 'Check optimization state' },
      { base: 'marm-memory maintenance', flag: 'embeddings migrate', description: 'Upgrade to 512-dim' },
      { base: 'marm-memory maintenance', flag: 'chunks rechunk', description: 'Recalibrate memory chunking' },
    ],
  },
];

const REVIEW_FIRST_COMMANDS: CliCommand[] = [
  { base: 'marm-memory key', flag: 'reveal', description: 'Shows the secret onscreen' },
  { base: 'marm-memory uninstall', description: 'Removes package, keeps data' },
];

function fullCommand(entry: CliCommand): string {
  return entry.flag ? `${entry.base} ${entry.flag}` : entry.base;
}

function matches(entry: CliCommand, query: string): boolean {
  const needle = query.toLowerCase();
  return fullCommand(entry).toLowerCase().includes(needle) || entry.description.toLowerCase().includes(needle);
}

export function CliCommandsDialog({ open, onOpenChange, onInsertCommand }: CliCommandsDialogProps) {
  const [query, setQuery] = useState('');
  const [insertFailed, setInsertFailed] = useState(false);

  useEffect(() => {
    if (open) setInsertFailed(false);
  }, [open]);

  const filteredGroups = COMMAND_GROUPS.map((group) => ({ ...group, commands: group.commands.filter((entry) => matches(entry, query)) })).filter(
    (group) => group.commands.length > 0
  );
  const filteredReviewFirst = REVIEW_FIRST_COMMANDS.filter((entry) => matches(entry, query));
  const isEmpty = filteredGroups.length === 0 && filteredReviewFirst.length === 0;

  const handleSelect = (entry: CliCommand) => {
    if (onInsertCommand(fullCommand(entry))) {
      onOpenChange(false);
    } else {
      setInsertFailed(true);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[calc(100vh-4rem)] max-w-3xl flex-col overflow-hidden">
        <DialogHeader className="flex-row items-center justify-between space-y-0">
          <DialogTitle>MARM Commands</DialogTitle>
          <Input
            placeholder="Search commands..."
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            autoFocus
            className="w-56"
          />
        </DialogHeader>
        {insertFailed && (
          <p className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-1.5 text-xs text-amber-500">
            No active terminal session to insert into. Open a session first.
          </p>
        )}
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto py-1 pr-1">
          {isEmpty ? (
            <p className="py-6 text-center text-sm text-muted-foreground">No commands found.</p>
          ) : (
            <>
              {filteredGroups.map((group) => (
                <div key={group.label} className="space-y-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{group.label}</h3>
                  <div className="columns-2 gap-3">
                    {group.commands.map((entry) => (
                      <CommandRow key={fullCommand(entry)} entry={entry} onSelect={handleSelect} />
                    ))}
                  </div>
                </div>
              ))}
              {filteredReviewFirst.length > 0 && (
                <div className="space-y-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                  <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-amber-500">
                    <TriangleAlert className="h-3.5 w-3.5" /> Review before running
                  </h3>
                  <div className="columns-2 gap-3">
                    {filteredReviewFirst.map((entry) => (
                      <CommandRow key={fullCommand(entry)} entry={entry} onSelect={handleSelect} />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function CommandRow({ entry, onSelect }: { entry: CliCommand; onSelect: (entry: CliCommand) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(entry)}
      className="mb-2.5 flex w-full break-inside-avoid flex-col gap-1 rounded-lg border border-border/70 bg-background/35 p-3 text-left transition-colors hover:border-primary/25 hover:bg-accent/30"
    >
      <span className="flex items-center justify-between gap-2">
        <code className="truncate font-mono text-sm text-foreground">{entry.base}</code>
        {entry.flag && <code className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 font-mono text-[11px] text-primary">{entry.flag}</code>}
      </span>
      <span className="text-sm text-muted-foreground">{entry.description}</span>
    </button>
  );
}
