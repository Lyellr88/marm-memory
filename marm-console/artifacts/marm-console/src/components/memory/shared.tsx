import type { MemoryDeleteResult } from '@/lib/marm-types';
import { useEffect, useId, useState, type ReactNode } from 'react';
import { AlertTriangle, BrainCircuit, CheckCircle2, ChevronLeft, ChevronRight, CircleAlert, FileText, Lightbulb, MessageSquareText, Sparkles, Trash2, Wrench, XCircle } from 'lucide-react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from '@/components/ui/core';

export type ActionNotice = {
  kind: 'success' | 'warning' | 'error';
  message: string;
};

export function mutationErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'The memory action failed.';
}

export function deleteNotice(result: MemoryDeleteResult, fallback: string): ActionNotice {
  const cleanup = result.concept_cleanup;
  const deletedCount = result.deleted_ids?.length ?? 0;
  const missingCount = result.missing_ids?.length ?? 0;
  const base =
    deletedCount === 0
      ? 'No memories were deleted.'
      : deletedCount > 1
        ? `${deletedCount} memories deleted.`
        : fallback;
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
    kind: missingCount > 0 ? 'warning' : 'success',
    message: `${base}${missing}`,
  };
}

export function ActionNoticePanel({ notice }: { notice: ActionNotice | null }) {
  if (!notice) return null;
  const styles = {
    success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200',
    warning: 'border-amber-500/30 bg-amber-500/10 text-amber-100',
    error: 'border-destructive/30 bg-destructive/10 text-destructive',
  };
  const Icon = notice.kind === 'success' ? CheckCircle2 : XCircle;
  return (
    <div
      role={notice.kind === 'error' ? 'alert' : 'status'}
      aria-live={notice.kind === 'error' ? 'assertive' : 'polite'}
      className={`success-pop flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${styles[notice.kind]}`}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{notice.message}</span>
    </div>
  );
}

export function MemoryEmptyState({
  title,
  detail,
  className = '',
  children,
}: {
  title: string;
  detail?: string;
  className?: string;
  /** Optional call to action. Empty states that can be acted on directly are
   *  better than empty states that describe an action taken elsewhere. */
  children?: ReactNode;
}) {
  return (
    <div className={`memory-empty-state relative flex min-h-40 flex-col items-center justify-center overflow-hidden rounded-xl ${className}`}>
      <div className="memory-empty-field" aria-hidden="true" />
      <div className="relative z-10 flex h-11 w-11 items-center justify-center rounded-xl border border-primary/20 bg-primary/[0.07] text-primary shadow-[0_0_28px_rgba(var(--primary-rgb),0.08)]">
        <Sparkles className="h-4.5 w-4.5" />
      </div>
      <p className="relative z-10 mt-3 text-sm font-medium text-foreground/90">{title}</p>
      {detail && <p className="relative z-10 mt-1 max-w-sm text-center text-xs text-muted-foreground">{detail}</p>}
      {children && <div className="relative z-10">{children}</div>}
    </div>
  );
}

export function PageControls({
  page,
  pageSize,
  total,
  itemLabel,
  onPageChange,
  isFetching = false,
}: {
  page: number;
  pageSize: number;
  total: number;
  itemLabel: string;
  onPageChange: (page: number) => void;
  isFetching?: boolean;
}) {
  const rangeStart = total === 0 ? 0 : page * pageSize + 1;
  const rangeEnd = Math.min((page + 1) * pageSize, total);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="flex flex-col gap-3 border-t border-border/70 px-4 py-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-6">
      <span>Showing {rangeStart}–{rangeEnd} of {total} {itemLabel}</span>
      <div className="flex shrink-0 items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={page === 0 || isFetching}
          onClick={() => onPageChange(page - 1)}
          aria-label={`Previous ${itemLabel}`}
        >
          <ChevronLeft className="mr-1 h-4 w-4" /> Previous
        </Button>
        <span className="min-w-24 text-center font-mono text-foreground">
          Page {page + 1} of {pageCount}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={page + 1 >= pageCount || isFetching}
          onClick={() => onPageChange(page + 1)}
          aria-label={`Next ${itemLabel}`}
        >
          Next <ChevronRight className="ml-1 h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

export function DeleteSelectionDialog({
  open,
  onOpenChange,
  count,
  itemLabel,
  description,
  isPending,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  count: number;
  itemLabel: string;
  description: string;
  isPending: boolean;
  onConfirm: () => void;
}) {
  const [confirmation, setConfirmation] = useState('');
  const confirmationId = useId();

  useEffect(() => {
    if (open) setConfirmation('');
  }, [open]);

  const close = (nextOpen: boolean) => {
    if (!isPending) onOpenChange(nextOpen);
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <div className="mb-2 flex h-11 w-11 items-center justify-center rounded-xl border border-destructive/30 bg-destructive/10 text-destructive">
            <AlertTriangle className="h-5 w-5" />
          </div>
          <DialogTitle>Delete {count} {itemLabel}{count === 1 ? '' : 's'}?</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2 py-2">
          <Label htmlFor={confirmationId} className="text-xs text-muted-foreground">
            Type <span className="font-mono font-semibold text-foreground">DELETE</span> to confirm.
          </Label>
          <Input
            id={confirmationId}
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            autoComplete="off"
            className="border-destructive/30 font-mono uppercase focus-visible:ring-destructive"
            autoFocus
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)} disabled={isPending}>Cancel</Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={confirmation !== 'DELETE'}
            isLoading={isPending}
          >
            <Trash2 className="mr-2 h-4 w-4" /> Delete permanently
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** How a memory's context_type is coloured and iconified.
 *
 *  Lives here, not in MemoriesTab, because Code Context shows the same memory
 *  records. The concept-graph palette in knowledge/shared.tsx is a different
 *  vocabulary for a different thing -- it colours graph ENTITY types, where
 *  `decision` is violet. Using it for a memory would render the same record
 *  amber on /memory and violet on /code-context.
 */
export function memoryContext(contextType: string | null) {
  const value = (contextType || 'general').toLowerCase();
  if (value.includes('decision')) return { icon: Lightbulb, tone: 'text-amber-300 border-amber-400/20 bg-amber-400/[0.06]', rail: 'border-l-amber-400/70' };
  if (value.includes('error') || value.includes('issue')) return { icon: CircleAlert, tone: 'text-red-300 border-red-400/20 bg-red-400/[0.06]', rail: 'border-l-red-400/70' };
  if (value.includes('doc') || value.includes('book') || value.includes('handbook')) return { icon: FileText, tone: 'text-violet-300 border-violet-400/20 bg-violet-400/[0.06]', rail: 'border-l-violet-400/70' };
  if (value.includes('code') || value.includes('project') || value.includes('tool')) return { icon: Wrench, tone: 'text-blue-300 border-blue-400/20 bg-blue-400/[0.06]', rail: 'border-l-blue-400/70' };
  if (value.includes('concept') || value.includes('pattern')) return { icon: BrainCircuit, tone: 'text-teal-300 border-teal-400/20 bg-teal-400/[0.06]', rail: 'border-l-teal-400/70' };
  return { icon: MessageSquareText, tone: 'text-primary border-primary/20 bg-primary/[0.06]', rail: 'border-l-primary/70' };
}
