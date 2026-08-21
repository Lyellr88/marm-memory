import { useEffect, useState } from 'react';
import { useNotebook, useUpsertNotebook, useBulkDeleteNotebook, useCompaction, useRunCompactionAction } from '@/hooks/use-marm-queries';
import { Badge, Button, Input, Textarea, Card, CardContent, cn } from '@/components/ui/core';
import { format } from 'date-fns';
import { Plus, Save, Trash2, RefreshCw, CheckCircle2, Eye, XCircle, BookOpenText } from 'lucide-react';
import type { NotebookEntry } from '@/lib/marm-types';
import { type ActionNotice, mutationErrorMessage, ActionNoticePanel, DeleteSelectionDialog, MemoryEmptyState, PageControls } from './shared';

const NOTEBOOK_PAGE_SIZE = 20;
const COMPACTION_PAGE_SIZE = 25;

function notebookKey(entry: Pick<NotebookEntry, 'name' | 'session_name' | 'project' | 'platform'>) {
  return JSON.stringify([entry.name, entry.session_name, entry.project, entry.platform]);
}

export function NotebookTab() {
  const { data, isLoading } = useNotebook();
  const upsert = useUpsertNotebook();
  const bulkDelete = useBulkDeleteNotebook();
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [page, setPage] = useState(0);
  
  const [editing, setEditing] = useState<NotebookEntry | Partial<NotebookEntry> | null>(null);
  // name/session_name/project/platform form the entry's identity key in the
  // store, so an existing entry's identity is locked once editing starts --
  // otherwise saving after editing one of these fields would upsert a new
  // entry and leave the original behind instead of updating it.
  const isExistingEntry = !!editing?.created_at;

  const total = data?.length ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / NOTEBOOK_PAGE_SIZE));
  const visibleEntries = data?.slice(page * NOTEBOOK_PAGE_SIZE, (page + 1) * NOTEBOOK_PAGE_SIZE) ?? [];

  useEffect(() => {
    if (page >= pageCount) setPage(pageCount - 1);
  }, [page, pageCount]);

  useEffect(() => {
    const visibleKeys = new Set(visibleEntries.map(notebookKey));
    setSelectedKeys((previous) => {
      const next = new Set(Array.from(previous).filter((key) => visibleKeys.has(key)));
      return next.size === previous.size ? previous : next;
    });
  }, [data, page]);

  const allSelected = !!visibleEntries.length && visibleEntries.every((entry) => selectedKeys.has(notebookKey(entry)));

  const toggleEntry = (entry: NotebookEntry) => {
    const key = notebookKey(entry);
    setSelectedKeys((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const confirmDelete = () => {
    const entries = visibleEntries
      .filter((entry) => selectedKeys.has(notebookKey(entry)))
      .map(({ name, session_name, project, platform }) => ({ name, session_name, project, platform }));
    if (!entries.length) return;
    bulkDelete.mutate(entries, {
      onSuccess: (result) => {
        const failedKeys = new Set(result.failed_entries.map(notebookKey));
        if (editing && selectedKeys.has(notebookKey(editing as NotebookEntry)) && !failedKeys.has(notebookKey(editing as NotebookEntry))) {
          setEditing(null);
        }
        setSelectedKeys(failedKeys);
        setDeleteOpen(false);
        setActionNotice({
          kind: result.failed_entries.length ? 'warning' : 'success',
          message: result.failed_entries.length
            ? `${result.deleted_entries} notebook entries deleted; ${result.failed_entries.length} could not be deleted.`
            : `${result.deleted_entries} notebook entries deleted.`,
        });
      },
      onError: (error) => setActionNotice({ kind: 'error', message: mutationErrorMessage(error) }),
    });
  };

  const handleSave = () => {
    if (!editing?.name || !editing?.content) return;
    upsert.mutate({
      name: editing.name,
      content: editing.content,
      session_name: editing.session_name || 'main',
      project: editing.project,
      platform: editing.platform
    }, {
      onSuccess: () => {
        setActionNotice({ kind: 'success', message: `Notebook entry '${editing.name}' saved.` });
        setEditing(null);
      },
      onError: (error) => setActionNotice({ kind: 'error', message: mutationErrorMessage(error) }),
    });
  };

  if (isLoading) return <div className="p-8 text-center text-muted-foreground">Loading notebook...</div>;

  return (
    <div className="flex h-full flex-col gap-4 overflow-hidden pb-4">
      <div className="flex shrink-0 items-center justify-between rounded-xl border border-card-border bg-card/70 p-2 pl-4 shadow-[0_12px_34px_rgba(0,0,0,0.14)]">
        <div>
          <h3 className="font-semibold tracking-tight">Notebook entries</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">Persistent reference material scoped to your work</p>
        </div>
        <div className="flex items-center gap-3">
          {!!data?.length && (
            <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={() => setSelectedKeys(allSelected ? new Set() : new Set(visibleEntries.map(notebookKey)))}
                className="rounded border-input bg-background"
              />
              Select all
            </label>
          )}
          {selectedKeys.size > 0 ? (
            <Button className="bulk-action-enter" variant="destructive" onClick={() => setDeleteOpen(true)} size="sm">
              <Trash2 className="w-4 h-4 mr-2" /> Delete {selectedKeys.size}
            </Button>
          ) : (
            <Button onClick={() => setEditing({ name: '', content: '' })} size="sm">
              <Plus className="w-4 h-4 mr-2" /> New Entry
            </Button>
          )}
        </div>
      </div>
      <ActionNoticePanel notice={actionNotice} />

      <div className="grid flex-1 grid-cols-1 gap-4 overflow-hidden lg:grid-cols-4">
        <div className="flex flex-col overflow-hidden rounded-xl border border-card-border border-t-primary/35 bg-card/75 shadow-[0_18px_50px_rgba(0,0,0,0.16)] lg:col-span-1">
          {total === 0 ? (
            <MemoryEmptyState title="No notebook entries" detail="Pin durable reference material here." className="min-h-full" />
          ) : (
            <div className="min-h-0 flex-1 overflow-auto divide-y">
              {visibleEntries.map(note => (
                <div
                  key={notebookKey(note)}
                  className={cn(
                    'flex items-start border-l-2 border-l-transparent transition-[color,background-color,border-color,box-shadow] hover:border-l-violet-400 hover:bg-violet-400/[0.04]',
                    selectedKeys.has(notebookKey(note)) && 'border-l-violet-400 bg-violet-400/[0.055] shadow-[inset_3px_0_0_rgba(192,132,252,0.5)]',
                  )}
                >
                  <input
                    type="checkbox"
                    checked={selectedKeys.has(notebookKey(note))}
                    onChange={() => toggleEntry(note)}
                    aria-label={`Select notebook entry ${note.name}`}
                    className="ml-4 mt-5 rounded border-input bg-background"
                  />
                  <button onClick={() => setEditing(note)} className="min-w-0 flex-1 p-4 text-left">
                    <div className="font-medium text-sm">{note.name}</div>
                    <div className="flex gap-1 mt-2">
                      <Badge variant="secondary" className="text-[10px]">{note.session_name}</Badge>
                      {note.project && <Badge variant="secondary" className="text-[10px]">{note.project}</Badge>}
                      {note.platform && <Badge variant="outline" className="text-[10px]">{note.platform}</Badge>}
                    </div>
                  </button>
                </div>
              ))}
            </div>
          )}
          {total > 0 && (
            <PageControls
              page={page}
              pageSize={NOTEBOOK_PAGE_SIZE}
              total={total}
              itemLabel="entries"
              onPageChange={setPage}
            />
          )}
        </div>

        <div className="relative flex flex-col overflow-hidden rounded-xl border border-card-border border-t-primary/35 bg-card/75 shadow-[0_18px_50px_rgba(0,0,0,0.16)] lg:col-span-3">
          {editing ? (
            <div className="p-6 flex flex-col h-full gap-4">
              <div className="flex gap-4">
                <Input
                  placeholder="Entry Name"
                  value={editing.name || ''}
                  onChange={e => setEditing(p => ({ ...p!, name: e.target.value }))}
                  className="font-mono"
                  disabled={isExistingEntry}
                />
                <Input
                  placeholder="Session (default: main)"
                  value={editing.session_name || ''}
                  onChange={e => setEditing(p => ({ ...p!, session_name: e.target.value }))}
                  className="w-40 font-mono"
                  disabled={isExistingEntry}
                />
                <Input
                  placeholder="Project (optional)"
                  value={editing.project || ''}
                  onChange={e => setEditing(p => ({ ...p!, project: e.target.value }))}
                  className="w-40 font-mono"
                  disabled={isExistingEntry}
                />
                <Input
                  placeholder="Platform (optional)"
                  value={editing.platform || ''}
                  onChange={e => setEditing(p => ({ ...p!, platform: e.target.value }))}
                  className="w-40 font-mono"
                  disabled={isExistingEntry}
                />
              </div>
              <p className="text-xs text-muted-foreground -mt-2">
                Entries are keyed by name + session + project + platform, so the same name can exist in different scopes.
                {isExistingEntry && ' Delete and re-create the entry to change its name, session, project, or platform.'}
              </p>
              <Textarea 
                placeholder="Markdown content..." 
                value={editing.content || ''}
                onChange={e => setEditing(p => ({ ...p!, content: e.target.value }))}
                className="flex-1 font-mono text-sm resize-none"
              />
              <div className="flex justify-end pt-2">
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
                  <Button onClick={handleSave} isLoading={upsert.isPending} disabled={!editing.name || !editing.content}>
                    <Save className="w-4 h-4 mr-2" /> Save Entry
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center text-sm text-muted-foreground">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl border border-primary/20 bg-primary/[0.06] text-primary">
                <BookOpenText className="h-5 w-5" />
              </div>
              <span>Select an entry to view or edit</span>
              <span className="mt-1 text-xs text-muted-foreground/70">Notebook content remains available across sessions.</span>
            </div>
          )}
        </div>
      </div>
      <DeleteSelectionDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        count={selectedKeys.size}
        itemLabel="notebook entry"
        description="The selected notebook entries will be removed from their exact session, project, and platform scopes."
        isPending={bulkDelete.isPending}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

const HISTORY_STATUS_LABEL: Record<string, string> = {
  applied: 'Applied',
  discarded: 'Discarded',
  stale: 'Stale',
  nudge_exhausted: 'Nudge Exhausted',
};

function CompactionHistoryRow({ candidate }: { candidate: import('@/lib/marm-types').CompactionCandidate }) {
  const variant = candidate.status === 'applied' ? 'default' : candidate.status === 'discarded' ? 'outline' : 'secondary';
  return (
    <div className="flex items-center justify-between p-3 rounded-lg border bg-muted/20">
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Badge variant={variant as any} className="text-[10px] uppercase">{HISTORY_STATUS_LABEL[candidate.status] || candidate.status}</Badge>
          <span className="text-sm font-mono">{candidate.session_name}</span>
        </div>
        <span className="text-xs text-muted-foreground line-clamp-1 max-w-md">{candidate.proposed_summary}</span>
      </div>
      <div className="text-xs text-muted-foreground whitespace-nowrap">
        {candidate.source_memory_ids.length} sources
      </div>
    </div>
  );
}

export function CompactionTab() {
  const { data, isLoading } = useCompaction();
  const runAction = useRunCompactionAction();
  const [view, setView] = useState<'active' | 'history'>('active');
  const [page, setPage] = useState(0);
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);

  const handleCompactionAction = (id: string, action: 'stage' | 'apply' | 'discard') => {
    runAction.mutate({ id, action }, {
      onSuccess: () => {
        const label = action === 'stage' ? 'staged for review' : action === 'apply' ? 'applied' : 'discarded';
        setActionNotice({ kind: 'success', message: `Compaction candidate ${label}.` });
      },
      onError: (error) => setActionNotice({ kind: 'error', message: mutationErrorMessage(error) }),
    });
  };

  const pending = data?.filter(c => c.status === 'pending' || c.status === 'staged') || [];
  const history = data?.filter(c => c.status === 'applied' || c.status === 'discarded' || c.status === 'stale' || c.status === 'nudge_exhausted') || [];
  const candidates = view === 'history' ? history : pending;
  const pageCount = Math.max(1, Math.ceil(candidates.length / COMPACTION_PAGE_SIZE));
  const visibleCandidates = candidates.slice(page * COMPACTION_PAGE_SIZE, (page + 1) * COMPACTION_PAGE_SIZE);

  useEffect(() => {
    if (page >= pageCount) setPage(pageCount - 1);
  }, [page, pageCount]);

  if (isLoading) return <div className="p-8 text-center text-muted-foreground">Loading candidates...</div>;

  return (
    <div className="h-full space-y-4 overflow-auto pb-4">
      <div className="flex items-center justify-between rounded-xl border border-card-border bg-card/70 p-3 pl-4 shadow-[0_12px_34px_rgba(0,0,0,0.14)]">
        <div>
          <h3 className="text-lg font-medium">Compaction Pipeline</h3>
          <p className="text-sm text-muted-foreground">Review and apply memory summaries</p>
        </div>
        <div className="flex gap-1 border rounded-md p-1 bg-muted/30">
          <Button size="sm" variant={view === 'active' ? 'secondary' : 'ghost'} onClick={() => { setView('active'); setPage(0); }}>
            Active ({pending.length})
          </Button>
          <Button size="sm" variant={view === 'history' ? 'secondary' : 'ghost'} onClick={() => { setView('history'); setPage(0); }}>
            History ({history.length})
          </Button>
        </div>
      </div>
      <ActionNoticePanel notice={actionNotice} />

      {view === 'history' ? (
        history.length === 0 ? (
          <Card className="border-dashed border-amber-400/20 bg-card/55">
            <CardContent className="p-3">
              <MemoryEmptyState title="No compaction history yet" detail="Completed summaries will leave an audit trail here." />
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {visibleCandidates.map(c => <CompactionHistoryRow key={c.id} candidate={c} />)}
          </div>
        )
      ) : pending.length === 0 ? (
        <Card className="border-dashed border-amber-400/20 bg-card/55">
          <CardContent className="p-3">
            <MemoryEmptyState title="No pending compactions" detail="MARM will surface summaries here when enough related context accumulates." />
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {visibleCandidates.map(candidate => (
            <Card
              key={candidate.id}
              className={cn(
                'overflow-hidden border-t-2 border-t-amber-400/40',
                runAction.isPending && runAction.variables?.id === candidate.id && runAction.variables.action === 'apply' && 'compaction-collapse',
              )}
            >
              <div className="flex flex-col md:flex-row">
                <div className="flex-1 p-6 border-b md:border-b-0 md:border-r bg-muted/10">
                  <div className="flex justify-between items-center mb-4">
                    <Badge variant="outline" className="font-mono text-xs">{candidate.session_name}</Badge>
                    <span className="text-xs text-muted-foreground">
                      {candidate.source_memory_ids.length} sources → 1 summary
                    </span>
                  </div>
                  <div className="font-mono text-sm leading-relaxed p-4 bg-background border rounded-md">
                    {candidate.proposed_summary}
                  </div>
                  <div className="mt-4 flex gap-4 text-xs text-muted-foreground">
                    <span className="text-emerald-500 font-medium">-{candidate.expected_reduction}% size</span>
                    {candidate.expiry && <span>Expires {format(new Date(candidate.expiry), 'MMM d, HH:mm')}</span>}
                  </div>
                </div>
                <div className="w-full md:w-64 p-6 bg-card flex flex-col justify-center gap-3">
                  <Button 
                    className="w-full justify-start" 
                    variant="default"
                    isLoading={runAction.isPending}
                    onClick={() => handleCompactionAction(candidate.id, 'apply')}
                  >
                    <CheckCircle2 className="w-4 h-4 mr-2" /> Apply Summary
                  </Button>
                  {candidate.status === 'pending' && (
                    <Button 
                      className="w-full justify-start" 
                      variant="secondary"
                      isLoading={runAction.isPending}
                      onClick={() => handleCompactionAction(candidate.id, 'stage')}
                    >
                      <Eye className="w-4 h-4 mr-2" /> Stage for Review
                    </Button>
                  )}
                  <Button 
                    className="w-full justify-start text-destructive hover:text-destructive" 
                    variant="ghost"
                    isLoading={runAction.isPending}
                    onClick={() => handleCompactionAction(candidate.id, 'discard')}
                  >
                    <XCircle className="w-4 h-4 mr-2" /> Discard
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
      {candidates.length > 0 && (
        <PageControls
          page={page}
          pageSize={COMPACTION_PAGE_SIZE}
          total={candidates.length}
          itemLabel={view === 'history' ? 'history entries' : 'active candidates'}
          onPageChange={setPage}
        />
      )}
    </div>
  );
}
