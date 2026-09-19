import { useLocation } from 'wouter';
import { Button } from '@/components/ui/core';
import { Sparkles } from 'lucide-react';

/** Phrase a symbol as a task the ranker can actually use.
 *
 *  This is the decision the backlog said not to guess at, so it lives in one
 *  place with the reasoning attached. `marm_code_context` seeds its ranking
 *  from the task's own words, and a bare symbol name is documented as the
 *  input it is *worst* at — lexical search will happily return a private
 *  helper whose name matches and rank it above the class everything calls.
 *  A behaviour question composes a better neighbourhood.
 */
export function taskForSymbol(qualifiedName: string): string {
  // The bare tail, not the qualified path: dotted or double-colon segments are
  // noise to a ranker seeded on words, and the qualified name is passed
  // separately as the project scope anyway.
  const name = qualifiedName.split(/[.:]/).filter(Boolean).pop() || qualifiedName;
  return `How does ${name} work?`;
}

/** Jump to Code Context with a symbol's question prefilled.
 *
 *  It deliberately does NOT auto-run. The concern with prefilling a task was
 *  that it puts words in the reader's mouth — and that is only true if the
 *  words are acted on before anyone reads them. Landing the phrasing in the
 *  box, visible and editable, with the reader pressing Compose, turns the same
 *  string from an assumption into a suggestion.
 *
 *  The Overview bar does the opposite and passes `run=1`, because there the
 *  reader typed the question themselves and has nothing to review.
 */
export function ComposeAction({
  qualifiedName,
  project,
  className,
}: {
  qualifiedName: string;
  project?: string | null;
  className?: string;
}) {
  const [, navigate] = useLocation();
  if (!qualifiedName) return null;

  return (
    <Button
      size="sm"
      variant="outline"
      className={className}
      title={`Compose context for ${qualifiedName} — you can edit the question before it runs`}
      aria-label={`Compose context for ${qualifiedName}`}
      onClick={() => {
        const params = new URLSearchParams({ task: taskForSymbol(qualifiedName) });
        if (project) params.set('project', project);
        navigate(`/code-context?${params.toString()}`);
      }}
    >
      <Sparkles className="h-3.5 w-3.5" />
    </Button>
  );
}
