import type {
  AnalystResult,
  AnswerDisagreement,
  AnswerGrounding,
  AnswerItem,
  AnswerModelInfo,
  AnswerOperation,
  AnswerPacket,
  AnswerProfile,
  AnswerVerification,
  CodeContextCitation,
  CodeContextResult,
} from '@/lib/marm-types';

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
  /** Cut off by the profile's token cap or time limit. Never retried wider. */
  truncated?: boolean;
  /** The composition the answer is written from: the stream's first event. */
  context?: CodeContextResult;
  /** The evidence the model was given, built once by MARM. */
  packet?: AnswerPacket;
  verification?: AnswerVerification;
  modelInfo?: AnswerModelInfo;
  /** The operator's profile and the limits it held the model to. */
  profile?: AnswerProfile;
  /** Structured profiles: each operation as it finishes, then every item. */
  operations?: AnswerOperation[];
  items?: AnswerItem[];
  disagreements?: AnswerDisagreement[];
  /** Staged results and guardrails decisions, when a mode asked for them. */
  analyst?: AnalystResult;
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
    case 'packet':
      return { ...prev, packet: payload as unknown as AnswerPacket };
    case 'start':
      return {
        ...prev,
        model: payload.model as string,
        profile: payload.profile as AnswerProfile | undefined,
      };
    case 'operation':
      return {
        ...prev,
        operations: [...(prev.operations ?? []), payload as unknown as AnswerOperation],
      };
    case 'delta':
      return { ...prev, text: prev.text + (payload.text as string) };
    case 'restart':
      // Sent only by a server that still widened its budget; what was sent is
      // withdrawn.
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
        verification: payload.verification as AnswerVerification | undefined,
        modelInfo: payload.model_info as AnswerModelInfo | undefined,
        profile: (payload.profile as AnswerProfile | undefined) ?? prev.profile,
        operations: (payload.operations as AnswerOperation[] | undefined) ?? prev.operations,
        items: payload.items as AnswerItem[] | undefined,
        disagreements: payload.disagreements as AnswerDisagreement[] | undefined,
        analyst: payload.analyst as AnalystResult | undefined,
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

/** The response body closed. A stream still `streaming` never sent `done` or
 *  `error` -- a proxy or server restart, an upstream timeout -- and would
 *  otherwise show "answering…" forever. */
export function applyStreamEnd(prev: AnswerStreamState): AnswerStreamState {
  if (prev.status !== 'streaming') return prev;
  return {
    ...prev,
    status: 'error',
    message: 'The answer stream ended before the answer finished.',
  };
}
