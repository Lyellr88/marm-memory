import { useState, useEffect } from 'react';
import { useMemories, useFilters, useCreateMemory, useUpdateMemory, useDeleteMemory, useBulkDeleteMemories } from '@/hooks/use-marm-queries';
import { Badge, Button, Input, Select, SelectTrigger, SelectValue, SelectContent, SelectItem, Table, TableHeader, TableRow, TableHead, TableBody, TableCell, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, Textarea, Label } from '@/components/ui/core';
import { format } from 'date-fns';
import { Search, Trash2, Plus, Edit2 } from 'lucide-react';
import type { Memory, MemoryId, MemoryListParams } from '@/lib/marm-types';
import { type ActionNotice, mutationErrorMessage, deleteNotice, ActionNoticePanel } from './shared';

function MemoryRow({ 
  memory, 
  onSelect,
  selected,
  onToggleSelect 
}: { 
  memory: Memory, 
  onSelect: (m: Memory) => void,
  selected: boolean,
  onToggleSelect: (id: MemoryId) => void
}) {
  return (
    <TableRow className="cursor-pointer hover:bg-muted/50" onClick={() => onSelect(memory)}>
      <TableCell className="w-[40px] pl-4" onClick={(e) => e.stopPropagation()}>
        <input 
          type="checkbox" 
          checked={selected}
          onChange={() => onToggleSelect(memory.id)}
          className="rounded border-input bg-background"
        />
      </TableCell>
      <TableCell className="w-[100px] font-mono text-xs text-muted-foreground">{format(new Date(memory.created_at), 'MMM d, HH:mm')}</TableCell>
      <TableCell>
        <div className="flex gap-2 mb-1">
          <Badge variant="outline" className="text-[10px] py-0">{memory.session_name}</Badge>
          {memory.project && <Badge variant="secondary" className="text-[10px] py-0">{memory.project}</Badge>}
        </div>
        <div className="text-sm line-clamp-2">{memory.content}</div>
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
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  
  const [selectedIds, setSelectedIds] = useState<Set<MemoryId>>(new Set());
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

  const handleBulkDelete = () => {
    // Recompute against the current visible items instead of trusting
    // selectedIds directly -- the cleanup effect runs after render, so a
    // stale ID could still be present in selectedIds at click time if
    // data changed on this same render.
    const visibleIds = new Set(data?.items.map(m => m.id));
    const targetIds = Array.from(selectedIds).filter(id => visibleIds.has(id));
    if (targetIds.length === 0) return;
    const typed = prompt(`Type DELETE to delete ${targetIds.length} selected memories.`);
    if (typed === 'DELETE') {
      bulkDelete.mutate(targetIds, {
        onSuccess: (result) => {
          setSelectedIds(new Set());
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
      onSuccess: () => {
        setCreateMode(false);
        setEditContent('');
        setNewSession('');
        setNewProject('');
        setNewPlatform('');
        setNewContextType('');
        setActionNotice({ kind: 'success', message: 'Memory created.' });
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

  const handleDelete = () => {
    if (!selectedMemory) return;
    const warnings: string[] = [];
    if (selectedMemory.compaction_role === 'source') {
      warnings.push('This memory is a compaction source — its linked summary may reference content that no longer exists.');
    } else if (selectedMemory.compaction_role === 'summary') {
      warnings.push('This memory is a compaction summary — deleting it removes the compacted record entirely.');
    }
    if (selectedMemory.concept_link_count > 0) {
      warnings.push(`It has ${selectedMemory.concept_link_count} concept link(s); provenance cleanup may fail silently on the server if concepts are shared with other memories.`);
    }
    const msg = ['Delete this memory?', ...warnings].join('\n\n');
    if (confirm(msg)) {
      deleteMemory.mutate(selectedMemory.id, {
        onSuccess: (result) => {
          setSelectedMemory(null);
          setActionNotice(deleteNotice(result, 'Memory deleted.'));
        },
        onError: (error) => setActionNotice({ kind: 'error', message: mutationErrorMessage(error) }),
      });
    }
  };

  return (
    <div className="space-y-4 h-full flex flex-col">
      <div className="flex gap-4 items-center shrink-0">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input 
            placeholder="Search memories..." 
            className="pl-9 bg-background"
            value={params.q || ''}
            onChange={e => setParams(p => ({ ...p, q: e.target.value || undefined }))}
          />
        </div>
        <Select value={params.session || "all"} onValueChange={v => setParams(p => ({ ...p, session: v === "all" ? undefined : v }))}>
          <SelectTrigger className="w-[180px] bg-background">
            <SelectValue placeholder="Session" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Sessions</SelectItem>
            {filters?.sessions.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={params.compaction_role || "all"} onValueChange={v => setParams(p => ({ ...p, compaction_role: v === "all" ? undefined : v as any }))}>
          <SelectTrigger className="w-[180px] bg-background">
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
          <Button variant="destructive" onClick={handleBulkDelete} isLoading={bulkDelete.isPending}>
            <Trash2 className="w-4 h-4 mr-2" /> Delete {selectedIds.size}
          </Button>
        ) : (
          <Button onClick={() => { setCreateMode(true); setEditContent(''); setNewSession(''); setNewProject(''); setNewPlatform(''); setNewContextType(''); }}>
            <Plus className="w-4 h-4 mr-2" /> New
          </Button>
        )}
      </div>
      <ActionNoticePanel notice={actionNotice} />

      <div className="border rounded-md bg-card flex-1 overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-muted/80 backdrop-blur">
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
              <TableRow><TableCell colSpan={4} className="h-24 text-center text-muted-foreground">No memories found</TableCell></TableRow>
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
            <ActionNoticePanel notice={updateMemory.error ? { kind: 'error', message: mutationErrorMessage(updateMemory.error) } : deleteMemory.error ? { kind: 'error', message: mutationErrorMessage(deleteMemory.error) } : null} />
          </div>
          <DialogFooter className="flex justify-between sm:justify-between items-center">
            <Button variant="destructive" onClick={handleDelete} isLoading={deleteMemory.isPending}>
              <Trash2 className="w-4 h-4 mr-2" /> Delete
            </Button>
            <Button variant="outline" onClick={() => setSelectedMemory(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
