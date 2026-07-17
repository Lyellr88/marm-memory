// Types for the MARM Console frontend. These mirror the REST contract of the
// external MARM dashboard backend (FastAPI, run separately by the user on
// localhost). This app does not implement or proxy that backend — it is a
// pure client against whatever base URL is configured in Settings.

export interface Overview {
  memory: {
    active_memories: number;
    compacted_sources: number;
    pending_compaction: number;
    staged_compaction: number;
    missing_embeddings: number;
    sessions: number;
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
  id: number;
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

export interface NotebookEntry {
  name: string;
  content: string;
  project: string | null;
  platform: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotebookInput {
  name: string;
  content: string;
  project?: string | null;
  platform?: string | null;
}

export interface SessionSummary {
  session_name: string;
  summary: string;
  entry_count: number;
  is_dirty: boolean;
  generated_at: string;
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
  status: 'queued' | 'running' | 'success' | 'error' | 'degraded';
  memories_processed: number;
  entities_extracted: number;
  relationships_created: number;
  code_links_created: number;
  duplicate_candidates: number;
  duration_ms: number | null;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ConceptsSummary {
  entities: number;
  relationships: number;
  code_links: number;
  by_type: { type: string; count: number }[];
  by_project: { project: string; count: number }[];
  recent_builds: ConceptBuildRun[];
}

export interface ConceptEntity {
  id: number;
  name: string;
  type: string;
  session_name: string | null;
  project: string | null;
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
}

export interface Neighborhood {
  seed_id: number | null;
  nodes: NeighborhoodNode[];
  edges: NeighborhoodEdge[];
  limits: { nodes: number; edges: number };
  truncated: boolean;
}

export interface DuplicateCandidate {
  entity_a: ConceptEntity;
  entity_b: ConceptEntity;
  similarity: number;
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

export interface ProjectArchitecture {
  name: string;
  modules: { name: string; file_count: number; node_count: number }[];
  schema: { node_types: string[]; edge_types: string[] };
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
