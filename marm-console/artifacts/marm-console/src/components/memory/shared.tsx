import type { MemoryDeleteResult } from '@/lib/marm-types';
import { CheckCircle2, XCircle } from 'lucide-react';

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

export function ActionNoticePanel({ notice }: { notice: ActionNotice | null }) {
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
