import { useState, useEffect } from 'react';
import { useConcept, useDismissConceptDuplicate, useMergeConceptDuplicate, useRemoveConceptEntity } from '@/hooks/use-marm-queries';
import { Button, Badge, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/core';
import { Merge, ShieldX, Trash2 } from 'lucide-react';
import type { ConceptDetail, DuplicateCandidate } from '@/lib/marm-types';
import { decodeEntities } from '@/lib/entities';

type ReviewAction =
  | { kind: 'merge'; keep: 'a' | 'b' }
  | { kind: 'remove'; entity: 'a' | 'b' };

export function DuplicateReviewDialog({
  candidate,
  onOpenChange,
}: {
  candidate: DuplicateCandidate | null;
  onOpenChange: (open: boolean) => void;
}) {
  const entityA = useConcept(candidate?.entity_a.id || 0);
  const entityB = useConcept(candidate?.entity_b.id || 0);
  const dismiss = useDismissConceptDuplicate();
  const merge = useMergeConceptDuplicate();
  const remove = useRemoveConceptEntity();
  const [confirmation, setConfirmation] = useState<ReviewAction | null>(null);
  const [error, setError] = useState('');
  const pending = dismiss.isPending || merge.isPending || remove.isPending;

  useEffect(() => {
    setConfirmation(null);
    setError('');
  }, [candidate]);

  if (!candidate) return null;

  const pair = {
    entity_a_id: candidate.entity_a.id,
    entity_b_id: candidate.entity_b.id,
  };

  const closeAfter = async (operation: Promise<unknown>) => {
    setError('');
    try {
      await operation;
      setConfirmation(null);
      onOpenChange(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The review action failed.');
    }
  };

  const confirmAction = () => {
    if (!confirmation) return;
    if (confirmation.kind === 'merge') {
      void closeAfter(merge.mutateAsync({ ...pair, keep: confirmation.keep }));
      return;
    }
    const entityId = confirmation.entity === 'a' ? pair.entity_a_id : pair.entity_b_id;
    void closeAfter(remove.mutateAsync(entityId));
  };

  const confirmationName = confirmation?.kind === 'remove'
    ? (confirmation.entity === 'a' ? candidate.entity_a.name : candidate.entity_b.name)
    : confirmation?.kind === 'merge'
      ? (confirmation.keep === 'a' ? candidate.entity_a.name : candidate.entity_b.name)
      : '';

  return (
    <>
      <Dialog open onOpenChange={onOpenChange}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>Review Potential Duplicate</DialogTitle>
            <DialogDescription>
              {(candidate.similarity * 100).toFixed(1)}% name similarity in the same graph scope. Compare provenance before changing the graph.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 md:grid-cols-2">
            <ConceptCompareCard label="Concept A" entity={candidate.entity_a} detail={entityA.data} loading={entityA.isLoading} />
            <ConceptCompareCard label="Concept B" entity={candidate.entity_b} detail={entityB.data} loading={entityB.isLoading} />
          </div>
          {error && (
            <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
          <div className="rounded-lg border border-border/80 bg-muted/20 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <Merge className="h-4 w-4 text-primary" /> Merge concepts
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <Button variant="outline" disabled={pending} onClick={() => setConfirmation({ kind: 'merge', keep: 'a' })}>
                Keep “{candidate.entity_a.name}”
              </Button>
              <Button variant="outline" disabled={pending} onClick={() => setConfirmation({ kind: 'merge', keep: 'b' })}>
                Keep “{candidate.entity_b.name}”
              </Button>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">Sources, relationships, and code links move to the name you keep. Future builds reuse that choice.</p>
          </div>
          <DialogFooter className="flex-col gap-2 sm:flex-row sm:justify-between">
            <div className="flex flex-wrap gap-2">
              <Button variant="ghost" disabled={pending} onClick={() => void closeAfter(dismiss.mutateAsync(pair))}>
                <ShieldX className="mr-2 h-4 w-4" /> Not a duplicate
              </Button>
              <Button variant="ghost" className="text-destructive hover:text-destructive" disabled={pending} onClick={() => setConfirmation({ kind: 'remove', entity: 'a' })}>
                <Trash2 className="mr-2 h-4 w-4" /> Remove A
              </Button>
              <Button variant="ghost" className="text-destructive hover:text-destructive" disabled={pending} onClick={() => setConfirmation({ kind: 'remove', entity: 'b' })}>
                <Trash2 className="mr-2 h-4 w-4" /> Remove B
              </Button>
            </div>
            <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmation !== null} onOpenChange={(open) => !open && setConfirmation(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{confirmation?.kind === 'merge' ? 'Confirm merge' : 'Remove concept from graph?'}</DialogTitle>
            <DialogDescription>
              {confirmation?.kind === 'merge'
                ? `This keeps “${confirmationName}” as the canonical concept and removes the other graph node.`
                : `This removes “${confirmationName}” and suppresses it in this exact scope so automatic builds do not add it back.`}
            </DialogDescription>
          </DialogHeader>
          {confirmation?.kind === 'remove' && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              This is destructive graph cleanup. It does not delete the source memories.
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" disabled={pending} onClick={() => setConfirmation(null)}>Cancel</Button>
            <Button variant={confirmation?.kind === 'remove' ? 'destructive' : 'default'} isLoading={pending} onClick={confirmAction}>
              {confirmation?.kind === 'merge' ? 'Merge concepts' : 'Remove concept'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function ConceptCompareCard({ label, entity, detail, loading }: {
  label: string;
  entity: DuplicateCandidate['entity_a'];
  detail: ConceptDetail | undefined;
  loading: boolean;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-border/80 bg-card/70 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{label}</span>
        <Badge variant="outline">{entity.type}</Badge>
      </div>
      <div className="truncate font-mono text-base font-semibold" title={entity.name}>{entity.name}</div>
      <div className="mt-2 flex gap-4 text-xs text-muted-foreground">
        <span>{entity.mention_count} mentions</span>
        <span>{entity.degree} links</span>
      </div>
      <div className="mt-4 space-y-2">
        <div className="flex items-center justify-between gap-3 text-xs font-medium text-muted-foreground">
          <span>Source memories</span>
          {detail?.source_memories.length ? <span>{detail.source_memories.length} attached</span> : null}
        </div>
        {loading ? (
          <div className="flex h-48 items-center justify-center rounded border border-border/60 bg-background/40 text-xs text-muted-foreground">Loading provenance...</div>
        ) : detail?.source_memories.length ? (
          <div
            className="h-48 space-y-2 overflow-y-auto rounded border border-border/60 bg-background/30 p-2 pr-1 [scrollbar-gutter:stable] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
            role="region"
            aria-label={`${label} source memories`}
            tabIndex={0}
          >
            {detail.source_memories.map((memory, index) => (
              <article key={String(memory.id)} className="rounded border border-border/60 bg-background/70 p-3 text-xs leading-relaxed">
                <div className="mb-2 flex items-center justify-between gap-3 font-mono text-[10px] text-muted-foreground">
                  <span>Memory {index + 1}</span>
                  <span>{memory.session_name}</span>
                </div>
                <p className="whitespace-pre-wrap break-words text-foreground">{decodeEntities(memory.content)}</p>
              </article>
            ))}
          </div>
        ) : (
          <div className="flex h-48 items-center justify-center rounded border border-border/60 bg-background/40 text-xs text-muted-foreground">No source memories available.</div>
        )}
      </div>
    </div>
  );
}
