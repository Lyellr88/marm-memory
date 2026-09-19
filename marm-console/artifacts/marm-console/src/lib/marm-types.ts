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

export interface MaintenanceAction {
  runnable: boolean;
  command: string | null;
  reason?: string;
}

export interface MaintenanceStatus {
  status: string;
  http_server_running: boolean;
  actions: Record<'compaction_dry_run' | 'reload_docs' | 'embeddings_migrate' | 'chunks_rechunk', MaintenanceAction>;
}

export interface DoctorCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface DoctorStatus {
  status: string;
  checks: DoctorCheck[];
}

export interface RuntimeLogs {
  status: string;
  path: string;
  exists: boolean;
  lines: string[];
}

export interface UpgradeCheck {
  status: string;
  installed_version: string;
  latest_version: string;
  state: 'current' | 'update_available' | string;
  installer: string | null;
  editable: boolean;
  command: string;
}

export interface BackupItem {
  name: string;
  size_bytes: number;
  created_at: string;
}

export interface BackupList {
  status: string;
  directory: string;
  items: BackupItem[];
}

export interface ReloadDocsJob {
  job_id: string;
  kind: 'reload_docs';
  status: 'queued' | 'running' | 'success' | 'error';
  message: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface CompactionDryRunJob {
  job_id: string;
  status: 'queued' | 'running' | 'success' | 'error';
  session_name: string;
  candidates: Array<Record<string, unknown>>;
  report_path: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export type RuntimeProfile = 'standard' | 'swarm' | 'swarm-max' | 'trusted';

export interface RuntimeProfileResult {
  status: string;
  profile: RuntimeProfile;
  requested_profile: RuntimeProfile;
  mode: string;
  persistence: 'saved' | 'until_restart';
  rate_limit: RuntimeSettings['rate_limit'];
  write_queue_enabled: boolean;
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
    dimension: number;
    marker: string | null;
    compatible: boolean;
    incompatible_vectors: number;
    errors: string[];
  };
  rate_limit: {
    requests_per_minute: number;
    window_seconds: number;
    block_seconds: number;
    enforced: boolean;
    environment_default: number;
  };
  search: {
    semantic_enabled: boolean;
    semantic_available: boolean;
    model_state: 'loaded' | 'loading' | 'failed' | 'not_loaded';
  };
  llm?: LocalLlmStatus;
  hardware?: HardwareStatus;
}

/** One accelerator, as its own vendor tool describes it.
 *
 *  `unified` is load-bearing rather than cosmetic: on Apple Silicon the GPU
 *  shares one pool with the CPU, so `memory_total_mb` is the whole machine's
 *  RAM and there is no free-VRAM figure to give. Rendering that the same way
 *  as a discrete card tells a Mac owner they have 64 GB to spend on weights.
 */
export interface GpuInfo {
  index: number;
  vendor: string;
  name: string;
  memory_total_mb: number | null;
  memory_used_mb: number | null;
  memory_free_mb: number | null;
  utilisation_percent: number | null;
  driver: string | null;
  unified: boolean;
}

export interface HardwareStatus {
  gpus: GpuInfo[];
  platform: string;
  detected: boolean;
}

export interface ServedModel {
  id: string | null;
  path?: string | null;
  state?: string | null;
}

/** The optional local generative model, and what can actually be changed.
 *
 *  `can_switch` is not a capability MARM chose; it is what the detected
 *  runtime was measured to do. llama.cpp accepts a `model` parameter and
 *  ignores it, so a picker rendered without consulting this would report a
 *  swap that never happened.
 */
export interface LocalLlmStatus {
  configured: boolean;
  enabled: boolean;
  endpoint: string | null;
  available: boolean;
  /** What would answer. Present even while switched off, so the pane that
   *  turns it back on can say what it would turn on. */
  model: string | null;
  /** What IS answering. Null whenever generation is off. */
  model_in_use: string | null;
  preferred_model: string | null;
  loopback_enforced: boolean;
  runtime: string | null;
  runtime_version: string | null;
  can_switch: boolean;
  model_path: string | null;
  context_length: number | null;
  served: ServedModel[];
  switch_blocked_reason: string | null;
  /** WHICH RULE chose `endpoint`, which is not the same as what it chose.
   *
   *  `flag` and `environment` mean somebody stated this address; `discovery`
   *  means nothing answered at the stated one and MARM fell back to whatever
   *  is running. A picker that cannot tell those apart shows an auto-selected
   *  server as "in use" and disables it, while the banner above still asks the
   *  reader to pick one — telling them to do something the UI forbids. */
  endpoint_source?: 'flag' | 'environment' | 'discovery' | 'default';
  source?: string;
  rejected?: string;
  applied_model?: string;
}

/** A local OpenAI-compatible server found by scanning loopback ports.
 *
 *  `expected` is which runtime that port conventionally belongs to; `runtime`
 *  is what actually answered. They can differ — anyone may run llama.cpp on
 *  1234 — and the pane shows what answered.
 */
export interface DiscoveredServer {
  url: string;
  port: number;
  expected: string;
  runtime: string;
  version: string | null;
  can_switch: boolean;
  model_count: number;
  models: string[];
  model_path: string | null;
  context_length: number | null;
}

export interface LlmServersResponse {
  servers: DiscoveredServer[];
  configured: string | null;
  configured_reachable: boolean;
  scanned_ports: number[];
  scan_seconds: number;
}

export interface DiscoveredModel {
  name: string;
  path: string;
  size_bytes: number | null;
  source: string;
  format: string;
  root: string;
  shards?: number;
  /** The id this runtime would accept for it, or null when the runtime has
   *  never seen this file and so cannot load it by name. Decides whether the
   *  row in "Models on this machine" is clickable. */
  served_id?: string | null;
}

export interface ModelRoot {
  source: string;
  path: string;
  exists: boolean;
  configured: boolean;
}

export interface LlmModelsResponse {
  runtime: string | null;
  can_switch: boolean;
  switch_blocked_reason: string | null;
  served: ServedModel[];
  model_in_use: string | null;
  preferred_model: string | null;
  models: DiscoveredModel[];
  roots: ModelRoot[];
  total: number;
  truncated: boolean;
  scan_seconds: number;
  note?: string;
}

export interface BrowseEntry {
  name: string;
  path: string;
  kind: 'directory' | 'model';
  size_bytes?: number | null;
}

export interface LlmBrowseResponse {
  roots: string[];
  path: string | null;
  parent: string | null;
  entries: BrowseEntry[];
  error?: string;
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

export type CodeSearchKind = 'auto' | 'symbol' | 'text' | 'snippet';

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
  answer_status?: 'ok' | 'unavailable' | 'failed';
  answer_hint?: string;
  answer_model?: string;
  /** Only symbols that are actually in the context; an invented name is
   *  dropped server-side rather than rendered as a dead link. */
  answer_citations?: CodeContextCitation[];
}

export interface CodeContextCitation {
  name: string;
  qualified_name: string;
  file_path: string;
  start_line: number;
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
}

export interface DistillResult {
  status: 'success';
  /** `propose` returns proposals; `review` returns pending. Never both. */
  proposals?: DistillProposal[];
  pending?: DistillProposal[];
  count?: number;
  extracted?: number;
  staged?: number;
  session_name?: string;
  memory_id?: string;
  proposal_id?: string;
  /** Present when nothing read as durable -- a success, not a failure. */
  note?: string;
  /** Which extraction path ran. `selected` means no local model was reachable. */
  mode?: 'generated' | 'selected';
}

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
