export type CodeSearchKind = 'auto' | 'symbol' | 'text' | 'snippet';

export interface CodeSearchInput {
  query: string;
  kind?: CodeSearchKind;
  limit?: number;
}

export interface CodeSearchResult {
  qualified_name: string;
  file_path: string;
  line: number | null;
  snippet: string | null;
  kind: string;
}

export type TraceDirection = 'inbound' | 'outbound' | 'both';
export type TraceMode = 'calls' | 'data_flow' | 'cross_service';

export interface TraceInput {
  symbol: string;
  direction?: TraceDirection;
  mode?: TraceMode;
  depth?: number;
}

export interface TraceStep {
  qualified_name: string;
  file_path: string;
  relation: string;
}

export interface TraceResult {
  root: string;
  steps: TraceStep[];
  truncated: boolean;
}

export interface ImpactInput {
  base_branch?: string;
  since?: string;
  depth?: number;
}

export interface ImpactResult {
  changed_files: string[];
  /** Normalised by the Console proxy from the engine's `impacted_symbols`.
   *  There is no `risk` here: the engine does not compute one, and the field
   *  this replaced was defaulted to `'low'` for every row — a risk assessment
   *  nothing had made. `hop` is the real signal: distance from a changed file. */
  affected_symbols: {
    qualified_name: string;
    file_path: string;
    label?: string;
    hop?: number | null;
  }[];
  /** The engine caps what it returns. Without these the page shows 200 rows
   *  and lets a reader believe that is all of them. */
  impacted_total?: number;
  impacted_shown?: number;
  impacted_modules?: { module: string; count: number }[];
  seed_symbols?: number;
  base?: string;
}
