import type { MemoryId } from './memory';

export interface ConceptBuildRun {
  id: string;
  scope_type: 'session' | 'project' | 'all';
  scope_value: string | null;
  status: 'queued' | 'running' | 'success' | 'error' | 'degraded' | 'cancelled';
  memories_processed: number;
  memories_total: number;
  entities_extracted: number;
  relationships_created: number;
  code_links_created: number;
  duplicate_candidates: number;
  duration_ms: number | null;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  last_progress_at?: string | null;
  cancel_requested_at: string | null;
  cancelled_at: string | null;
  finished_at: string | null;
}

/** Entity names the extractor would now store differently, e.g. names that
 *  predate its markdown cleanup. Read-only; `sample` is capped. */
export interface ConceptLegacyNames {
  count: number;
  checked: number;
  sample: string[];
}

export interface ConceptsSummary {
  entities: number;
  relationships: number;
  code_links: number;
  by_type: { type: string; count: number }[];
  by_project: { project: string; count: number }[];
  recent_builds: ConceptBuildRun[];
  schema_status?: 'current' | 'rebuild_required' | 'unavailable';
}

export interface ConceptEntity {
  id: number;
  name: string;
  type: string;
  session_name: string | null;
  project: string | null;
  platform: string | null;
  mention_count: number;
  degree: number;
  created_at: string;
}

export interface ConceptSourceMemory {
  id: MemoryId;
  content: string;
  session_name: string;
  project: string | null;
  created_at: string;
}

export interface ConceptDetail extends ConceptEntity {
  source_memory_ids: string[];
  source_memories: ConceptSourceMemory[];
  linked_code: ConceptCodeLink[];
}

export interface ConceptCodeLink {
  qualified_name: string;
  file_path: string;
  link_method: string;
  last_verified_at: string | null;
}

export interface ConceptSearchParams {
  q?: string;
  project?: string;
  session?: string;
  type?: string;
  limit?: number;
}

export interface NeighborhoodNode {
  id: number;
  name: string;
  type: string;
  session_name: string | null;
  project: string | null;
  mention_count: number;
  degree: number;
  hidden_neighbor_count: number;
  linked_code: ConceptCodeLink[];
}

export interface NeighborhoodEdge {
  id: number;
  source: number;
  target: number;
  predicate: string;
  memory_id: string | null;
  weight?: number;
  evidence_count?: number;
}

export interface Neighborhood {
  seed_id: number | null;
  nodes: NeighborhoodNode[];
  edges: NeighborhoodEdge[];
  limits: { nodes: number; edges: number };
  truncated: boolean;
}

export interface ConceptAtlas extends Neighborhood {
  mode: 'full' | 'sampled';
  schema_status: 'current' | 'rebuild_required' | 'unavailable';
  total: { nodes: number; edges: number; code_links: number };
  rendered: { nodes: number; edges: number };
  sample_reason: string | null;
}

export interface ProjectMemoryLinking {
  state: 'bound' | 'unbound' | 'ambiguous' | 'conflict';
  binding: {
    graph_project: string;
    memory_project: string;
    root_path: string;
    source: 'auto' | 'user';
    created_at: string;
    updated_at: string;
    last_verified_at: string;
  } | null;
  candidates: string[];
  refresh: {
    state: 'pending' | 'leased' | 'parked';
    attempts: number;
    last_error: string | null;
    enqueued_at: string;
  } | null;
  linked_entities: number;
}

export interface ProjectMemoryCodeLink {
  qualified_name: string;
  file_path: string;
  link_method: string;
  last_verified_at: string | null;
  entity_id: number;
  entity_name: string;
  entity_type: string;
}

export interface ConceptGraphParams {
  full?: boolean;
  project?: string;
  session?: string;
}

export type ConceptGraphScope =
  | { type: 'all' }
  | { type: 'project'; value: string }
  | { type: 'session'; value: string };

/** Cheap change marker polled while the Explorer is open. The value is opaque:
 *  compare it, do not parse it. */
export interface ConceptGraphVersion {
  schema_status: 'current' | 'rebuild_required' | 'unavailable';
  version: string;
}

export interface DuplicateCandidate {
  entity_a: ConceptEntity;
  entity_b: ConceptEntity;
  similarity: number;
}

export interface DuplicateReport {
  items: DuplicateCandidate[];
  total: number;
  threshold: number;
  scanned_entities: number;
  scan_limit: number;
  result_limit: number;
  offset: number;
  has_more: boolean;
}

export interface DuplicatePairInput {
  entity_a_id: number;
  entity_b_id: number;
}

export interface MergeDuplicateInput extends DuplicatePairInput {
  keep: 'a' | 'b';
}

export interface ConceptReviewResult {
  status: 'dismissed' | 'merged' | 'removed';
  kept_entity_id?: number;
  removed_entity_id?: number;
  canonical_name?: string;
}

export interface ConceptBuildInput {
  session_name?: string;
  project?: string;
  search_all?: boolean;
}
