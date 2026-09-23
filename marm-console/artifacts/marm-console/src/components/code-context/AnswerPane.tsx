import { useMemo } from 'react';
import { Link } from 'wouter';
import { Badge, Button, cn } from '@/components/ui/core';
import { MemoryEmptyState } from '@/components/memory/shared';
import { Sparkles, CircleAlert, FileCode2, Brain, ShieldAlert } from 'lucide-react';
import type {
  AnalystResult,
  AnswerGrounding,
  AnswerModelInfo,
  AnswerPacket,
  AnswerVerification,
  CodeContextCitation,
  CodeContextResult,
  CodeContextSymbol,
} from '@/lib/marm-types';
import { CopyButton } from './shared';
import { VerificationPanel } from './VerificationPanel';

const HANDLE = /^[SM]\d+$/i;

/** The packet as citations, so `[S1]` links while the answer is still arriving. */
function packetCitations(packet: AnswerPacket): CodeContextCitation[] {
  return [
    ...packet.symbols.map((s) => ({ ...s, kind: 'symbol' as const })),
    ...packet.memories.map((m) => ({
      handle: m.handle,
      kind: 'memory' as const,
      name: m.handle,
      memory_id: m.memory_id,
    })),
  ];
}

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
  const byHandle = new Map(
    citations.filter((c) => c.handle).map((c) => [(c.handle as string).toUpperCase(), c]),
  );
  const lookup = (raw: string) => {
    const name = raw.trim().replace(/`/g, '').split('(')[0].trim();
    return HANDLE.test(name) ? byHandle.get(name.toUpperCase()) : byName.get(name.toLowerCase());
  };
  const link = (citation: CodeContextCitation, key: string) => (
    <button
      key={key}
      type="button"
      onClick={() => onCite(citation)}
      title={
        citation.kind === 'memory'
          ? `memory ${citation.memory_id ?? citation.handle}`
          : `${citation.file_path}:${citation.start_line}`
      }
      className="mx-0.5 rounded border border-primary/30 bg-primary/10 px-1 font-mono text-[0.85em] text-primary-highlight transition-colors hover:bg-primary/20"
    >
      {citation.name}
    </button>
  );
  return text.split('\n').map((line, lineIndex) => {
    const bullet = /^\s*(?:[-*]|\d+\.)\s+/.exec(line);
    const body = bullet ? line.slice(bullet[0].length) : line;
    // Same shape the server resolves: `[a]`, `[`a`]`, `[a, b]`, never a link's text.
    const rendered = body.split(/(\[[^[\]\n]{1,200}\](?!\())/g).map((part, i) => {
      const key = `${lineIndex}-${i}`;
      const match = /^\[([^[\]\n]{1,200})\]$/.exec(part);
      const names = match ? match[1].split(/([,;])/) : [];
      if (!names.some((name, n) => n % 2 === 0 && lookup(name))) {
        return <span key={key}>{inline(part, key)}</span>;
      }
      // Resolved names become links; anything unresolved stays plain text.
      return (
        <span key={key}>
          {names.map((name, n) => {
            const citation = n % 2 === 0 ? lookup(name) : undefined;
            return citation ? link(citation, `${key}-${n}`) : <span key={`${key}-${n}`}>{name}</span>;
          })}
        </span>
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
  grounding?: AnswerGrounding;
  unresolved?: string[];
  truncated?: boolean;
  packet?: AnswerPacket;
  verification?: AnswerVerification;
  modelInfo?: AnswerModelInfo;
  analyst?: AnalystResult;
}

function elapsed(info: AnswerModelInfo) {
  return `${(info.elapsed_ms / 1000).toFixed(1)} s`;
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
  // Once the server has ruled, only what it resolved is linked.
  const arriving = stream?.status === 'streaming';
  const packet = streaming ? stream.packet : result?.answer_packet;
  const citations = useMemo(() => {
    if (!arriving) return settled;
    if (packet) return packetCitations(packet);
    if (!symbols?.length) return settled;
    return symbols.map((symbol) => ({
      name: symbol.name,
      qualified_name: symbol.qualified_name,
      file_path: symbol.file_path,
      start_line: symbol.start_line,
    }));
  }, [arriving, settled, symbols, packet]);
  const sources = settled.filter((c) => c.kind !== 'memory' && c.file_path);
  const cited = settled.filter((c) => c.kind === 'memory');
  const verification = streaming ? stream.verification : result?.answer_verification;
  const modelInfo = streaming ? stream.modelInfo : result?.answer_model_info;
  const analyst = streaming ? stream.analyst : result?.analyst;
  const model = streaming ? stream.model : result?.answer_model;
  // `answering` is not a verdict: grounding is decided on the finished text.
  const status = streaming
    ? stream.status === 'error'
      ? 'failed'
      : arriving
        ? 'answering'
        : (stream.grounding ?? 'unverified')
    : result?.answer_status;
  const hint = streaming ? stream.hint : result?.answer_hint;

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

  if (status === 'unavailable' || status === 'failed' || (!text && !arriving)) {
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
            <p className="mt-1 text-sm text-muted-foreground">{hint}</p>
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
        {status === 'ok' ? (
          <Badge variant="outline" className="border-primary/30 text-primary-highlight">
            <Sparkles className="mr-1 h-3 w-3" />
            grounded answer
          </Badge>
        ) : status === 'rejected' ? (
          <Badge variant="outline" className="border-red-500/50 text-red-300">
            <ShieldAlert className="mr-1 h-3 w-3" />
            rejected answer
          </Badge>
        ) : status === 'answering' ? (
          <Badge variant="outline" className="text-muted-foreground">
            <Sparkles className="mr-1 h-3 w-3" />
            answering…
          </Badge>
        ) : (
          <Badge variant="outline" className="border-amber-500/40 text-amber-200">
            <CircleAlert className="mr-1 h-3 w-3" />
            unverified
          </Badge>
        )}
        {model && (
          <Badge variant="outline" className="font-mono text-[10px]">
            {model}
          </Badge>
        )}
        <span className="text-[11px] text-muted-foreground">
          {status === 'unverified' || status === 'rejected'
            ? hint
            : typeof result?.symbol_count === 'number'
              ? `Written only from the ${result.symbol_count.toLocaleString()} ranked symbols above — not from general knowledge of similar projects.`
              : 'Written only from the ranked context for this task — not from general knowledge of similar projects.'}
        </span>
        <div className="ml-auto">
          <CopyButton className="h-7 w-7" value={text} label="Copy the answer" />
        </div>
      </div>

      {verification && !arriving && <VerificationPanel verification={verification} />}

      <div className="space-y-1 rounded-xl border border-border/80 bg-card/45 p-4 text-[13px] leading-relaxed">
        {withCitations(text, citations, onCite)}
        {stream?.status === 'streaming' && (
          /* A caret, not a spinner: the answer is arriving, not pending, and a
             spinner beside text that is already appearing says the wrong thing. */
          <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-primary align-text-bottom" />
        )}
      </div>

      {stream?.status === 'done' && stream.truncated && (
        <p className="text-[11px] text-amber-200/90">
          The model stopped at its token budget, even after one retry with a wider one, so this answer
          ends early. Raise <code className="font-mono">MARM_CODE_CONTEXT_ANSWER_TOKENS</code> for a
          reasoning model.
        </p>
      )}

      {(modelInfo || packet) && !arriving && (
        <p className="font-mono text-[10px] text-muted-foreground">
          {modelInfo && `${modelInfo.id} · ${elapsed(modelInfo)}`}
          {modelInfo && packet && ' · '}
          {packet && `packet ${packet.packet_id}`}
          {modelInfo?.stopped === 'deadline' && ' · stopped at its time budget'}
          {modelInfo?.stopped === 'cancelled' && ' · stopped when the reader left'}
        </p>
      )}

      {analyst && !arriving && (
        <div className="rounded-xl border border-border/70 bg-background/25 p-3 text-[12px]">
          {analyst.staged.length > 0 && (
            <Link href="/distill" className="font-medium text-primary-highlight underline-offset-2 hover:underline">
              {analyst.staged.length === 1
                ? '1 conclusion staged for review'
                : `${analyst.staged.length} conclusions staged for review`}
            </Link>
          )}
          {analyst.staged.length === 0 && (
            <p className="text-muted-foreground">
              Nothing was staged
              {analyst.skipped[0]?.reason ? `: ${analyst.skipped[0].reason}` : '.'}
            </p>
          )}
          {analyst.decisions.map((d) => (
            <p key={d.proposal_id} className="mt-1 text-[11px] text-muted-foreground">
              {d.applied ? 'Applied as a memory.' : d.decision.reason}
            </p>
          ))}
        </div>
      )}

      {cited.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <Brain className="h-3 w-3" />
          {cited.map((citation) => (
            <button
              key={citation.handle ?? citation.name}
              type="button"
              onClick={() => onCite(citation)}
              className="rounded-lg border border-border/70 bg-card/45 px-2 py-0.5 font-mono"
            >
              memory {citation.handle}
            </button>
          ))}
        </div>
      )}

      {sources.length > 0 && (
        <div className="rounded-xl border border-border/70 bg-background/25 p-3">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Sources it used
          </div>
          <div className="flex flex-wrap gap-2">
            {sources.map((citation) => (
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

      {status === 'ok' && (
        <p className="text-[11px] text-muted-foreground">
          A grounded answer can still be wrong about code it was given. The citations are the point —
          click one to read the source it claims to be describing.
        </p>
      )}
    </div>
  );
}
