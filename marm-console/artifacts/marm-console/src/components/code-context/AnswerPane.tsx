import { useMemo } from 'react';
import { Badge, Button, cn } from '@/components/ui/core';
import { MemoryEmptyState } from '@/components/memory/shared';
import { Sparkles, CircleAlert, FileCode2 } from 'lucide-react';
import type { CodeContextCitation, CodeContextResult, CodeContextSymbol } from '@/lib/marm-types';
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

export interface AnswerStream {
  status: 'idle' | 'streaming' | 'done' | 'error';
  text: string;
  citations: CodeContextCitation[];
  model?: string;
  message?: string;
  hint?: string;
}

export function AnswerPane({
  result,
  symbols,
  stream,
  onCite,
  onAsk,
  asking,
  canAsk = true,
}: {
  /** Absent before anything has been composed. Asking still works from here:
   *  the button composes and answers in one step, so a reader who arrived with
   *  a question never has to learn that "compose" comes first. */
  result?: CodeContextResult;
  /** Ranked symbols from the composition, used to resolve citation markers
   *  while the answer is still arriving. The server's own resolution lands
   *  with the final frame and replaces this. */
  symbols?: CodeContextSymbol[];
  /** Live answer state. Present while one is arriving and after it lands;
   *  `result.answer` remains the non-streaming path an agent-shaped response
   *  still uses. */
  stream?: AnswerStream;
  onCite: (citation: CodeContextCitation) => void;
  onAsk: () => void;
  asking: boolean;
  canAsk?: boolean;
}) {
  // A live stream wins over a finished JSON answer: it is the newer one, and
  // during streaming it is the only one with any text at all.
  const streaming = stream && stream.status !== 'idle';
  const text = streaming ? stream.text : (result?.answer ?? '');
  const settled = streaming ? stream.citations : (result?.answer_citations ?? []);
  // While the answer is still arriving the server has not resolved anything
  // yet -- it cannot, because a marker may still be arriving one character at
  // a time. Without this a reader watches raw `[cpu_write_register]` text for
  // the whole eight seconds and only sees links at the very end. The symbols
  // are already on the page, so the same resolution is available locally.
  const citations = useMemo(() => {
    if (settled.length > 0 || !symbols?.length) return settled;
    return symbols.map((symbol) => ({
      name: symbol.name,
      qualified_name: symbol.qualified_name,
      file_path: symbol.file_path,
      start_line: symbol.start_line,
    }));
  }, [settled, symbols]);
  const model = streaming ? stream.model : result?.answer_model;
  const status = streaming
    ? stream.status === 'error'
      ? 'failed'
      : 'ok'
    : result?.answer_status;

  if (stream?.status === 'error') {
    return (
      <div className="rounded-xl border border-amber-500/25 bg-amber-500/[0.05] p-4">
        <div className="flex items-start gap-3">
          <CircleAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-amber-100">{stream.message}</p>
            {stream.hint && (
              <p className="mt-1 text-sm text-muted-foreground">{stream.hint}</p>
            )}
            <p className="mt-2 text-[11px] text-muted-foreground">
              Everything else on this page is unaffected — the ranked symbols, their source and
              what memory knows were retrieved without a model.
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (!status) {
    return (
      <MemoryEmptyState
        icon={Sparkles}
        tone="console-tab-rose"
        title={result ? 'No answer was requested' : 'Ask a question about this project'}
        detail={
          canAsk
            ? 'The local model answers only from the context MARM ranks for your task, and cites the symbols it used. Nothing leaves this machine.'
            : 'Type what you are trying to do or understand in the Task box above, then ask. Ranking is seeded from your own words.'
        }
      >
        <Button className="mt-4" onClick={onAsk} isLoading={asking} disabled={!canAsk}>
          <Sparkles className="mr-2 h-4 w-4" />
          {result ? 'Answer from this context' : 'Compose and answer'}
        </Button>
      </MemoryEmptyState>
    );
  }

  if (status !== 'ok' || (!text && stream?.status !== 'streaming')) {
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
            <p className="mt-1 text-sm text-muted-foreground">{result?.answer_hint}</p>
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
        {model && (
          <Badge variant="outline" className="font-mono text-[10px]">
            {model}
          </Badge>
        )}
        <span className="text-[11px] text-muted-foreground">
          {/* While streaming, the composition may not have landed yet, so the
              count is omitted rather than shown as a confident zero. */}
          {typeof result?.symbol_count === 'number'
            ? `Answered only from the ${result.symbol_count.toLocaleString()} ranked symbols above — not from general knowledge of similar projects.`
            : 'Answered only from the ranked context for this task — not from general knowledge of similar projects.'}
        </span>
        <div className="ml-auto">
          <CopyButton className="h-7 w-7" value={text} label="Copy the answer" />
        </div>
      </div>

      <div className="space-y-1 rounded-xl border border-border/80 bg-card/45 p-4 text-[13px] leading-relaxed">
        {withCitations(text, citations, onCite)}
        {stream?.status === 'streaming' && (
          /* A caret, not a spinner: the answer is arriving, not pending, and a
             spinner beside text that is already appearing says the wrong thing. */
          <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-primary align-text-bottom" />
        )}
      </div>

      {settled.length > 0 && (
        <div className="rounded-xl border border-border/70 bg-background/25 p-3">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Sources it used
          </div>
          <div className="flex flex-wrap gap-2">
            {settled.map((citation) => (
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
