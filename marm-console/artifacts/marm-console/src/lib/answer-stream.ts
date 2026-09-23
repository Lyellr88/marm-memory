import type { AnswerGrounding, CodeContextCitation, CodeContextResult } from '@/lib/marm-types';

/** The state of one streamed answer, as the Console renders it. */
export interface AnswerStreamState {
  status: 'idle' | 'streaming' | 'done' | 'error';
  text: string;
  citations: CodeContextCitation[];
  model?: string;
  message?: string;
  hint?: string;
  /** The server's verdict on the finished text; absent until `done`. */
  grounding?: AnswerGrounding;
  unresolved?: string[];
  /** The model stopped at its token budget even after the wider retry. */
  truncated?: boolean;
  /** The composition the answer is written from: the stream's first event. */
  context?: CodeContextResult;
}

export const IDLE_ANSWER: AnswerStreamState = { status: 'idle', text: '', citations: [] };

/** Fold one server-sent event into the answer state. Pure, so each event's
 *  effect is testable without a network or a React tree. */
export function applyAnswerEvent(
  prev: AnswerStreamState,
  name: string,
  payload: Record<string, unknown>,
): AnswerStreamState {
  switch (name) {
    case 'context':
      return { ...prev, context: payload as unknown as CodeContextResult };
    case 'start':
      return { ...prev, model: payload.model as string };
    case 'delta':
      return { ...prev, text: prev.text + (payload.text as string) };
    case 'restart':
      // The server is retrying with a wider budget; what was sent is withdrawn.
      return { ...prev, status: 'streaming', text: '' };
    case 'done':
      return {
        ...prev,
        status: 'done',
        citations: (payload.citations as CodeContextCitation[]) ?? [],
        // Absent from a server that predates the check, which cannot have
        // verified anything, so it is unverified rather than grounded.
        grounding: (payload.status as AnswerGrounding | undefined) ?? 'unverified',
        unresolved: (payload.unresolved as string[] | undefined) ?? [],
        hint: payload.hint as string | undefined,
        truncated: Boolean(payload.truncated),
      };
    case 'error':
      return {
        ...prev,
        status: 'error',
        message: payload.message as string,
        hint: payload.hint as string | undefined,
      };
    default:
      return prev;
  }
}
