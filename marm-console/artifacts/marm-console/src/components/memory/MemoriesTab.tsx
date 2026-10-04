import { useState, useEffect } from 'react';
import { decodeEntities } from '@/lib/entities';
import { useMemories, useFilters, useOverview, useCreateMemory, useUpdateMemory, useDeleteMemory, useBulkDeleteMemories } from '@/hooks/use-marm-queries';
import { Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from '@/components/ui/core';
import type { Memory, MemoryId, MemoryListParams } from '@/lib/marm-types';
import { type ActionNotice, mutationErrorMessage, deleteNotice, ActionNoticePanel, DeleteSelectionDialog, MemoryEmptyState, PageControls } from './shared';
import { MemoryRow } from './MemoryRow';
import { MemoryToolbar } from './MemoryToolbar';
import { CreateMemoryDialog } from './CreateMemoryDialog';
import { MemoryDetailsDialog } from './MemoryDetailsDialog';

const MEMORY_PAGE_SIZE = 100;

export function MemoriesTab() {
  const [params, setParams] = useState<MemoryListParams>({ limit: MEMORY_PAGE_SIZE, offset: 0 });
  const { data: filters } = useFilters();
  // Scope to ONE project by default, chosen once the filter list arrives.
  // Loading every project was the previous behaviour and is still available,
  // but it is the expensive option and should be asked for rather than
  // happened upon: recall and listing both scale with how many rows are in
  // scope, and distillation makes rows cheaper to create than ever.
  const [scopedAll, setScopedAll] = useState(false);
  const { data: overview } = useOverview();
  // Hold the first request until the scope is settled. The default-project
  // effect below cannot influence the render that would already have started an
  // all-project listing, and that listing is the expensive one -- it scales with
  // every row in the store, which is exactly what scoping exists to avoid.
  // `!!filters` was not enough: filters arriving is what lets the effect below
  // pick a default, so between those two renders the scope is still unset and
  // the query would fire unscoped anyway. The gate needs an actual scope --
  // or proof that none exists, which is filters with no projects in it.
  const scopeSettled =
    scopedAll || !!params.project || (!!filters && !filters.projects?.length);
  const { data, isLoading, isFetching } = useMemories(params, scopeSettled);
  useEffect(() => {
    if (scopedAll || params.project || !filters?.projects?.length) return;
    setParams(prev => ({ ...prev, project: filters.projects[0], offset: 0 }));
  }, [filters, params.project, scopedAll]);
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

  useEffect(() => {
    if (!data || !params.offset || params.offset < data.total) return;
    setParams((previous) => ({
      ...previous,
      offset: Math.max(0, Math.floor((data.total - 1) / MEMORY_PAGE_SIZE) * MEMORY_PAGE_SIZE),
    }));
  }, [data, params.offset]);

  const updateFilters = (updates: Partial<MemoryListParams>) => {
    setParams((previous) => ({ ...previous, ...updates, limit: MEMORY_PAGE_SIZE, offset: 0 }));
  };

  const currentPage = Math.floor((data?.offset ?? params.offset ?? 0) / MEMORY_PAGE_SIZE);

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
      // Keep the server's escaped row, not the decoded editor text: decoding
      // must happen once. A bare `{id}` response must not replace a whole row.
      onSuccess: (updated) => {
        setEditMode(false);
        if (typeof updated?.content === 'string') {
          setSelectedMemory(updated);
          setActionNotice({ kind: 'success', message: 'Memory updated.' });
          return;
        }
        // The row could not be read back -- the write landed, but there is
        // nothing to show. Close rather than leave the pre-edit content on
        // screen looking like the saved result.
        setSelectedMemory(null);
        setActionNotice({ kind: 'success', message: 'Memory updated, but it could not be read back.' });
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

  const startCreate = () => {
    setCreateMode(true);
    setEditContent('');
    setNewSession('');
    setNewProject('');
    setNewPlatform('');
    setNewContextType('');
  };

  const startEdit = () => {
    setEditMode(true);
    setEditContent(decodeEntities(selectedMemory?.content));
    setEditProject(selectedMemory?.project || '');
    setEditPlatform(selectedMemory?.platform || '');
    setEditContextType(selectedMemory?.context_type || '');
  };

  return (
    <div className="flex h-full flex-col gap-4">
      <MemoryToolbar
        params={params}
        filters={filters}
        selectedCount={selectedIds.size}
        bulkPending={bulkDelete.isPending}
        updateFilters={updateFilters}
        setScopedAll={setScopedAll}
        onBulkDelete={requestBulkDelete}
        onNew={startCreate}
      />
      <ActionNoticePanel notice={actionNotice} />

      <div className="min-h-0 flex flex-1 flex-col overflow-hidden rounded-xl border border-card-border border-t-primary/35 shadow-[0_18px_50px_rgba(0,0,0,0.16)]">
        <div className="min-h-0 flex-1 overflow-auto">
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
        {data && (
          <>
            {/* Scoping must never hide rows quietly. If the store holds more
                than this scope does, the page says so and offers the way out.
                The same principle the recall scan-truncation note follows:
                showing less is fine, showing less without saying so is not. */}
            {params.project && typeof overview?.memory.active_memories === 'number'
              && overview.memory.active_memories > data.total && (
              <p className="px-1 pt-2 text-[11px] text-muted-foreground">
                Scoped to <span className="font-mono text-foreground/80">{params.project}</span> —{' '}
                {data.total.toLocaleString()} of {overview.memory.active_memories.toLocaleString()} stored
                memories.{' '}
                <button
                  type="button"
                  className="underline underline-offset-2 hover:text-foreground/80"
                  onClick={() => {
                    setScopedAll(true);
                    updateFilters({ project: undefined });
                  }}
                >
                  Show all projects
                </button>
                .
              </p>
            )}
            <PageControls
              page={currentPage}
              pageSize={MEMORY_PAGE_SIZE}
              total={data.total}
              itemLabel="memories"
              isFetching={isFetching}
              onPageChange={(page) => setParams((previous) => ({ ...previous, offset: page * MEMORY_PAGE_SIZE }))}
            />
          </>
        )}
      </div>

      <CreateMemoryDialog
        open={createMode}
        onOpenChange={setCreateMode}
        filters={filters}
        newSession={newSession}
        setNewSession={setNewSession}
        newProject={newProject}
        setNewProject={setNewProject}
        newPlatform={newPlatform}
        setNewPlatform={setNewPlatform}
        newContextType={newContextType}
        setNewContextType={setNewContextType}
        editContent={editContent}
        setEditContent={setEditContent}
        createError={createMemory.error}
        isCreating={createMemory.isPending}
        onCreate={handleCreate}
      />

      <MemoryDetailsDialog
        open={!!selectedMemory && !createMode}
        selectedMemory={selectedMemory}
        onClose={() => setSelectedMemory(null)}
        editMode={editMode}
        onStartEdit={startEdit}
        onCancelEdit={() => setEditMode(false)}
        editContent={editContent}
        setEditContent={setEditContent}
        editProject={editProject}
        setEditProject={setEditProject}
        editPlatform={editPlatform}
        setEditPlatform={setEditPlatform}
        editContextType={editContextType}
        setEditContextType={setEditContextType}
        onSave={handleUpdate}
        isSaving={updateMemory.isPending}
        relatedMemories={relatedMemories}
        onSelectRelated={(memory) => { setSelectedMemory(memory); setEditMode(false); }}
        updateError={updateMemory.error}
        deleteError={deleteMemory.error}
        onDelete={requestSingleDelete}
        isDeleting={deleteMemory.isPending}
      />
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
