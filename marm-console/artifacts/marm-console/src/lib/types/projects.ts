export interface ProjectSummary {
  name: string;
  /** Short label for display; falls back to `name`. Never use as an identity or route key. */
  display_name?: string;
  root_path: string;
  nodes: number;
  edges: number;
  status: 'ready' | 'error' | 'indexing' | 'unknown';
}

export type IndexMode = 'fast' | 'moderate' | 'full';

export interface ProjectIndexInput {
  repo_path: string;
  project?: string;
  mode: IndexMode;
}

export interface IndexJob {
  job_id: string;
  status: 'queued' | 'running' | 'success' | 'error';
  project: string | null;
  phase: string | null;
  error: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at: string | null;
}

export interface ProjectStatus {
  name: string;
  status: 'ready' | 'error' | 'indexing' | 'unknown';
  nodes: number;
  edges: number;
  last_indexed_at: string | null;
  error: string | null;
}

export interface ProjectCoverageEntry {
  path: string;
  kind: string;
  detail?: string;
}

export interface ProjectCoverage {
  signal: 'best_effort' | string;
  indexed_at?: string | null;
  metadata?: {
    generation_matches?: boolean;
    index_mode?: IndexMode | string;
    recording_status?: string;
  };
  scopes: Array<{
    total: number;
    has_more?: boolean;
    entries: ProjectCoverageEntry[];
    status?: string;
  }>;
  caveat?: string;
}

export interface ProjectAdr {
  content?: string;
  status?: string;
  message?: string;
  [key: string]: unknown;
}

export interface RuntimeTrace {
  caller: string;
  callee: string;
  count: number;
}

export interface GraphTypeEntry {
  // Only `name` may be rendered as a child. React raises on an object child, and
  // an unreduced engine row reaching a badge is what took down this whole tab.
  name: string;
  count?: number;
}

export interface ProjectArchitecture {
  name: string;
  state: 'ready' | 'indexed_no_summary';
  message?: string | null;
  schema: { node_types: GraphTypeEntry[]; edge_types: GraphTypeEntry[] };
}

export interface CodeUnit {
  unit: string;
  fan_in: number;
  fan_out: number;
}

export interface CodeUnitEdge {
  path: string;
  count: number;
}

export interface CodeUnitEdges {
  state: 'ready' | 'unavailable';
  reason?: string;
  message?: string;
  unit?: string;
  imports: CodeUnitEdge[];
  imported_by: CodeUnitEdge[];
}

export interface CodeUnits {
  // Every empty table has a reason. `indexed_no_summary` means the project is
  // indexed but holds no source the table recognises, which is not the same as
  // an empty index or an unreachable graph.
  state: 'ready' | 'indexed_no_summary' | 'empty_index' | 'unavailable';
  reason?: string;
  message?: string;
  total: number;
  shown: number;
  sampled?: boolean;
  fan_in_is_lower_bound?: boolean;
  code_units: CodeUnit[];
}

export interface CodeGraphNode {
  id: string;
  label: string;
  path: string;
  kind: 'file';
  fan_in: number | null;
  fan_out: number | null;
}

export interface CodeGraphEdge {
  source: string;
  target: string;
  relation: 'imports';
  count: number;
}

export interface CodeGraphSnapshot {
  state: 'ready' | 'indexed_no_summary' | 'empty_index' | 'unavailable';
  reason?: string;
  message?: string;
  total: { code_units: number; import_edges: number };
  rendered: { code_units: number; import_edges: number };
  truncated: boolean;
  sampled?: boolean;
  sample_reason?: string;
  nodes: CodeGraphNode[];
  edges: CodeGraphEdge[];
}

export interface CodeGraphNeighborhood {
  state: 'ready' | 'unavailable';
  reason?: string;
  message?: string;
  seed_id?: string;
  total_imports?: number;
  rendered_imports?: number;
  truncated?: boolean;
  nodes: CodeGraphNode[];
  edges: CodeGraphEdge[];
}
