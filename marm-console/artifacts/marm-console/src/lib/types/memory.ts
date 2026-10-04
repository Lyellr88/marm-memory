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
