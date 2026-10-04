import type { AnswerVerification, GuardrailDecision } from './code-context';

/** How an analyst result was judged when it was staged. The answer's own
 *  verdict is nested, and is empty when the answer carried none. */
export interface StagedVerification {
  state: AnswerVerification['state'];
  claim_kind?: string;
  result?: string;
  packet_id?: string;
  answer?: Partial<AnswerVerification>;
}

/** One distilled proposal, before or after it has been staged. */
export interface DistillProposal {
  /** Absent when the proposal was not staged (a duplicate, or already seen). */
  id?: string;
  content: string;
  score: number;
  /** Why it scored what it scored -- shown so a reviewer can judge the judge. */
  reasons: string[];
  verdict: 'new' | 'duplicate' | 'near';
  cosine: number;
  /** Absent for `new`: below the near band there is no relationship to show. */
  neighbour_id?: string;
  neighbour?: string;
  staged?: boolean;
  note?: string;
  /** The verbatim span the fact came from. Present on the generation path,
   *  where the content was rewritten and the original would otherwise be lost. */
  evidence?: string;
  /** `generated` when a local model wrote it, `selected` when it was lifted
   *  from the transcript verbatim. */
  mode?: 'generated' | 'selected';
  session_name?: string;
  project?: string | null;
  context_type?: string;
  created_at?: string;
  /** `analyst` when the Code Context analyst staged it. */
  origin?: 'distill' | 'analyst';
  verification?: StagedVerification;
  /** Set when guardrails applied it during this run; it no longer awaits review. */
  applied?: boolean;
  applied_memory_id?: string;
  /** A guardrails decision, recorded whether or not it applied. */
  decision?: GuardrailDecision['decision'];
}

export interface DistillInput {
  action: 'propose' | 'review' | 'apply' | 'discard';
  text?: string | null;
  session_name?: string | null;
  proposal_id?: string | null;
  project?: string | null;
  context_type?: string;
  threshold?: number;
  limit?: number;
  include_duplicates?: boolean;
  use_llm?: boolean;
  review_mode?: 'manual' | 'guardrails';
}

export interface DistillResult {
  status: 'success';
  /** `propose` returns proposals; `review` returns pending. Never both. */
  proposals?: DistillProposal[];
  pending?: DistillProposal[];
  count?: number;
  extracted?: number;
  staged?: number;
  /** Applied by guardrails during this run, so not counted in `staged`. */
  applied?: number;
  session_name?: string;
  memory_id?: string;
  proposal_id?: string;
  /** Present when nothing read as durable -- a success, not a failure. */
  note?: string;
  /** Which extraction path ran. `selected` means no local model was reachable. */
  mode?: 'generated' | 'selected';
  review_mode?: 'manual' | 'guardrails';
  /** Present in guardrails mode: one decision per staged proposal. */
  guardrails?: GuardrailDecision[];
}
