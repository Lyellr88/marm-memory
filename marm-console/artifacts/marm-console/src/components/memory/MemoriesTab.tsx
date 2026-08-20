import { useState, useEffect } from 'react';
import { useMemories, useFilters, useCreateMemory, useUpdateMemory, useDeleteMemory, useBulkDeleteMemories } from '@/hooks/use-marm-queries';
import { Badge, Button, Input, Select, SelectTrigger, SelectValue, SelectContent, SelectItem, Table, TableHeader, TableRow, TableHead, TableBody, TableCell, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, Textarea, Label, cn } from '@/components/ui/core';
import { format } from 'date-fns';
import { BrainCircuit, CircleAlert, FileText, Lightbulb, MessageSquareText, Search, Trash2, Plus, Edit2, Wrench } from 'lucide-react';
import type { Memory, MemoryId, MemoryListParams } from '@/lib/marm-types';
import { type ActionNotice, mutationErrorMessage, deleteNotice, ActionNoticePanel, DeleteSelectionDialog, MemoryEmptyState } from './shared';

function memoryContext(contextType: string | null) {
  const value = (contextType || 'general').toLowerCase();
  if (value.includes('decision')) return { icon: Lightbulb, tone: 'text-amber-300 border-amber-400/20 bg-amber-400/[0.06]', rail: 'border-l-amber-400/70' };
  if (value.includes('error') || value.includes('issue')) return { icon: CircleAlert, tone: 'text-red-300 border-red-400/20 bg-red-400/[0.06]', rail: 'border-l-red-400/70' };
  if (value.includes('doc') || value.includes('book') || value.includes('handbook')) return { icon: FileText, tone: 'text-violet-300 border-violet-400/20 bg-violet-400/[0.06]', rail: 'border-l-violet-400/70' };
  if (value.includes('code') || value.includes('project') || value.includes('tool')) return { icon: Wrench, tone: 'text-blue-300 border-blue-400/20 bg-blue-400/[0.06]', rail: 'border-l-blue-400/70' };
  if (value.includes('concept') || value.includes('pattern')) return { icon: BrainCircuit, tone: 'text-teal-300 border-teal-400/20 bg-teal-400/[0.06]', rail: 'border-l-teal-400/70' };
  return { icon: MessageSquareText, tone: 'text-primary border-primary/20 bg-primary/[0.06]', rail: 'border-l-primary/70' };
}

function MemoryRow({ 
  memory, 
  onSelect,
  selected,
  fresh,
  onToggleSelect 
}: { 
  memory: Memory, 
  onSelect: (m: Memory) => void,
  selected: boolean,
  fresh: boolean,
  onToggleSelect: (id: MemoryId) => void
}) {
  const context = memoryContext(memory.context_type);
  const ContextIcon = context.icon;
  return (
    <TableRow
      className={cn(
        'group cursor-pointer border-l-2 transition-[background-color,border-color,box-shadow] duration-200 hover:bg-primary/[0.045] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
        context.rail,
        selected && 'bg-primary/[0.065] shadow-[inset_3px_0_0_rgba(var(--primary-rgb),0.75)]',
        fresh && 'memory-new',
      )}
      onClick={() => onSelect(memory)}
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.currentTarget !== event.target) return;
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelect(memory);
        }
      }}
    >
      <TableCell className="w-[40px] pl-4" onClick={(e) => e.stopPropagation()}>
        <input 
          type="checkbox" 
          checked={selected}
          onChange={() => onToggleSelect(memory.id)}
          aria-label={`Select memory ${memory.id}`}
          className="rounded border-input bg-background"
        />
      </TableCell>
      <TableCell className="w-[100px] font-mono text-xs text-muted-foreground">{format(new Date(memory.created_at), 'MMM d, HH:mm')}</TableCell>
      <TableCell>
        <div className="flex gap-2 mb-1">
          <Badge variant="outline" className="text-[10px] py-0">{memory.session_name}</Badge>
          {memory.project && <Badge variant="secondary" className="text-[10px] py-0">{memory.project}</Badge>}
          <Badge variant="outline" className={cn('gap-1 text-[10px] py-0', context.tone)}>
            <ContextIcon className="h-2.5 w-2.5" /> {memory.context_type || 'general'}
          </Badge>
        </div>
        <div className="line-clamp-2 text-sm leading-relaxed text-foreground/90 transition-colors group-hover:text-foreground">{memory.content}</div>
      </TableCell>
      <TableCell className="text-right">
        {memory.compaction_role !== 'none' && (
          <Badge variant={memory.compaction_role === 'summary' ? 'default' : 'outline'} className="text-[10px]">
            {memory.compaction_role}
          </Badge>
        )}
      </TableCell>
    </TableRow>
  );
}

