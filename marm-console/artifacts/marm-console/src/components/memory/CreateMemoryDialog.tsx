import { Button, Input, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, Textarea, Label } from '@/components/ui/core';
import type { Filters } from '@/lib/marm-types';
import { mutationErrorMessage, ActionNoticePanel } from './shared';

type CreateMemoryDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  filters: Filters | undefined;
  newSession: string;
  setNewSession: (value: string) => void;
  newProject: string;
  setNewProject: (value: string) => void;
  newPlatform: string;
  setNewPlatform: (value: string) => void;
  newContextType: string;
  setNewContextType: (value: string) => void;
  editContent: string;
  setEditContent: (value: string) => void;
  createError: unknown;
  isCreating: boolean;
  onCreate: () => void;
};

export function CreateMemoryDialog({ open, onOpenChange, filters, newSession, setNewSession, newProject, setNewProject, newPlatform, setNewPlatform, newContextType, setNewContextType, editContent, setEditContent, createError, isCreating, onCreate }: CreateMemoryDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
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
        <ActionNoticePanel notice={createError ? { kind: 'error', message: mutationErrorMessage(createError) } : null} />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={onCreate} isLoading={isCreating} disabled={!editContent || !newSession.trim()}>Create</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
