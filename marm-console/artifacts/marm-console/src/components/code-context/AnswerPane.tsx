import { Badge, Button, cn } from '@/components/ui/core';
import { MemoryEmptyState } from '@/components/memory/shared';
import { Sparkles, CircleAlert, FileCode2 } from 'lucide-react';
import type { CodeContextCitation, CodeContextResult } from '@/lib/marm-types';
import { CopyButton } from './shared';

/** The model writes markdown. Rendering it as literal asterisks is not a small
 *  cosmetic issue: `**Immediate assertion:**` in the middle of a technical
 *  answer reads as noise and buries the structure the model deliberately put
 *  there. This handles the three things an answer actually uses — bold, inline
 *  code, and list markers — and nothing else.
 *
 *  Deliberately not a markdown library. The app has none, the answer is one
 *  block of prose, and every markdown renderer worth adding either pulls in a
 *  parser or wants `dangerouslySetInnerHTML`, which appears zero times in this
 *  codebase and should not start here for a formatting nicety.
 */
function inline(text: string, keyPrefix: string) {
  const parts = text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g);
  return parts.map((part, i) => {
    const key = `${keyPrefix}-${i}`;
    if (/^\*\*[^*\n]+\*\*$/.test(part)) {
      return (
        <strong key={key} className="font-semibold text-foreground">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (/^`[^`\n]+`$/.test(part)) {
      return (
        <code key={key} className="rounded bg-muted/50 px-1 font-mono text-[0.9em]">
          {part.slice(1, -1)}
        </code>
      );
    }
    return <span key={key}>{part}</span>;
  });
}

/** Render the citation markers as something you can click.
 *
 *  The model writes `[symbol]` inline. Only names the server could resolve back
 *  to a real symbol arrive in `answer_citations`, so an unresolved marker is
 *  rendered as plain text rather than a link — a citation that goes nowhere is
 *  worse than no citation, because it looks like evidence.
 */
function withCitations(
  text: string,
  citations: CodeContextCitation[],
  onCite: (citation: CodeContextCitation) => void,
) {
  const byName = new Map(citations.map((c) => [c.name.toLowerCase(), c]));
  return text.split('\n').map((line, lineIndex) => {
    const bullet = /^\s*(?:[-*]|\d+\.)\s+/.exec(line);
    const body = bullet ? line.slice(bullet[0].length) : line;
    const rendered = body.split(/(\[`?[^\]`\n]{1,200}`?\])/g).map((part, i) => {
      const match = /^\[`?([^\]`\n]{1,200})`?\]$/.exec(part);
      const citation = match
        ? byName.get(match[1].trim().replace(/`/g, '').split('(')[0].trim().toLowerCase())
        : undefined;
      if (!citation) return <span key={`${lineIndex}-${i}`}>{inline(part, `${lineIndex}-${i}`)}</span>;
      return (
        <button
          key={`${lineIndex}-${i}`}
          type="button"
          onClick={() => onCite(citation)}
          title={`${citation.file_path}:${citation.start_line}`}
          className="mx-0.5 rounded border border-primary/30 bg-primary/10 px-1 font-mono text-[0.85em] text-primary-highlight transition-colors hover:bg-primary/20"
        >
          {citation.name}
        </button>
      );
    });
    if (!line.trim()) return <div key={lineIndex} className="h-2" />;
    return (
      <div key={lineIndex} className={bullet ? 'flex gap-2 pl-1' : undefined}>
        {bullet && <span className="shrink-0 text-muted-foreground">{bullet[0].trim()}</span>}
        <span className="min-w-0">{rendered}</span>
      </div>
    );
  });
}

export function AnswerPane({
  result,
  onCite,
  onAsk,
  asking,
}: {
  result: CodeContextResult;
  onCite: (citation: CodeContextCitation) => void;
  onAsk: () => void;
  asking: boolean;
}) {
  const status = result.answer_status;
  const citations = result.answer_citations ?? [];

  if (!status) {
    return (
      <MemoryEmptyState
        title="No answer was requested"
        detail="Ask the local model to answer this task from the ranked context above. It answers only from what the ranking retrieved, and cites the symbols it used."
      >
        <Button className="mt-4" onClick={onAsk} isLoading={asking}>
          <Sparkles className="mr-2 h-4 w-4" /> Answer from this context
        </Button>
      </MemoryEmptyState>
    );
  }

  if (status !== 'ok' || !result.answer) {
    return (
      <div className="rounded-xl border border-amber-500/25 bg-amber-500/[0.05] p-4">
        <div className="flex items-start gap-3">
          <CircleAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-amber-100">
              {status === 'unavailable'
                ? 'No local model is reachable'
                : 'The local model did not answer'}
            </p>
            <p className="mt-1 text-sm text-muted-foreground">{result.answer_hint}</p>
            <p className="mt-2 text-[11px] text-muted-foreground">
              Everything else on this page is unaffected — the ranked symbols, their source and
              what memory knows were retrieved without a model and are the answer a reader needs.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="border-primary/30 text-primary-highlight">
          <Sparkles className="mr-1 h-3 w-3" />
          grounded answer
        </Badge>
        {result.answer_model && (
          <Badge variant="outline" className="font-mono text-[10px]">
            {result.answer_model}
          </Badge>
        )}
        <span className="text-[11px] text-muted-foreground">
          Answered only from the {(result.symbol_count ?? 0).toLocaleString()} ranked symbols
          above — not from general knowledge of similar projects.
        </span>
        <div className="ml-auto">
          <CopyButton className="h-7 w-7" value={result.answer} label="Copy the answer" />
        </div>
      </div>

      <div className="space-y-1 rounded-xl border border-border/80 bg-card/45 p-4 text-[13px] leading-relaxed">
        {withCitations(result.answer, citations, onCite)}
      </div>

      {citations.length > 0 && (
        <div className="rounded-xl border border-border/70 bg-background/25 p-3">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Sources it used
          </div>
          <div className="flex flex-wrap gap-2">
            {citations.map((citation) => (
              <button
                key={citation.qualified_name}
                type="button"
                onClick={() => onCite(citation)}
                className={cn(
                  'flex items-center gap-1.5 rounded-lg border border-border/70 bg-card/45 px-2 py-1',
                  'font-mono text-[11px] transition-colors hover:border-primary/40',
                )}
                title={`${citation.file_path}:${citation.start_line}`}
              >
                <FileCode2 className="h-3 w-3 text-cyan-300" />
                {citation.name}
                <span className="text-muted-foreground">:{citation.start_line}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <p className="text-[11px] text-muted-foreground">
        A grounded answer can still be wrong about code it was given. The citations are the point —
        click one to read the source it claims to be describing.
      </p>
    </div>
  );
}