export function MemoriesTab() {
  const [params, setParams] = useState<MemoryListParams>({ limit: 50 });
  const { data, isLoading } = useMemories(params);
  const { data: filters } = useFilters();
  const [selectedMemory, setSelectedMemory] = useState<Memory | null>(null);
  const [freshMemoryId, setFreshMemoryId] = useState<MemoryId | null>(null);
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  
  const [selectedIds, setSelectedIds] = useState<Set<MemoryId>>(new Set());
  const [deleteTarget, setDeleteTarget] = useState<{ ids: MemoryId[]; memory?: Memory } | null>(null);
  const bulkDelete = useBulkDeleteMemories();

  // Drop selections that are no longer in the visible result set (search,
  // filter, or pagination changed) so bulk delete can't act on hidden rows.
  useEffect(() => {
    if (!data?.items) return;
    const visibleIds = new Set(data.items.map(m => m.id));
    setSelectedIds(prev => {
      let changed = false;
      const next = new Set<MemoryId>();
      for (const id of prev) {
        if (visibleIds.has(id)) next.add(id);
        else changed = true;
      }
      return changed ? next : prev;
    });
  }, [data?.items]);

  const allVisibleSelected = !!data?.items.length && data.items.every(m => selectedIds.has(m.id));

  const toggleSelect = (id: MemoryId) => {
    const newSet = new Set(selectedIds);
    if (newSet.has(id)) newSet.delete(id);
    else newSet.add(id);
    setSelectedIds(newSet);
  };

  const toggleAll = () => {
    if (allVisibleSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(data?.items.map(m => m.id)));
    }
  };

  const requestBulkDelete = () => {
    // Recompute against the current visible items instead of trusting
    // selectedIds directly -- the cleanup effect runs after render, so a
    // stale ID could still be present in selectedIds at click time if
    // data changed on this same render.
    const visibleIds = new Set(data?.items.map(m => m.id));
    const targetIds = Array.from(selectedIds).filter(id => visibleIds.has(id));
    if (targetIds.length === 0) return;
    setDeleteTarget({ ids: targetIds });
  };

  const confirmDelete = () => {
    if (!deleteTarget) return;
    if (deleteTarget.memory) {
      deleteMemory.mutate(deleteTarget.memory.id, {
        onSuccess: (result) => {
          setSelectedMemory(null);
          setDeleteTarget(null);
          setActionNotice(deleteNotice(result, 'Memory deleted.'));
        },
        onError: (error) => setActionNotice({ kind: 'error', message: mutationErrorMessage(error) }),
      });
    } else {
      bulkDelete.mutate(deleteTarget.ids, {
        onSuccess: (result) => {
          setSelectedIds(new Set());
          setDeleteTarget(null);
          setActionNotice(deleteNotice(result, 'Selected memory deleted.'));
        },
        onError: (error) => setActionNotice({ kind: 'error', message: mutationErrorMessage(error) }),
      });
    }
  };

  const [editMode, setEditMode] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [editProject, setEditProject] = useState('');
  const [editPlatform, setEditPlatform] = useState('');
  const [editContextType, setEditContextType] = useState('');
  const [createMode, setCreateMode] = useState(false);
  const [newSession, setNewSession] = useState('');
  const [newProject, setNewProject] = useState('');
  const [newPlatform, setNewPlatform] = useState('');
  const [newContextType, setNewContextType] = useState('');
  
  const createMemory = useCreateMemory();
  const updateMemory = useUpdateMemory();
  const deleteMemory = useDeleteMemory();

  const handleCreate = () => {
    createMemory.mutate({
      content: editContent,
      session_name: newSession.trim(),
      project: newProject.trim() || null,
      platform: newPlatform.trim() || null,
      context_type: newContextType.trim() || 'general',
    }, {
      onSuccess: (created) => {
        setCreateMode(false);
        setEditContent('');
        setNewSession('');
        setNewProject('');
        setNewPlatform('');
        setNewContextType('');
        setActionNotice({ kind: 'success', message: 'Memory created.' });
        setFreshMemoryId(created.id);
        window.setTimeout(() => {
          setFreshMemoryId((current) => current === created.id ? null : current);
        }, 2600);
      },
      onError: (error) => setActionNotice({ kind: 'error', message: mutationErrorMessage(error) }),
    });
  };

  const handleUpdate = () => {
    if (!selectedMemory) return;
    // context_type has no null/blank state on the server -- it's a required
    // non-empty string there (and downstream recall code assumes as much),
    // so clearing the field falls back to the same 'general' default used
    // for new memories, not the previous value and not null.
    updateMemory.mutate({
      id: selectedMemory.id,
      data: {
        content: editContent,
        session_name: selectedMemory.session_name,
        project: editProject.trim() || null,
        platform: editPlatform.trim() || null,
        context_type: editContextType.trim() || 'general',
        metadata: selectedMemory.metadata,
      }
    }, {
      onSuccess: () => {
        setEditMode(false);
        setSelectedMemory({
          ...selectedMemory,
          content: editContent,
          project: editProject.trim() || null,
          platform: editPlatform.trim() || null,
          context_type: editContextType.trim() || 'general',
        });
        setActionNotice({ kind: 'success', message: 'Memory updated.' });
      },
      onError: (error) => setActionNotice({ kind: 'error', message: mutationErrorMessage(error) }),
    });
  };

  const requestSingleDelete = () => {
    if (!selectedMemory) return;
    setDeleteTarget({ ids: [selectedMemory.id], memory: selectedMemory });
  };

  const deleteDescription = deleteTarget?.memory
    ? [
        deleteTarget.memory.compaction_role === 'source'
          ? 'This memory is a compaction source. Its linked summary may continue to reference content that no longer exists.'
          : deleteTarget.memory.compaction_role === 'summary'
            ? 'This memory is a compaction summary. Deleting it removes the compacted record permanently.'
            : 'This memory will be removed permanently.',
        deleteTarget.memory.concept_link_count > 0
          ? `MARM will also attempt to clean up its ${deleteTarget.memory.concept_link_count} concept link(s).`
          : '',
      ].filter(Boolean).join(' ')
    : 'The selected memories and their graph provenance will be removed permanently.';

  const relatedMemories = selectedMemory
    ? (data?.items ?? [])
        .filter((memory) => memory.id !== selectedMemory.id)
        .filter((memory) =>
          memory.session_name === selectedMemory.session_name
          || (!!memory.project && memory.project === selectedMemory.project)
        )
        .slice(0, 3)
    : [];

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex shrink-0 items-center gap-3 rounded-xl border border-card-border bg-card/70 p-2 shadow-[0_12px_34px_rgba(0,0,0,0.14)]">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input 
            placeholder="Search memories..." 
            className="border-transparent bg-background/65 pl-9 hover:border-primary/25"
            value={params.q || ''}
            onChange={e => setParams(p => ({ ...p, q: e.target.value || undefined }))}
          />
        </div>
        <Select value={params.session || "all"} onValueChange={v => setParams(p => ({ ...p, session: v === "all" ? undefined : v }))}>
          <SelectTrigger className="w-[180px] border-transparent bg-background/65">
            <SelectValue placeholder="Session" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Sessions</SelectItem>
            {filters?.sessions.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={params.compaction_role || "all"} onValueChange={v => setParams(p => ({ ...p, compaction_role: v === "all" ? undefined : v as any }))}>
          <SelectTrigger className="w-[180px] border-transparent bg-background/65">
            <SelectValue placeholder="Compaction Role" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Any Role</SelectItem>
            <SelectItem value="none">None</SelectItem>
            <SelectItem value="source">Source</SelectItem>
            <SelectItem value="summary">Summary</SelectItem>
            <SelectItem value="compacted">Compacted (Virtual)</SelectItem>
          </SelectContent>
        </Select>
        {selectedIds.size > 0 ? (
          <Button className="bulk-action-enter" variant="destructive" onClick={requestBulkDelete} isLoading={bulkDelete.isPending}>
            <Trash2 className="w-4 h-4 mr-2" /> Delete {selectedIds.size}
          </Button>
        ) : (
          <Button onClick={() => { setCreateMode(true); setEditContent(''); setNewSession(''); setNewProject(''); setNewPlatform(''); setNewContextType(''); }}>
            <Plus className="w-4 h-4 mr-2" /> New
          </Button>
        )}
      </div>
      <ActionNoticePanel notice={actionNotice} />

      <div className="min-h-0 flex-1 overflow-auto rounded-xl shadow-[0_18px_50px_rgba(0,0,0,0.16)] [&>div]:min-h-full [&>div]:border-card-border [&>div]:border-t-primary/35">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-card/95 backdrop-blur-xl">
            <TableRow>
              <TableHead className="w-[40px] pl-4">
                <input 
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleAll}
                  className="rounded border-input bg-background"
                />
              </TableHead>
              <TableHead>Time</TableHead>
              <TableHead>Content & Context</TableHead>
              <TableHead className="text-right">Role</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow><TableCell colSpan={4} className="h-24 text-center text-muted-foreground">Loading memories...</TableCell></TableRow>
            ) : data?.items.length === 0 ? (
              <TableRow><TableCell colSpan={4} className="p-4"><MemoryEmptyState title="No memories found" detail="Try a wider search or capture new context." /></TableCell></TableRow>
            ) : (
              data?.items.map(m => (
                <MemoryRow 
                  key={m.id} 
                  memory={m} 
                  onSelect={(m) => {
                    setSelectedMemory(m);
                    setEditMode(false);
                  }}
                  selected={selectedIds.has(m.id)}
                  fresh={freshMemoryId === m.id}
                  onToggleSelect={toggleSelect}
                />
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={createMode} onOpenChange={setCreateMode}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>New Memory</DialogTitle>
            <DialogDescription>Manually inject context into MARM. Blank scope fields are stored as null.</DialogDescription>
          </DialogHeader>
          <div className="py-4 space-y-4">
            <div className="grid grid-cols-3 gap-2">
              <div className="space-y-1">
                <Label className="text-xs">Session name *</Label>
                <Input placeholder="e.g. main" value={newSession} onChange={e => setNewSession(e.target.value)} className="font-mono text-xs" list="session-suggestions" />
                <datalist id="session-suggestions">
                  {filters?.sessions.map(s => <option key={s} value={s} />)}
                </datalist>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Project</Label>
                <Input placeholder="optional" value={newProject} onChange={e => setNewProject(e.target.value)} className="text-xs" list="project-suggestions" />
                <datalist id="project-suggestions">
                  {filters?.projects.map(p => <option key={p} value={p} />)}
                </datalist>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Platform</Label>
                <Input placeholder="optional" value={newPlatform} onChange={e => setNewPlatform(e.target.value)} className="text-xs" list="platform-suggestions" />
                <datalist id="platform-suggestions">
                  {filters?.platforms.map(p => <option key={p} value={p} />)}
                </datalist>
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Context type</Label>
              <Input placeholder="optional" value={newContextType} onChange={e => setNewContextType(e.target.value)} className="text-xs" list="context-type-suggestions" />
              <datalist id="context-type-suggestions">
                {filters?.context_types.map(c => <option key={c} value={c} />)}
              </datalist>
            </div>
            <Textarea 
              placeholder="Memory content..."
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className="min-h-[150px]"
            />
          </div>
          <ActionNoticePanel notice={createMemory.error ? { kind: 'error', message: mutationErrorMessage(createMemory.error) } : null} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateMode(false)}>Cancel</Button>
            <Button onClick={handleCreate} isLoading={createMemory.isPending} disabled={!editContent || !newSession.trim()}>Create</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!selectedMemory && !createMode} onOpenChange={(o) => !o && setSelectedMemory(null)}>
        <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>Memory Details</DialogTitle>
            <DialogDescription className="font-mono text-xs">ID: {selectedMemory?.id} | Hash: {selectedMemory?.content_hash.substring(0,8)}</DialogDescription>
          </DialogHeader>
          <div className="flex-1 overflow-auto py-4 space-y-6">
            <div>
              <div className="flex justify-between items-center mb-2">
                <div className="text-sm font-medium text-muted-foreground">Content</div>
                {!editMode && (
                  <Button variant="ghost" size="sm" className="h-6" onClick={() => {
                    setEditMode(true);
                    setEditContent(selectedMemory?.content || '');
                    setEditProject(selectedMemory?.project || '');
                    setEditPlatform(selectedMemory?.platform || '');
                    setEditContextType(selectedMemory?.context_type || '');
                  }}>
                    <Edit2 className="w-3 h-3 mr-1" /> Edit
                  </Button>
                )}
              </div>
              {editMode ? (
                <div className="space-y-2">
                  <Textarea 
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    className="min-h-[150px]"
                  />
                  <div className="grid grid-cols-3 gap-2">
                    <Input placeholder="Project (blank = null)" value={editProject} onChange={e => setEditProject(e.target.value)} className="text-xs" />
                    <Input placeholder="Platform (blank = null)" value={editPlatform} onChange={e => setEditPlatform(e.target.value)} className="text-xs" />
                    <Input placeholder="Context type (blank = general)" value={editContextType} onChange={e => setEditContextType(e.target.value)} className="text-xs" />
                  </div>
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" size="sm" onClick={() => setEditMode(false)}>Cancel</Button>
                    <Button size="sm" onClick={handleUpdate} isLoading={updateMemory.isPending}>Save</Button>
                  </div>
                </div>
              ) : (
                <div className="p-4 bg-muted/30 rounded-md font-mono text-sm whitespace-pre-wrap">
                  {selectedMemory?.content}
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-muted-foreground">Session:</span>
                <Badge variant="outline" className="ml-2">{selectedMemory?.session_name}</Badge>
              </div>
              {selectedMemory?.project && (
                <div>
                  <span className="text-muted-foreground">Project:</span>
                  <Badge variant="outline" className="ml-2">{selectedMemory.project}</Badge>
                </div>
              )}
              {selectedMemory?.platform && (
                <div>
                  <span className="text-muted-foreground">Platform:</span>
                  <Badge variant="outline" className="ml-2">{selectedMemory.platform}</Badge>
                </div>
              )}
              {selectedMemory?.context_type && (
                <div>
                  <span className="text-muted-foreground">Context type:</span>
                  <Badge variant="outline" className="ml-2">{selectedMemory.context_type}</Badge>
                </div>
              )}
              <div>
                <span className="text-muted-foreground">Created:</span>
                <span className="ml-2 font-mono">{selectedMemory && format(new Date(selectedMemory.created_at), 'PP pp')}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Concept Links:</span>
                <span className="ml-2">{selectedMemory?.concept_link_count}</span>
              </div>
            </div>
            {relatedMemories.length > 0 && (
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm font-medium text-muted-foreground">Related context in this view</span>
                  <Badge variant="outline" className="text-[9px]">same session or project</Badge>
                </div>
                <div className="space-y-2">
                  {relatedMemories.map((memory) => (
                    <button
                      key={memory.id}
                      type="button"
                      onClick={() => { setSelectedMemory(memory); setEditMode(false); }}
                      className="group w-full rounded-lg border border-border/70 bg-background/40 p-3 text-left transition-[border-color,background-color,transform] duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:bg-primary/[0.035] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <span className="line-clamp-2 text-xs leading-relaxed text-foreground/80 group-hover:text-foreground">{memory.content}</span>
                      <span className="mt-2 block font-mono text-[10px] text-muted-foreground">{memory.session_name}{memory.project ? ` · ${memory.project}` : ''}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            <ActionNoticePanel notice={updateMemory.error ? { kind: 'error', message: mutationErrorMessage(updateMemory.error) } : deleteMemory.error ? { kind: 'error', message: mutationErrorMessage(deleteMemory.error) } : null} />
          </div>
          <DialogFooter className="flex justify-between sm:justify-between items-center">
            <Button variant="destructive" onClick={requestSingleDelete} isLoading={deleteMemory.isPending}>
              <Trash2 className="w-4 h-4 mr-2" /> Delete
            </Button>
            <Button variant="outline" onClick={() => setSelectedMemory(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <DeleteSelectionDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        count={deleteTarget?.ids.length ?? 0}
        itemLabel="memory"
        description={deleteDescription}
        isPending={bulkDelete.isPending || deleteMemory.isPending}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
