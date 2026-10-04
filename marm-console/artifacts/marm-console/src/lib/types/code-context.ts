export interface CodeContextInput {
  task: string;
  project?: string | null;
  cwd?: string | null;
  budget?: number;
  /** Ask for the ranked call neighbourhood. Off by default server-side. */
  include_graph?: boolean;
  /** Also answer the task from the composed context with the local model. */
  answer?: boolean;
  /** 1 = markdown only, 2 = + metadata, 3 = + source and memory bodies.
   *  The Console lays the parts out, so it always asks for 3; an agent reads
   *  the markdown and stops, which is why the server default is 1. */
  detail?: number;
  /** With `answer`: also stage its verified results for review, or under
   *  guardrails let MARM apply the ones it can prove mechanically. */
  analyst_mode?: AnalystMode;
}

/** How a symbol was reached, when it arrived through the call graph rather than
 *  by matching the task. `null` for a seeded symbol — the four fields are
 *  jointly present or jointly absent, so zeros would be a claim, not an absence. */
export interface CodeContextProvenance {
  hop: number;
  strategy: string;
  confidence: number;
  risk: string;
}

export interface CodeContextSymbol {
  name: string;
  qualified_name: string;
  label: string;
  file_path: string;
  start_line: number;
  end_line: number;
  score: number;
  seeded: boolean;
  truncated: boolean;
  /** Present only at detail level 3; `serialise` omits it below that. */
  source?: string;
  provenance: CodeContextProvenance | null;
}

/** A memory row as `smart_recall` returns it. Every field optional: these come
 *  straight off the recall response and the page must not assume a shape it
 *  does not control. */
export interface CodeContextMemory {
  id?: string;
  content?: string;
  summary?: string;
  session_name?: string;
  similarity?: number;
  timestamp?: string;
  context_type?: string;
  project?: string;
  platform?: string;
  [key: string]: unknown;
}

export interface CodeContextProject {
  name: string;
  short_name: string;
  root_path: string;
}

/** `no_project` and `unavailable` are answers, not failures: each carries the
 *  next step to take, so the page renders the hint rather than an error. */
export interface CodeContextResult {
  status: 'success' | 'no_project' | 'unavailable';
  message?: string;
  hint?: string;
  project?: CodeContextProject;
  task?: string;
  markdown?: string;
  symbols?: CodeContextSymbol[];
  memories?: CodeContextMemory[];
  links?: Array<Record<string, unknown>>;
  graph_nodes?: number;
  /** Which level the server actually applied, after its own default. */
  detail?: number;
  /** Present at every level: the counts survive when the arrays do not. */
  symbol_count?: number;
  memory_count?: number;
  /** `[source, target, weight]`, present only when `include_graph` was set. */
  graph_edges?: Array<[string, string, number]>;
  notes?: string[];
  /** Grounded answer, present only when `answer` was requested. `null` with a
   *  status of `unavailable`/`failed` means the retrieval above still stands. */
  answer?: string | null;
  /** `ok` when verified against the composed context, `unverified` when its
   *  support is weak, `rejected` when it cites something the context does
   *  not contain. */
  answer_status?: AnswerGrounding | 'unavailable' | 'failed';
  answer_hint?: string;
  answer_model?: string;
  answer_model_info?: AnswerModelInfo;
  /** Only what is actually in the context; an invented name is dropped
   *  server-side rather than rendered as a dead link. */
  answer_citations?: CodeContextCitation[];
  /** Identifier-shaped citations that resolved to nothing in the context. */
  answer_unresolved?: string[];
  answer_verification?: AnswerVerification;
  answer_packet?: AnswerPacket;
  /** The operator's profile, with the limits it held the model to. */
  answer_profile?: AnswerProfile;
  /** Structured profiles only: what each narrow operation returned. */
  answer_operations?: AnswerOperation[];
  answer_items?: AnswerItem[];
  /** Memories that state a call the packet's graph does not show. */
  answer_disagreements?: AnswerDisagreement[];
  /** Present when `analyst_mode` was not `read_only`. */
  analyst?: AnalystResult;
}

