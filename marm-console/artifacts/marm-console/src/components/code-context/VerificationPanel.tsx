import { ShieldAlert, ShieldCheck, ShieldQuestion } from 'lucide-react';
import { cn } from '@/components/ui/core';
import type { AnswerVerification } from '@/lib/marm-types';

const LABEL = { verified: 'Verified', uncertain: 'Uncertain', rejected: 'Rejected' } as const;

const CHECKS = [
  ['citation_coverage', 'citation coverage'],
  ['source_span_support', 'source span support'],
  ['graph_memory_consistency', 'graph/memory consistency'],
] as const;

/** How the answer was judged. The score is the weakest check, so the check
 *  that set it is named: a reader should not have to find the minimum. */
export function VerificationPanel({ verification }: { verification: AnswerVerification }) {
  const { state } = verification;
  const Icon = state === 'verified' ? ShieldCheck : state === 'rejected' ? ShieldAlert : ShieldQuestion;
  const weakest = CHECKS.reduce((a, b) => (verification[b[0]] < verification[a[0]] ? b : a));
  return (
    <div
      className={cn(
        'rounded-lg border p-3 text-xs',
        state === 'verified' && 'border-emerald-500/40',
        state === 'uncertain' && 'border-amber-500/40',
        state === 'rejected' && 'border-red-500/50',
      )}
    >
      <div className="flex items-center gap-2 font-medium">
        <Icon className="h-4 w-4" />
        <span>{LABEL[state]}</span>
        <span className="ml-auto font-mono tabular-nums">{verification.score.toFixed(2)}</span>
      </div>
      {verification.hard_failures.map((failure) => (
        <p key={failure} className="mt-1 font-mono text-[11px] text-red-300">
          {failure}
        </p>
      ))}
      {verification.abstained ? (
        <p className="mt-2 text-muted-foreground">
          The model said the context does not show the answer. That is an honest reply, not a
          failure, and nothing from it is kept.
        </p>
      ) : (
        <ul className="mt-2 space-y-0.5 text-muted-foreground">
          {CHECKS.map(([key, label]) => (
            <li key={key} className="flex justify-between">
              <span>{label}</span>
              <span className="font-mono">{verification[key].toFixed(2)}</span>
            </li>
          ))}
        </ul>
      )}
      {state !== 'verified' && !verification.abstained && (
        <p className="mt-2">Weakest: {weakest[1]}</p>
      )}
      {verification.failures.map((failure) => (
        <p key={failure} className="mt-1 font-mono text-[11px] text-muted-foreground">
          {failure}
        </p>
      ))}
    </div>
  );
}
