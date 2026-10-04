export type AgentTransport = 'http' | 'stdio' | 'docker-stdio';
export type AgentScopeName = 'user' | 'project';
export type AgentState = 'missing' | 'configured' | 'different' | 'unreadable';
export type AgentAction = 'create' | 'add' | 'replace' | 'none';

export interface AgentScopeState {
  scope: AgentScopeName;
  project?: string | null;
  config_path: string | null;
  config_exists: boolean;
  state: AgentState;
  transport_detected: AgentTransport | null;
  current_entry: Record<string, unknown> | null;
}

export interface Agent {
  id: string;
  label: string;
  detected: boolean;
  transports: AgentTransport[];
  scopes: AgentScopeName[];
  user: AgentScopeState;
  skill: { supported: boolean; installed: boolean };
  notes: string[];
  unavailable: Partial<Record<AgentTransport, string>>;
}

export interface AgentsResponse {
  auth_required: boolean;
  configure_allowed: boolean;
  configure_blocked_reason: string | null;
  clients: Agent[];
}

export type AgentTarget = 'docker';

export interface AgentConfigureBody {
  transport: AgentTransport;
  scope: AgentScopeName;
  project?: string;
  target?: AgentTarget;
  dry_run: boolean;
}

export interface AgentConfigureResult {
  client: string;
  transport: AgentTransport;
  scope: AgentScopeName;
  config_path: string | null;
  action: AgentAction;
  entry: Record<string, unknown> | null;
  backup_path: string | null;
  method: 'file' | 'cli';
  notes: string[];
  written?: boolean;
  verified?: boolean;
}

export interface AgentRemoveBody {
  scope: AgentScopeName;
  project?: string;
  target?: AgentTarget;
  dry_run: boolean;
}

export interface AgentRemoveResult {
  client: string;
  config_path: string | null;
  action: 'remove' | 'none';
  backup_path: string | null;
  method: 'file' | 'cli';
  written?: boolean;
  verified?: boolean;
}

export interface AgentTestBody {
  scope: AgentScopeName;
  project?: string;
  target?: AgentTarget;
}

export type AgentTestErrorKind = 'refused' | 'timeout' | 'unauthorized' | 'protocol' | 'missing_entry' | 'spawn_failed' | 'unsupported';

export interface AgentTestResult {
  ok: boolean;
  transport: AgentTransport | null;
  tools: number | null;
  latency_ms: number | null;
  error: { kind: AgentTestErrorKind; detail: string } | null;
}

export interface AgentSkillResult {
  state: 'installed' | 'refreshed' | 'error';
  target: string | null;
  detail?: string | null;
}

export interface ConnectionsChecklistItem {
  id: string;
  label: string;
  done: boolean;
  detail: string;
}

export interface ConnectionsOverview {
  version: string;
  os: string;
  runtime: { state: string; managed: boolean; url: string; profile: string };
  auth: { mode: string; key_file_exists: boolean };
  agents: { connected: number; detected: number };
  skills_installed: number;
  checklist: ConnectionsChecklistItem[];
}

export type SetupSettingValue = boolean | number | string;

export interface SetupSettingItem {
  key: string;
  label: string;
  help: string;
  type: 'bool' | 'int' | 'choice';
  choices?: string[];
  min?: number;
  max?: number;
  default: SetupSettingValue;
  value: SetupSettingValue;
  source: 'saved' | 'env' | 'default';
  overrides_env: boolean;
  live: false;
}

export interface SetupSettingsGroup {
  id: string;
  label: string;
  items: SetupSettingItem[];
}

export interface SetupSettings {
  path: string;
  groups: SetupSettingsGroup[];
  live: {
    profile: string;
    rate_limit_rpm: number;
    auto_index_graph: boolean;
    auto_index_concept: boolean;
    llm_enabled: boolean;
  };
}
