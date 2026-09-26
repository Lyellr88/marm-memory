import { useState } from 'react';
import { Badge, Button, cn } from '@/components/ui/core';
import { Check, ChevronDown, ChevronRight, GitCompareArrows, Quote, Trash2, Wand2 } from 'lucide-react';
import type { DistillProposal } from '@/lib/marm-types';
import { CopyButton } from '@/components/code-context/shared';
import { VerificationPanel } from '@/components/code-context/VerificationPanel';
import { memoryContext } from '@/components/memory/shared';

/** Verdict drives the whole card, so it gets the colour vocabulary the rest of
 *  the Console already uses for severity: emerald means act, amber means look,
 *  muted means nothing to do. */
const VERDICTS = {
  new: {
    tone: 'border-emerald-400/30 bg-emerald-400/[0.06] text-emerald-200',
    rail: 'border-l-emerald-400/70',
    label: 'new',
    hint: 'Nothing in the store is close to this.',
  },
  near: {
    tone: 'border-amber-400/30 bg-amber-400/[0.06] text-amber-200',
    rail: 'border-l-amber-400/70',
    label: 'near',
    hint: 'Close to an existing memory. An encoder cannot tell whether this refines it or contradicts it — that judgement is yours.',
  },
  duplicate: {
    tone: 'border-border/70 bg-muted/30 text-muted-foreground',
    rail: 'border-l-muted-foreground/40',
    label: 'duplicate',
    hint: 'Already recorded. Applying it would add nothing.',
  },
} as const;

export function VerdictBadge({ verdict, cosine }: { verdict: DistillProposal['verdict']; cosine: number }) {
  const meta = VERDICTS[verdict] ?? VERDICTS.new;
  return (
    <Badge variant="outline" className={cn('font-mono text-[10px] uppercase', meta.tone)} title={meta.hint}>
      {meta.label}
      {verdict !== 'new' && <span className="ml-1.5 tabular-nums opacity-80">{cosine.toFixed(3)}</span>}
    </Badge>
  );
}

/** The score is a sum of named parts, and the reviewer is being asked to trust
 *  it, so the parts are shown rather than the total alone. This is the same
 *  argument the Symbols pane makes for exposing provenance: a retrieval UI is
 *  judged on whether it shows *why*. */
function Reasons({ reasons }: { reasons: string[] }) {
  if (!reasons?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {reasons.map((reason) => (
        <Badge
          key={reason}
          variant="outline"
          className={cn(
            'text-[10px] font-normal',
            reason.startsWith('subject is') || reason === 'conversational' || reason === 'hedged'
              ? 'border-destructive/25 text-destructive/80'
              : 'text-muted-foreground',
          )}
        >
          {reason}
        </Badge>
      ))}
    </div>
  );
}

