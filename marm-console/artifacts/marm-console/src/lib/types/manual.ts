import type { AgentScopeName, AgentTransport } from './connections';

export type ManualOs = 'windows' | 'macos' | 'linux';
export type ManualTarget = 'local' | 'docker';

export interface ManualSnippetParams {
  client: string;
  os: ManualOs;
  transport: AgentTransport;
  scope: AgentScopeName;
  target: ManualTarget;
}

export interface ManualSnippet {
  client: string;
  os: ManualOs;
  path: string;
  format: 'json' | 'toml' | 'yaml';
  text: string;
  notes: string | string[] | null;
}

export interface ManualAgentCommandParams {
  transport: AgentTransport;
  scope: AgentScopeName;
  target: ManualTarget;
}

export interface ManualAgentCommand {
  client: string;
  label: string;
  command: string | null;
  note: string;
}

export interface ManualCliArg {
  name: string;
  flag: string | null;
  kind: 'flag' | 'option' | 'positional';
  type: 'str' | 'int' | 'path';
  choices: string[] | null;
  default: string | number | boolean | null;
  required: boolean;
  help: string;
  repeatable: boolean;
  cli_only?: boolean;
  cli_only_reason?: string | null;
}

export interface ManualCliCommand {
  command: string;
  help: string;
  args: ManualCliArg[];
  cli_only: boolean;
  cli_only_reason: string | null;
}

export interface ManualRoute {
  method: string;
  path: string;
  summary: string;
  auth?: boolean | string | null;
}

export interface ManualEndpoints {
  mcp_url: string;
  runtime_available: boolean;
  reason: string | null;
  groups: Array<{ name: string; routes: ManualRoute[] }>;
  console: ManualRoute[];
}

export interface ManualEnvItem {
  name: string;
  group: string;
  default: string | null;
  current: string | null;
  source: 'saved' | 'env' | 'default';
  setting_key: string | null;
  description: string;
}