export type AnswerGrounding = 'ok' | 'unverified' | 'rejected';

export type AnalystMode = 'read_only' | 'manual_review' | 'guardrails';

export interface CodeContextCitation {
  /** `S1`/`M1`: the packet handle the answer cited. Absent from an older server. */
  handle?: string;
  kind?: 'symbol' | 'memory';
  name: string;
  qualified_name?: string;
  file_path?: string;
  start_line?: number;
  memory_id?: string;
}

export interface AnswerVerification {
  state: 'verified' | 'uncertain' | 'rejected';
  /** The minimum of the three checks, never their average. */
  score: number;
  citation_coverage: number;
  source_span_support: number;
  graph_memory_consistency: number;
  claims: number;
  cited_claims: number;
  failures: string[];
  hard_failures: string[];
  abstained: boolean;
}

export interface AnswerModelInfo {
  id: string;
  endpoint_source: string | null;
  profile?: string;
  /** The cap each call requested: output plus reasoning. Never widened. */
  max_tokens: number;
  output_tokens?: number;
  reasoning_tokens?: number;
  time_s?: number;
  calls?: number;
  output_chars?: number;
  elapsed_ms: number;
  stopped: 'cancelled' | 'deadline' | null;
}

export type AnalystProfileName = 'general' | 'small' | 'large';

export interface AnswerProfile {
  name: AnalystProfileName;
  context_chars: number;
  max_symbols: number;
  max_memories: number;
  output_tokens: number;
  reasoning_tokens: number;
  max_tokens: number;
  time_s: number;
  structured: boolean;
  batch: boolean;
}

export type AnswerOp = 'summary' | 'facts' | 'relations' | 'gaps' | 'next_steps';

export interface AnswerItem {
  /** Stable within one answer: A1 summary, F1 fact, R1 relation, G1 gap, N1 step. */
  id: string;
  op: AnswerOp;
  text: string;
  state: 'verified' | 'uncertain' | 'rejected' | 'missing' | 'proposal';
  /** What decided a verified state: a verbatim quote, a call edge, a memory
   *  link, or only resolved citations. */
  support: 'quote' | 'edge' | 'link' | 'citation' | 'none';
  cites: string[];
  quote?: string;
  kind?: 'calls' | 'memory_about';
  from?: string;
  to?: string;
  action?: 'read' | 'compare' | 'verify' | 'ask';
  failures: string[];
}

export interface AnswerOperation {
  op: AnswerOp;
  status: 'ok' | 'empty' | 'malformed' | 'failed' | 'skipped';
  malformed: number;
  dropped: number;
  finish: string | null;
  elapsed_ms: number;
  output_chars: number;
  items?: AnswerItem[];
}

export interface AnswerDisagreement {
  memory: string;
  from: string;
  to: string;
  memory_says?: 'calls' | 'does not call';
  graph?: 'edge' | 'no edge';
  severity: 'contradicted' | 'unconfirmed';
  sentence?: string;
}

export interface AnswerPacket {
  packet_id: string;
  project: string;
  task: string;
  symbols: Array<{
    handle: string;
    qualified_name: string;
    name: string;
    file_path: string;
    start_line: number;
    end_line: number;
  }>;
  memories: Array<{ handle: string; memory_id: string; content: string }>;
  /** Rendered size of what the model read, and what the profile's cap left out. */
  chars?: number;
  omitted_symbols?: number;
  omitted_memories?: number;
}

export interface GuardrailDecision {
  proposal_id: string;
  applied: boolean;
  memory_id?: string;
  decision: {
    apply: boolean;
    /** `review_required` whenever MARM could not prove the claim mechanically;
     *  `apply_failed` when it was eligible but the write did not happen. */
    status?: 'applied' | 'review_required' | 'apply_failed';
    checks: Record<string, boolean>;
    reason: string;
    error?: string;
  };
  error?: string;
}

export interface AnalystResult {
  mode: AnalystMode;
  /** Proposal ids staged into the Distill queue. */
  staged: string[];
  skipped: Array<{ content: string; reason: string }>;
  decisions: GuardrailDecision[];
}
