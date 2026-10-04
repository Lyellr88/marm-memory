import { format } from 'date-fns';
import { decodeEntities } from '@/lib/entities';
import { Badge, Button, Input, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, Textarea } from '@/components/ui/core';
import { Trash2, Edit2 } from 'lucide-react';
import type { Memory } from '@/lib/marm-types';
import { mutationErrorMessage, ActionNoticePanel } from './shared';

type MemoryDetailsDialogProps = {
  open: boolean;
  selectedMemory: Memory | null;
  onClose: () => void;
  editMode: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  editContent: string;
  setEditContent: (value: string) => void;
  editProject: string;
  setEditProject: (value: string) => void;
  editPlatform: string;
  setEditPlatform: (value: string) => void;
  editContextType: string;
  setEditContextType: (value: string) => void;
  onSave: () => void;
  isSaving: boolean;
  relatedMemories: Memory[];
  onSelectRelated: (memory: Memory) => void;
  updateError: unknown;
  deleteError: unknown;
  onDelete: () => void;
  isDeleting: boolean;
};

export function MemoryDetailsDialog({ open, selectedMemory, onClose, editMode, onStartEdit, onCancelEdit, editContent, setEditContent, editProject, setEditProject, editPlatform, setEditPlatform, editContextType, setEditContextType, onSave, isSaving, relatedMemories, onSelectRelated, updateError, deleteError, onDelete, isDeleting }: MemoryDetailsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
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
                <Button variant="ghost" size="sm" className="h-6" onClick={onStartEdit}>
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
                  <Button variant="outline" size="sm" onClick={onCancelEdit}>Cancel</Button>
                  <Button size="sm" onClick={onSave} isLoading={isSaving}>Save</Button>
                </div>
              </div>
            ) : (
              <div className="p-4 bg-muted/30 rounded-md font-mono text-sm whitespace-pre-wrap">
                {decodeEntities(selectedMemory?.content)}
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
                    onClick={() => onSelectRelated(memory)}
                    className="group w-full rounded-lg border border-border/70 bg-background/40 p-3 text-left transition-[border-color,background-color,transform] duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:bg-primary/[0.035] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="line-clamp-2 text-xs leading-relaxed text-foreground/80 group-hover:text-foreground">{decodeEntities(memory.content)}</span>
                    <span className="mt-2 block font-mono text-[10px] text-muted-foreground">{memory.session_name}{memory.project ? ` · ${memory.project}` : ''}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          <ActionNoticePanel notice={updateError ? { kind: 'error', message: mutationErrorMessage(updateError) } : deleteError ? { kind: 'error', message: mutationErrorMessage(deleteError) } : null} />
        </div>
        <DialogFooter className="flex justify-between sm:justify-between items-center">
          <Button variant="destructive" onClick={onDelete} isLoading={isDeleting}>
            <Trash2 className="w-4 h-4 mr-2" /> Delete
          </Button>
          <Button variant="outline" onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
