import { useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useMemories, useSessions, useLogs, useCompaction, useNotebook, useUpsertNotebook, useDeleteNotebook, useRunCompactionAction, useFilters, useCreateMemory, useUpdateMemory, useDeleteMemory, useBulkDeleteMemories, useSummary, useCreateSession, useDeleteSession, useDeleteAllSessions, useDeleteLog, useDeleteAllLogs } from '@/hooks/use-marm-queries';
import { Tabs, TabsList, TabsTrigger, TabsContent, Card, CardContent, CardHeader, CardTitle, CardDescription, Badge, Button, Input, Select, SelectTrigger, SelectValue, SelectContent, SelectItem, Table, TableHeader, TableRow, TableHead, TableBody, TableCell, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, Textarea, Label } from '@/components/ui/core';
import { format } from 'date-fns';
import { Search, Trash2, CheckCircle2, XCircle, Eye, RefreshCw, Plus, Save, Edit2 } from 'lucide-react';
import type { Memory, MemoryDeleteResult, MemoryId, MemoryListParams, LogListParams, NotebookEntry } from '@/lib/marm-types';

type ActionNotice = {
  kind: 'success' | 'warning' | 'error';
  message: string;
};

function mutationErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'The memory action failed.';
}

function deleteNotice(result: MemoryDeleteResult, fallback: string): ActionNotice {
  const cleanup = result.concept_cleanup;
  const deletedCount = result.deleted_ids?.length ?? 0;
  const missingCount = result.missing_ids?.length ?? 0;
  const base = deletedCount > 1 ? `${deletedCount} memories deleted.` : fallback;
  const missing = missingCount ? ` ${missingCount} requested ID(s) were not found.` : '';

  if (cleanup?.status === 'failed') {
    return {
      kind: 'warning',
      message: `${base}${missing} Concept graph cleanup failed: ${cleanup.error || 'graph repair may be needed.'}`,
    };
  }
  if (cleanup?.status === 'skipped') {
    return {
      kind: 'warning',
      message: `${base}${missing} Concept graph cleanup was skipped${cleanup.reason ? `: ${cleanup.reason}` : '.'}`,
    };
  }
  return {
    kind: 'success',
    message: `${base}${missing}`,
  };
}

