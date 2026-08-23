// Types for the MARM Console frontend. These mirror the REST contract of the
// local MARM Console backend (FastAPI, run separately by the user on localhost).
// The frontend is a pure client against whatever base URL is configured in
// Settings.

export interface Overview {
  memory: {
    active_memories: number;
    compacted_sources: number;
    pending_compaction: number;
    staged_compaction: number;
    missing_embeddings: number;
    sessions: number;
    log_entries: number;
    notebook_entries: number;
    projects: string[];
    platforms: string[];
  };
  concepts: {
    status: 'unavailable' | 'not_built' | 'ready';
    entities: number;
    relationships: number;
    code_links: number;
    recent_builds: ConceptBuildRun[];
  };
  graph: {
    status: 'disabled' | 'starting' | 'ready' | 'error';
    projects: ProjectSummary[];
  };
  runtime_mode: 'embedded' | 'standalone';
  mcp_status?: McpStatus;
}

export interface McpStatus {
  reachable: boolean;
  version?: string;
  status?: string;
  latency_ms?: number;
  last_checked?: string;
}

export interface Filters {
  sessions: string[];
  projects: string[];
  platforms: string[];
  context_types: string[];
}

export type CompactionRole = 'none' | 'source' | 'summary';
export type MemoryId = string | number;

export interface Memory {
  id: MemoryId;
  content: string;
  session_name: string;
  project: string | null;
  platform: string | null;
  context_type: string | null;
  metadata: Record<string, unknown> | null;
  content_hash: string;
  created_at: string;
  compaction_role: CompactionRole;
  chunk_count: number;
  has_embedding: boolean;
  concept_link_count: number;
}

export interface MemoryListParams {
  q?: string;
  session?: string;
  project?: string;
  platform?: string;
  context_type?: string;
  compaction_role?: CompactionRole | 'compacted';
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export interface MemoryListResponse {
  items: Memory[];
  total: number;
  limit: number;
  offset: number;
}

export interface MemoryInput {
  content: string;
  session_name: string;
  context_type?: string | null;
  project?: string | null;
  platform?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface MemoryDeleteCleanup {
  status: 'success' | 'skipped' | 'failed' | string;
  reason?: string;
  error?: string;
  relationships_deleted?: number;
  entities_updated?: number;
  entities_deleted?: number;
}

export interface MemoryDeleteResult {
  deleted_ids: string[];
  missing_ids: string[];
  concept_cleanup?: MemoryDeleteCleanup;
  compaction_updates?: {
    staging_candidates_marked_stale?: number;
    summaries_updated?: number;
    sources_restored?: number;
  };
}

export interface Session {
  name: string;
  active: boolean;
  created_at: string;
  last_accessed_at: string;
  memory_count: number;
  log_count: number;
  compaction_count: number;
  projects: string[];
  platforms: string[];
}

export interface LogEntry {
  id: string;
  date: string;
  topic: string | null;
  summary: string | null;
  entry: string;
  session_name: string;
  project: string | null;
  platform: string | null;
}

export interface LogListParams {
  q?: string;
  session?: string;
  project?: string;
  platform?: string;
  topic?: string;
  limit?: number;
  offset?: number;
}

export interface RuntimeAutomationState {
  enabled: boolean;
  source: 'environment' | 'saved_override' | string;
  environment_default: boolean;
  suppressed_projects?: string[];
  unindexable_projects?: string[];
}

export interface RuntimeSettings {
  status: string;
  service: string;
  runtime_id: string | null;
  pid: number;
  version: string;
  profile: string;
  write_queue: {
    enabled: boolean;
    running: boolean;
    depth: number;
    capacity: number;
    stopping: boolean;
  };
  graph: { state?: string; [key: string]: unknown };
  automation: {
    graph: RuntimeAutomationState;
    concept: RuntimeAutomationState;
  };
  knowledge: {
    state: string;
    schema: string;
    index_queue: { pending: number | null; parked: number | null };
  };
  storage: {
    memory: { path?: string; exists: boolean; size_bytes?: number; [key: string]: unknown };
    concept: { path?: string; exists: boolean; size_bytes?: number; [key: string]: unknown };
  };
  embedding: {
    model: string;
    marker: string | null;
    compatible: boolean;
    incompatible_vectors: number;
    errors: string[];
  };
}

export interface LogListResponse {
  items: LogEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface NotebookEntry {
  name: string;
  content: string;
  session_name: string;
  project: string | null;
  platform: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotebookInput {
  name: string;
  content: string;
  session_name?: string;
  project?: string | null;
  platform?: string | null;
}

export interface NotebookDeleteRef {
  name: string;
  session_name: string;
  project: string | null;
  platform: string | null;
}

export interface BulkSessionDeleteResult {
  status: string;
  deleted_sessions: number;
  deleted_count: number;
  memories_deleted: number;
  failed_sessions: Array<{ session_name: string; status_code: number; message: string }>;
}

export interface BulkLogDeleteResult {
  status: string;
  deleted_count: number;
  memories_deleted: number;
  failed_logs: Array<{ log_id: string; session_name: string; status_code: number; message: string }>;
}

export interface BulkNotebookDeleteResult {
  status: string;
  deleted_entries: number;
  failed_entries: Array<NotebookDeleteRef & { status_code: number; message: string }>;
}

export interface SessionSummary {
  session_name: string;
  summary: string;
  entry_count: number;
  is_dirty: boolean;
  generated_at: string | null;
  status?: 'success' | 'empty';
  message?: string | null;
}

export type CompactionStatus =
  | 'pending'
  | 'staged'
  | 'applied'
  | 'discarded'
  | 'stale'
  | 'nudge_exhausted';

export interface CompactionCandidate {
  id: string;
  status: CompactionStatus;
  session_name: string;
  source_memory_ids: number[];
  proposed_summary: string;
  expected_reduction: number;
  expiry: string | null;
  created_at: string;
}

export type CompactionAction = 'stage' | 'apply' | 'discard';

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
  linked_code: { qualified_name: string; file_path: string }[];
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
  linked_code: { qualified_name: string; file_path: string }[];
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

export interface ProjectSummary {
  name: string;
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
  affected_symbols: { qualified_name: string; file_path: string; risk: 'low' | 'medium' | 'high' }[];
}
