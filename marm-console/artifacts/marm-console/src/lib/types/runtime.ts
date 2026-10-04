import type { HardwareStatus, LocalLlmStatus } from './local-llm';

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

export interface RuntimeRestartJob {
  status: 'queued' | 'running' | 'done' | 'error';
  seconds?: number;
  detail?: string;
}