function ActionNoticePanel({ notice }: { notice: ActionNotice | null }) {
  if (!notice) return null;
  const styles = {
    success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200',
    warning: 'border-amber-500/30 bg-amber-500/10 text-amber-100',
    error: 'border-destructive/30 bg-destructive/10 text-destructive',
  };
  const Icon = notice.kind === 'success' ? CheckCircle2 : XCircle;
  return (
    <div className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${styles[notice.kind]}`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{notice.message}</span>
    </div>
  );
}

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

function MemoriesTab() {
  const [params, setParams] = useState<MemoryListParams>({ limit: 50 });
  const { data, isLoading } = useMemories(params);
  const { data: filters } = useFilters();
  const [selectedMemory, setSelectedMemory] = useState<Memory | null>(null);
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  
  const [selectedIds, setSelectedIds] = useState<Set<MemoryId>>(new Set());
  const bulkDelete = useBulkDeleteMemories();
  
  const toggleSelect = (id: MemoryId) => {
    const newSet = new Set(selectedIds);
    if (newSet.has(id)) newSet.delete(id);
    else newSet.add(id);
    setSelectedIds(newSet);
  };
  
  const toggleAll = () => {
    if (selectedIds.size === data?.items.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(data?.items.map(m => m.id)));
    }
  };

  const handleBulkDelete = () => {
    if (selectedIds.size === 0) return;
    const typed = prompt(`Type DELETE to delete ${selectedIds.size} selected memories.`);
    if (typed === 'DELETE') {
      bulkDelete.mutate(Array.from(selectedIds), {
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
    updateMemory.mutate({
      id: selectedMemory.id,
      data: {
        content: editContent,
        session_name: selectedMemory.session_name,
        project: editProject.trim() || null,
        platform: editPlatform.trim() || null,
        context_type: editContextType.trim() || selectedMemory.context_type || 'general',
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
          context_type: editContextType.trim() || null,
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
                  checked={
                    !!data?.items.length && selectedIds.size === data.items.length
                  }
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
                    <Input placeholder="Context type (blank = null)" value={editContextType} onChange={e => setEditContextType(e.target.value)} className="text-xs" />
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

function SessionSummaryDialog({ session, open, onOpenChange }: { session: string | null, open: boolean, onOpenChange: (o: boolean) => void }) {
  const { data, isLoading, isFetching, refetch } = useSummary(session || '');

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="font-mono">{session}</DialogTitle>
          <DialogDescription>Rolling session summary maintained by the MARM server.</DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <div className="p-8 text-center text-muted-foreground">Loading summary...</div>
        ) : (
          <div className="flex-1 overflow-auto space-y-4">
            <div className="flex items-center gap-2 flex-wrap">
              <Badge variant={data?.is_dirty ? 'secondary' : 'default'} className="text-[10px] uppercase">
                {data?.is_dirty ? 'Stale — recompute pending' : 'Fresh'}
              </Badge>
              <span className="text-xs text-muted-foreground">{data?.entry_count} entries summarized</span>
              {data?.generated_at && (
                <span className="text-xs text-muted-foreground">· generated {format(new Date(data.generated_at), 'MMM d, HH:mm')}</span>
              )}
            </div>
            <div className="p-4 bg-muted/30 rounded-md text-sm whitespace-pre-wrap font-mono">
              {data?.summary || 'No summary generated yet.'}
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          <Button onClick={() => refetch()} isLoading={isFetching}>
            <RefreshCw className="w-4 h-4 mr-2" /> Regenerate
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SessionsTab() {
  const { data, isLoading } = useSessions();
  const [summarySession, setSummarySession] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const createSession = useCreateSession();
  const deleteSession = useDeleteSession();
  const deleteAllSessions = useDeleteAllSessions();

  const handleCreateSession = () => {
    const name = prompt('Session name');
    if (!name?.trim()) return;
    createSession.mutate(name.trim(), {
      onSuccess: () => setActionNotice({ kind: 'success', message: `Session '${name.trim()}' created.` }),
    });
  };

  const handleDeleteSession = (name: string) => {
    const typed = prompt(`Type DELETE to delete session '${name}' and its log-backed memories.`);
    if (typed !== 'DELETE') return;
    deleteSession.mutate(name, {
      onSuccess: (result) => {
        setActionNotice({
          kind: 'success',
          message: `Session '${name}' deleted. ${result.deleted_count} log entries and ${result.memories_deleted} semantic log memories removed.`,
        });
      },
    });
  };

  const handleDeleteAllSessions = () => {
    const typed = prompt('Type DELETE_ALL to delete every session and its log-backed memories.');
    if (typed !== 'DELETE_ALL') return;
    deleteAllSessions.mutate(undefined, {
      onSuccess: (result) => {
        setActionNotice({
          kind: 'success',
          message: `${result.deleted_sessions} sessions deleted. ${result.deleted_count} log entries and ${result.memories_deleted} semantic log memories removed.`,
        });
      },
    });
  };
  
  if (isLoading) return <div className="p-8 text-center text-muted-foreground">Loading sessions...</div>;

  return (
    <div className="h-full overflow-auto pb-4 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <ActionNoticePanel
          notice={
            createSession.error
              ? { kind: 'error', message: mutationErrorMessage(createSession.error) }
              : deleteSession.error
                ? { kind: 'error', message: mutationErrorMessage(deleteSession.error) }
                : deleteAllSessions.error
                  ? { kind: 'error', message: mutationErrorMessage(deleteAllSessions.error) }
                : actionNotice
          }
        />
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            className="text-destructive hover:text-destructive"
            onClick={handleDeleteAllSessions}
            isLoading={deleteAllSessions.isPending}
          >
            <Trash2 className="w-4 h-4 mr-2" /> Delete All
          </Button>
          <Button size="sm" onClick={handleCreateSession} isLoading={createSession.isPending}>
            <Plus className="w-4 h-4 mr-2" /> New Session
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 content-start">
        {data?.map(session => (
          <Card key={session.name} className={session.active ? 'border-primary' : ''}>
          <CardHeader className="pb-2">
            <div className="flex justify-between items-start">
              <CardTitle className="font-mono text-base">{session.name}</CardTitle>
              {session.active && <Badge className="text-[10px]">Active</Badge>}
            </div>
            <CardDescription className="text-xs">
              Last active: {format(new Date(session.last_accessed_at), 'MMM d, HH:mm')}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-2 text-sm mt-2">
              <div className="p-2 bg-muted/30 rounded flex flex-col items-center justify-center">
                <span className="text-xl font-bold">{session.memory_count}</span>
                <span className="text-xs text-muted-foreground">Memories</span>
              </div>
              <div className="p-2 bg-muted/30 rounded flex flex-col items-center justify-center">
                <span className="text-xl font-bold">{session.compaction_count}</span>
                <span className="text-xs text-muted-foreground">Compactions</span>
              </div>
            </div>
            {session.projects.length > 0 && (
              <div className="mt-4">
                <div className="text-xs text-muted-foreground mb-1">Projects</div>
                <div className="flex flex-wrap gap-1">
                  {session.projects.map(p => <Badge key={p} variant="secondary" className="text-[10px]">{p}</Badge>)}
                </div>
              </div>
            )}
            <div className="grid grid-cols-2 gap-2 mt-4">
              <Button variant="outline" size="sm" onClick={() => setSummarySession(session.name)}>
                <Eye className="w-4 h-4 mr-2" /> Summary
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive"
                onClick={() => handleDeleteSession(session.name)}
                isLoading={deleteSession.isPending}
              >
                <Trash2 className="w-4 h-4 mr-2" /> Delete
              </Button>
            </div>
          </CardContent>
          </Card>
        ))}
      </div>
      <SessionSummaryDialog session={summarySession} open={!!summarySession} onOpenChange={(o) => !o && setSummarySession(null)} />
    </div>
  );
}

function LogsTab() {
  const [params, setParams] = useState<LogListParams>({ limit: 50 });
  const { data, isLoading } = useLogs(params);
  const { data: filters } = useFilters();
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const deleteLog = useDeleteLog();
  const deleteAllLogs = useDeleteAllLogs();

  const handleDeleteLog = (id: number, sessionName: string) => {
    const typed = prompt(`Type DELETE to delete log entry ${id}.`);
    if (typed !== 'DELETE') return;
    deleteLog.mutate({ id, sessionName }, {
      onSuccess: (result) => {
        setActionNotice({
          kind: 'success',
          message: `Log ${result.log_id} deleted. ${result.memories_deleted} semantic log memories removed.`,
        });
      },
    });
  };

  const handleDeleteAllLogs = () => {
    const typed = prompt('Type DELETE_ALL to delete every log entry.');
    if (typed !== 'DELETE_ALL') return;
    deleteAllLogs.mutate(undefined, {
      onSuccess: (result) => {
        setActionNotice({
          kind: 'success',
          message: `${result.deleted_count} log entries deleted. ${result.memories_deleted} semantic log memories removed.`,
        });
      },
    });
  };

  return (
    <div className="space-y-4 h-full flex flex-col">
      <ActionNoticePanel
        notice={
          deleteLog.error
            ? { kind: 'error', message: mutationErrorMessage(deleteLog.error) }
            : deleteAllLogs.error
              ? { kind: 'error', message: mutationErrorMessage(deleteAllLogs.error) }
              : actionNotice
        }
      />
      <div className="flex gap-4 items-center shrink-0">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input 
            placeholder="Search logs..." 
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
        <Button
          variant="outline"
          className="text-destructive hover:text-destructive"
          onClick={handleDeleteAllLogs}
          isLoading={deleteAllLogs.isPending}
        >
          <Trash2 className="w-4 h-4 mr-2" /> Delete All
        </Button>
      </div>

      <div className="border rounded-md bg-card flex-1 overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-muted/80 backdrop-blur">
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Topic / Context</TableHead>
              <TableHead>Summary</TableHead>
              <TableHead className="w-[80px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow><TableCell colSpan={4} className="h-24 text-center text-muted-foreground">Loading logs...</TableCell></TableRow>
            ) : data?.length === 0 ? (
              <TableRow><TableCell colSpan={4} className="h-24 text-center text-muted-foreground">No logs found</TableCell></TableRow>
            ) : (
              data?.map(l => (
                <TableRow key={l.id}>
                  <TableCell className="w-[100px] font-mono text-xs text-muted-foreground">{format(new Date(l.date), 'MMM d, HH:mm')}</TableCell>
                  <TableCell>
                    <div className="flex gap-2 mb-1">
                      <Badge variant="outline" className="text-[10px] py-0">{l.session_name}</Badge>
                      {l.topic && <Badge variant="secondary" className="text-[10px] py-0">{l.topic}</Badge>}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm line-clamp-2">{l.summary || l.entry}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={() => handleDeleteLog(l.id, l.session_name)}
                      isLoading={deleteLog.isPending}
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function NotebookTab() {
  const { data, isLoading } = useNotebook();
  const upsert = useUpsertNotebook();
  const deleteNote = useDeleteNotebook();
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  
  const [editing, setEditing] = useState<NotebookEntry | Partial<NotebookEntry> | null>(null);

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
      }
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
      <ActionNoticePanel
        notice={
          upsert.error
            ? { kind: 'error', message: mutationErrorMessage(upsert.error) }
            : deleteNote.error
              ? { kind: 'error', message: mutationErrorMessage(deleteNote.error) }
              : actionNotice
        }
      />

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
                />
                <Input 
                  placeholder="Project (optional)" 
                  value={editing.project || ''} 
                  onChange={e => setEditing(p => ({ ...p!, project: e.target.value }))}
                  className="w-40 font-mono"
                />
                <Input
                  placeholder="Platform (optional)"
                  value={editing.platform || ''}
                  onChange={e => setEditing(p => ({ ...p!, platform: e.target.value }))}
                  className="w-40 font-mono"
                />
              </div>
              <p className="text-xs text-muted-foreground -mt-2">
                Entries are keyed by name + project + platform, so the same name can exist in different scopes.
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
                    onClick={() => deleteNote.mutate(
                      { name: editing.name!, params: { project: editing.project || undefined, platform: editing.platform || undefined } },
                      {
                        onSuccess: () => {
                          setActionNotice({ kind: 'success', message: `Notebook entry '${editing.name}' deleted.` });
                          setEditing(null);
                        },
                      },
                    )}
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

function CompactionTab() {
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
      <ActionNoticePanel
        notice={runAction.error ? { kind: 'error', message: mutationErrorMessage(runAction.error) } : actionNotice}
      />

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


export function MemoryPage() {
  return (
    <div className="p-8 flex flex-col h-full overflow-hidden">
      <div className="mb-8 shrink-0">
        <h1 className="text-2xl font-bold tracking-tight">Memory Management</h1>
        <p className="text-muted-foreground text-sm mt-1">Raw context, sessions, logs, and summarization</p>
      </div>

      <Tabs defaultValue="memories" className="flex-1 flex flex-col overflow-hidden">
        <TabsList className="self-start shrink-0 mb-4 bg-transparent border-b rounded-none w-full justify-start p-0 h-auto">
          <TabsTrigger value="memories" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none py-3 px-6">
            Raw Memories
          </TabsTrigger>
          <TabsTrigger value="sessions" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none py-3 px-6">
            Sessions
          </TabsTrigger>
          <TabsTrigger value="logs" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none py-3 px-6">
            Logs
          </TabsTrigger>
          <TabsTrigger value="notebook" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none py-3 px-6">
            Notebook
          </TabsTrigger>
          <TabsTrigger value="compaction" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none py-3 px-6">
            Compaction
          </TabsTrigger>
        </TabsList>
        
        <div className="flex-1 overflow-hidden min-h-0">
          <TabsContent value="memories" className="m-0 h-full">
            <MemoriesTab />
          </TabsContent>
          <TabsContent value="sessions" className="m-0 h-full">
            <SessionsTab />
          </TabsContent>
          <TabsContent value="logs" className="m-0 h-full">
            <LogsTab />
          </TabsContent>
          <TabsContent value="notebook" className="m-0 h-full">
            <NotebookTab />
          </TabsContent>
          <TabsContent value="compaction" className="m-0 h-full">
            <CompactionTab />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