export function ProposalCard({
  proposal,
  onApply,
  onDiscard,
  busy = false,
  delay = 0,
}: {
  proposal: DistillProposal;
  onApply?: (id: string) => void;
  onDiscard?: (id: string) => void;
  busy?: boolean;
  delay?: number;
}) {
  const [showEvidence, setShowEvidence] = useState(false);
  const meta = VERDICTS[proposal.verdict] ?? VERDICTS.new;
  // Coloured by the same helper the Memory page uses, so a `decision` is amber
  // in both places. A second colour vocabulary for one concept is how a
  // consistency pass introduces an inconsistency.
  const context = memoryContext(proposal.context_type ?? null);
  const ContextIcon = context.icon;
  // A proposal with no id was never staged -- a duplicate, or one already
  // reviewed. Showing apply/discard on it would offer an action that cannot
  // run, so the card renders as a record instead of a decision.
  // Per-handler, not either-or: a caller supplying only one of them would
  // otherwise get an enabled button whose click does nothing.
  const canApply = Boolean(proposal.id && onApply);
  const canDiscard = Boolean(proposal.id && onDiscard);
  const actionable = canApply || canDiscard;

  return (
    <article
      className={cn(
        'metric-enter rounded-xl border border-l-2 border-border/80 bg-card/45 p-4 transition-transform duration-200 hover:-translate-y-px',
        meta.rail,
      )}
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <VerdictBadge verdict={proposal.verdict} cosine={proposal.cosine} />
        {proposal.context_type && (
          <Badge variant="outline" className={cn('text-[10px]', context.tone)}>
            <ContextIcon className="mr-1 h-3 w-3" />
            {proposal.context_type}
          </Badge>
        )}
        {proposal.origin === 'analyst' && (
          <Badge
            variant="outline"
            className="border-cyan-400/40 text-[10px] text-cyan-200"
            title="Staged by the Code Context analyst from a verified answer"
          >
            Analyst
          </Badge>
        )}
        {proposal.mode === 'generated' && (
          <Badge
            variant="outline"
            className="border-primary/30 text-[10px] text-primary-highlight"
            title="Rewritten to stand alone by the local model, then checked against the transcript it came from"
          >
            <Wand2 className="mr-1 h-3 w-3" />
            written
          </Badge>
        )}
        <span
          className="font-mono text-[11px] tabular-nums text-muted-foreground"
          title="Shape score: how strongly this reads like a durable fact"
        >
          {proposal.score >= 0 ? '+' : ''}
          {proposal.score.toFixed(2)}
        </span>
        {proposal.session_name && (
          <Badge variant="outline" className="font-mono text-[10px]">
            {proposal.session_name}
          </Badge>
        )}
        {proposal.project && (
          <Badge variant="outline" className="font-mono text-[10px]">
            {proposal.project}
          </Badge>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          <CopyButton className="h-7 w-7" value={proposal.content} label="Copy this proposal" />
        </div>
      </div>

      <p className="text-sm leading-relaxed text-foreground/95">{proposal.content}</p>

      <div className="mt-3">
        <Reasons reasons={proposal.reasons} />
      </div>

      {proposal.verification && (
        <div className="mt-3">
          <VerificationPanel verification={proposal.verification} />
        </div>
      )}

      {proposal.decision && (
        <p className="mt-3 text-[11px] text-muted-foreground">
          Guardrails: {proposal.decision.reason}
        </p>
      )}

      {proposal.evidence && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowEvidence((prev) => !prev)}
            aria-expanded={showEvidence}
            className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground transition-colors hover:text-foreground/80"
          >
            {showEvidence ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            <Quote className="h-3 w-3" />
            {proposal.origin === 'analyst' ? 'The source it cites' : 'What was actually said'}
          </button>
          {showEvidence && (
            <blockquote
              className={cn(
                'mt-2 border-l-2 border-primary/30 bg-background/30 py-2 pl-3 pr-2 text-[12px] leading-relaxed text-muted-foreground',
                proposal.origin === 'analyst' && 'whitespace-pre-wrap font-mono text-[11px]',
              )}
            >
              {proposal.evidence}
            </blockquote>
          )}
        </div>
      )}

      {proposal.neighbour && (
        <div className="mt-3 rounded-lg border border-border/70 bg-background/30 p-3">
          <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            <GitCompareArrows className="h-3 w-3" />
            Closest existing memory
          </div>
          <p className="text-[13px] leading-relaxed text-muted-foreground">{proposal.neighbour}</p>
        </div>
      )}

      {proposal.note && !actionable && (
        <p className="mt-3 text-[11px] text-muted-foreground">{proposal.note}</p>
      )}

      {actionable && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border/70 pt-3">
          {canApply && (
            <Button size="sm" onClick={() => onApply!(proposal.id!)} disabled={busy}>
              <Check className="mr-1.5 h-3.5 w-3.5" /> Keep it
            </Button>
          )}
          {canDiscard && (
            <Button size="sm" variant="outline" onClick={() => onDiscard!(proposal.id!)} disabled={busy}>
              <Trash2 className="mr-1.5 h-3.5 w-3.5" /> Discard
            </Button>
          )}
          {/* Stated on the card, not buried in a help page: discard is the one
              action here that cannot be undone from this screen. */}
          {canDiscard && (
            <span className="text-[11px] text-muted-foreground">
              Discarding is permanent — it will not be proposed again.
            </span>
          )}
        </div>
      )}
    </article>
  );
}
