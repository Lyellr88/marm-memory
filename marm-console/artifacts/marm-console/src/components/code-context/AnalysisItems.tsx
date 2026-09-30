import { cn } from '@/components/ui/core';
import type { AnswerDisagreement, AnswerItem, AnswerOp } from '@/lib/marm-types';

const TITLE: Record<AnswerOp, string> = {
  summary: 'Summary',
  facts: 'Facts',
  relations: 'Relations',
  gaps: 'Missing from the evidence',
  next_steps: 'Next steps',
};

const SUPPORT: Record<AnswerItem['support'], string> = {
  quote: 'verbatim quote',
  edge: 'call edge',
  link: 'memory link',
  citation: 'citations only',
  none: '',
};

function Item({ item }: { item: AnswerItem }) {
  return (
    <li data-item={item.id} className="rounded-md border border-border/60 bg-background/25 px-2 py-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10px] text-muted-foreground">{item.id}</span>
        <span className="text-[12px]">{item.text}</span>
        <span
          className={cn(
            'ml-auto rounded-full border px-1.5 text-[10px]',
            item.state === 'verified' && 'border-emerald-500/40 text-emerald-300',
            item.state === 'uncertain' && 'border-amber-500/40 text-amber-200',
            item.state === 'rejected' && 'border-red-500/50 text-red-300',
            (item.state === 'missing' || item.state === 'proposal') &&
              'border-border/70 text-muted-foreground',
          )}
        >
          {item.state}
          {item.state === 'verified' && SUPPORT[item.support] ? ` · ${SUPPORT[item.support]}` : ''}
        </span>
      </div>
      {item.quote && (
        <code className="mt-1 block break-all font-mono text-[10px] text-muted-foreground">
          {item.quote}
        </code>
      )}
      {item.failures.map((failure) => (
        <p key={failure} className="mt-0.5 font-mono text-[10px] text-amber-200/80">
          {failure}
        </p>
      ))}
    </li>
  );
}

/** Each structured result on its own, as the verifier judged it. A verified
 *  item names what verified it, because a quote and a bare citation are not
 *  the same strength of evidence. */
export function AnalysisItems({
  items,
  disagreements,
}: {
  items?: AnswerItem[];
  disagreements?: AnswerDisagreement[];
}) {
  const groups = (Object.keys(TITLE) as AnswerOp[])
    .map((op) => [op, (items ?? []).filter((i) => i.op === op)] as const)
    .filter(([, rows]) => rows.length > 0);
  if (!groups.length && !disagreements?.length) return null;
  return (
    <div className="space-y-3 rounded-xl border border-border/70 bg-background/25 p-3">
      {groups.map(([op, rows]) => (
        <div key={op}>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            {TITLE[op]}
          </div>
          <ul className="space-y-1">
            {rows.map((item) => (
              <Item key={item.id} item={item} />
            ))}
          </ul>
        </div>
      ))}
      {disagreements && disagreements.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Memory and code disagree
          </div>
          <ul className="space-y-1 text-[12px]">
            {disagreements.map((d) => (
              <li key={`${d.memory}-${d.from}-${d.to}`}>
                <span className="font-mono">{d.memory}</span> says {d.from}{' '}
                {d.memory_says ?? 'calls'} {d.to}; the graph shows{' '}
                {d.graph === 'edge' ? 'that edge' : 'no such edge'}
                <span className="ml-1 text-muted-foreground">({d.severity})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
