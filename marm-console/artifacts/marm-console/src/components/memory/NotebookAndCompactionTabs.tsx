import { useState } from 'react';
import { useNotebook, useUpsertNotebook, useDeleteNotebook, useCompaction, useRunCompactionAction } from '@/hooks/use-marm-queries';
import { Badge, Button, Input, Textarea, Card, CardContent } from '@/components/ui/core';
import { format } from 'date-fns';
import { Plus, Save, Trash2, RefreshCw, CheckCircle2, Eye, XCircle } from 'lucide-react';
import type { NotebookEntry } from '@/lib/marm-types';
import { type ActionNotice, mutationErrorMessage, ActionNoticePanel } from './shared';

export function NotebookTab() {
  const { data, isLoading } = useNotebook();
  const upsert = useUpsertNotebook();
  const deleteNote = useDeleteNotebook();
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  
  const [editing, setEditing] = useState<NotebookEntry | Partial<NotebookEntry> | null>(null);
  // name/project/platform form the entry's identity key in the store, so an
  // existing entry's identity is locked once editing starts -- otherwise
  // saving after editing one of these fields would upsert a new entry and
  // leave the original behind instead of updating it.
  const isExistingEntry = !!editing?.created_at;

  const handleSave = () => {
    if (!editing?.name || !editing?.content) return;
    upsert.mutate({
      name: editing.name,
      content: editing.content,
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
    <div className="h-full flex flex-col gap-4 overflow-hidden pb-4">
      <div className="flex justify-between items-center shrink-0">
        <h3 className="text-lg font-medium">Notebook Entries</h3>
        <Button onClick={() => setEditing({ name: '', content: '' })} size="sm">
          <Plus className="w-4 h-4 mr-2" /> New Entry
        </Button>
      </div>
      <ActionNoticePanel notice={actionNotice} />

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 flex-1 overflow-hidden">
        <div className="lg:col-span-1 border rounded-md bg-card overflow-auto">
          {data?.length === 0 ? (
            <div className="p-6 text-center text-sm text-muted-foreground">No notebook entries</div>
          ) : (
            <div className="divide-y">
              {data?.map(note => (
                <button
                  key={`${note.name}-${note.project}-${note.platform}`}
                  onClick={() => setEditing(note)}
                  className="w-full text-left p-4 hover:bg-muted transition-colors"
                >
                  <div className="font-medium text-sm">{note.name}</div>
                  <div className="flex gap-1 mt-2">
                    {note.project && <Badge variant="secondary" className="text-[10px]">{note.project}</Badge>}
                    {note.platform && <Badge variant="outline" className="text-[10px]">{note.platform}</Badge>}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="lg:col-span-3 border rounded-md bg-card flex flex-col overflow-hidden relative">
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
                Entries are keyed by name + project + platform, so the same name can exist in different scopes.
                {isExistingEntry && ' Delete and re-create the entry to change its name, project, or platform.'}
              </p>
              <Textarea 
                placeholder="Markdown content..." 
                value={editing.content || ''}
                onChange={e => setEditing(p => ({ ...p!, content: e.target.value }))}
                className="flex-1 font-mono text-sm resize-none"
              />
              <div className="flex justify-between items-center pt-2">
                {editing.created_at ? (
                  <Button 
                    variant="destructive" 
                    size="sm"
                    onClick={() => {
                      const typed = prompt(`Type DELETE to delete notebook entry '${editing.name}'.`);
                      if (typed !== 'DELETE') return;
                      deleteNote.mutate(
                        { name: editing.name!, params: { project: editing.project || undefined, platform: editing.platform || undefined } },
                        {
                          onSuccess: () => {
                            setActionNotice({ kind: 'success', message: `Notebook entry '${editing.name}' deleted.` });
                            setEditing(null);
                          },
                          onError: (error) => setActionNotice({ kind: 'error', message: mutationErrorMessage(error) }),
                        },
                      );
                    }}
                    isLoading={deleteNote.isPending}
                  >
                    <Trash2 className="w-4 h-4 mr-2" /> Delete
                  </Button>
                ) : <div />}
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
                  <Button onClick={handleSave} isLoading={upsert.isPending} disabled={!editing.name || !editing.content}>
                    <Save className="w-4 h-4 mr-2" /> Save Entry
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
              Select an entry to view or edit
            </div>
          )}
        </div>
      </div>
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

  if (isLoading) return <div className="p-8 text-center text-muted-foreground">Loading candidates...</div>;

  const pending = data?.filter(c => c.status === 'pending' || c.status === 'staged') || [];
  const history = data?.filter(c => c.status === 'applied' || c.status === 'discarded' || c.status === 'stale' || c.status === 'nudge_exhausted') || [];

  return (
    <div className="space-y-4 h-full overflow-auto pb-4">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h3 className="text-lg font-medium">Compaction Pipeline</h3>
          <p className="text-sm text-muted-foreground">Review and apply memory summaries</p>
        </div>
        <div className="flex gap-1 border rounded-md p-1 bg-muted/30">
          <Button size="sm" variant={view === 'active' ? 'secondary' : 'ghost'} onClick={() => setView('active')}>
            Active ({pending.length})
          </Button>
          <Button size="sm" variant={view === 'history' ? 'secondary' : 'ghost'} onClick={() => setView('history')}>
            History ({history.length})
          </Button>
        </div>
      </div>
      <ActionNoticePanel notice={actionNotice} />

      {view === 'history' ? (
        history.length === 0 ? (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center justify-center h-48 text-muted-foreground">
              <RefreshCw className="w-8 h-8 mb-2 opacity-50" />
              <p>No compaction history yet.</p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {history.map(c => <CompactionHistoryRow key={c.id} candidate={c} />)}
          </div>
        )
      ) : pending.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center h-48 text-muted-foreground">
            <RefreshCw className="w-8 h-8 mb-2 opacity-50" />
            <p>No pending compactions.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {pending.map(candidate => (
            <Card key={candidate.id} className="overflow-hidden">
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
    </div>
  );
}
