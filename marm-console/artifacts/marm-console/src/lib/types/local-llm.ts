import type { AnalystProfileName, AnswerProfile } from './code-context';

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
  /** Which analyst profile bounds an answer. Chosen by the operator, never
   *  inferred from the model being served. */
  analyst_profile?: {
    name: AnalystProfileName;
    source: 'runtime' | 'environment' | 'default';
    profiles: Record<AnalystProfileName, AnswerProfile>;
    active: AnswerProfile;
  };
  /** Whether Guardrails may apply provable results without review. Off unless
   *  the operator turns it on; `unknown` when the saved switch is unreadable,
   *  in which case nothing is applied. */
  analyst_auto_apply?: {
    enabled: boolean;
    source: 'override' | 'environment' | 'unknown';
  };
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
