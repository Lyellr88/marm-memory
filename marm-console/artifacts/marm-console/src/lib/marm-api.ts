// Thin typed fetch client for the local MARM Console REST API.
// The backend is the user's own Console API process running locally (default
// http://127.0.0.1:8002, configurable in Settings). Every call here targets
// `${baseUrl}/api/...` per the documented contract. If that backend is not
// reachable, calls will fail and callers must render loading /
// error / empty states rather than assuming data exists.

import type {
  BulkLogDeleteResult,
  BulkNotebookDeleteResult,
  BulkSessionDeleteResult,
  CodeSearchInput,
  CodeSearchResult,
  CompactionAction,
  CompactionCandidate,
  ConceptBuildInput,
  ConceptBuildRun,
  ConceptAtlas,
  ConceptDetail,
  ConceptEntity,
  ConceptGraphParams,
  ConceptGraphVersion,
  ConceptReviewResult,
  ConceptSearchParams,
  ConceptsSummary,
  DuplicateReport,
  DuplicatePairInput,
  Filters,
  ImpactInput,
  ImpactResult,
  MergeDuplicateInput,
  GraphQueryInput,
  GraphQueryResult,
  IndexJob,
  LogListParams,
  LogListResponse,
  Memory,
  MemoryDeleteResult,
  MemoryId,
  MemoryInput,
  MemoryListParams,
  MemoryListResponse,
  Neighborhood,
  NotebookEntry,
  NotebookDeleteRef,
  NotebookInput,
  Overview,
  ProjectArchitecture,
  ProjectAdr,
  ProjectCoverage,
  CodeUnits,
  ProjectIndexInput,
  ProjectStatus,
  ProjectSummary,
  RuntimeSettings,
  RuntimeTrace,
  Session,
  SessionSummary,
  TraceInput,
  TraceResult,
} from './marm-types';

export class MarmApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'MarmApiError';
    this.status = status;
  }
}

export interface MarmClientConfig {
  baseUrl: string;
  apiKey: string | null;
}

function buildQuery(params: object | null | undefined): string {
  if (!params) return '';
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    usp.set(key, String(value));
  }
  const qs = usp.toString();
  return qs ? `?${qs}` : '';
}

async function request<T>(
  config: MarmClientConfig,
  method: string,
  path: string,
  opts?: { query?: object; body?: unknown; timeoutMs?: number },
): Promise<T> {
  const url = `${config.baseUrl}/api${path}${buildQuery(opts?.query)}`;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (opts?.body !== undefined) headers['Content-Type'] = 'application/json';
  if (config.apiKey) headers.Authorization = `Bearer ${config.apiKey}`;

  const controller = new AbortController();
  const timeoutMs = opts?.timeoutMs ?? 30000;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: opts?.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: controller.signal,
      credentials: 'same-origin',
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new MarmApiError(0, `Request to MARM server timed out after ${timeoutMs / 1000}s`);
    }
    throw new MarmApiError(0, `Could not reach MARM server at ${config.baseUrl}`);
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    let message = res.statusText;
    try {
      const data = await res.json();
      message = data?.error ?? data?.detail ?? message;
    } catch {
      // ignore body parse errors
    }
    throw new MarmApiError(res.status, message || `Request failed (${res.status})`);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function createMarmClient(config: MarmClientConfig) {
  return {
    // Overview & runtime
    getOverview: () => request<Overview>(config, 'GET', '/overview'),
    getFilters: () => request<Filters>(config, 'GET', '/filters'),

    // Memory
    listMemories: (params?: MemoryListParams) =>
      request<MemoryListResponse>(config, 'GET', '/memories', { query: params }),
    getMemory: (id: MemoryId) => request<Memory>(config, 'GET', `/memories/${id}`),
    createMemory: (data: MemoryInput) =>
      request<Memory>(config, 'POST', '/memories', { body: data }),
    updateMemory: (id: MemoryId, data: MemoryInput) =>
      request<Memory>(config, 'PUT', `/memories/${id}`, { body: data }),
    deleteMemory: (id: MemoryId) =>
      request<MemoryDeleteResult>(config, 'DELETE', `/memories/${id}`, { body: { confirm: 'DELETE' } }),
    bulkDeleteMemories: (ids: MemoryId[]) =>
      request<MemoryDeleteResult>(config, 'POST', '/memories/bulk-delete', {
        body: { memory_ids: ids.map(String), confirm: 'DELETE' },
      }),

    // Sessions / logs / notebook / summary
    listSessions: () => request<Session[]>(config, 'GET', '/sessions'),
    createSession: (name: string) =>
      request<{ name: string; active: boolean; status: string }>(config, 'POST', '/sessions', { body: { name } }),
    deleteSession: (name: string) =>
      request<{ session_name: string; deleted_count: number; memories_deleted: number }>(
        config,
        'DELETE',
        `/sessions/${encodeURIComponent(name)}`,
        { body: { confirm: 'DELETE' } },
      ),
    bulkDeleteSessions: (names: string[]) =>
      request<BulkSessionDeleteResult>(config, 'POST', '/sessions/bulk-delete', {
        body: { session_names: names, confirm: 'DELETE' },
      }),
    deleteAllSessions: () =>
      request<BulkSessionDeleteResult>(
        config,
        'DELETE',
        '/sessions',
        { body: { confirm: 'DELETE_ALL' } },
      ),
    listLogs: (params?: LogListParams) =>
      request<LogListResponse>(config, 'GET', '/logs', { query: params }),
    deleteLog: (id: string, sessionName: string) =>
      request<{ log_id: string; session_name: string; deleted_count: number; memories_deleted: number }>(
        config,
        'DELETE',
        `/logs/${encodeURIComponent(id)}`,
        { body: { session_name: sessionName, confirm: 'DELETE' } },
      ),
    bulkDeleteLogs: (logs: Array<{ id: string; session_name: string }>) =>
      request<BulkLogDeleteResult>(config, 'POST', '/logs/bulk-delete', {
        body: { logs, confirm: 'DELETE' },
      }),
    deleteAllLogs: () =>
      request<{ deleted_count: number; memories_deleted: number }>(
        config,
        'DELETE',
        '/logs',
        { body: { confirm: 'DELETE_ALL' } },
      ),
    listNotebook: (params?: { q?: string; session_name?: string; project?: string; platform?: string }) =>
      request<NotebookEntry[]>(config, 'GET', '/notebook', { query: params }),
    upsertNotebook: (data: NotebookInput) =>
      request<NotebookEntry>(config, 'POST', '/notebook', { body: data }),
    deleteNotebookEntry: (name: string, params?: { session_name?: string; project?: string; platform?: string }) =>
      request<{ name: string; deleted: boolean }>(config, 'DELETE', `/notebook/${encodeURIComponent(name)}`, {
        body: {
          confirm: 'DELETE',
          session_name: params?.session_name,
          project: params?.project,
          platform: params?.platform,
        },
      }),
    bulkDeleteNotebookEntries: (entries: NotebookDeleteRef[]) =>
      request<BulkNotebookDeleteResult>(config, 'POST', '/notebook/bulk-delete', {
        body: { entries, confirm: 'DELETE' },
      }),
    getSummary: (session: string) =>
      request<SessionSummary>(config, 'GET', `/summaries/${encodeURIComponent(session)}`),
    generateSummary: (session: string) =>
      request<SessionSummary>(config, 'POST', `/summaries/${encodeURIComponent(session)}/generate`),

    // Compaction
    listCompaction: () => request<CompactionCandidate[]>(config, 'GET', '/compaction'),
    runCompactionAction: (candidateId: string, action: CompactionAction) =>
      request<CompactionCandidate>(config, 'POST', `/compaction/${candidateId}/${action}`),

    // Concepts / knowledge graph
    getConceptsSummary: () => request<ConceptsSummary>(config, 'GET', '/concepts/summary'),
    searchConcepts: (params?: ConceptSearchParams) =>
      request<ConceptEntity[]>(config, 'GET', '/concepts/search', { query: params }),
    getConcept: (entityId: number) =>
      request<ConceptDetail>(config, 'GET', `/concepts/${entityId}`),
    getConceptGraph: (params?: ConceptGraphParams) =>
      request<ConceptAtlas>(config, 'GET', '/concepts/graph', { query: params }),
    getConceptGraphVersion: () =>
      request<ConceptGraphVersion>(config, 'GET', '/concepts/graph/version'),
    getConceptNeighborhood: (
      entityId: number,
      params?: { depth?: number; direction?: string; predicate?: string },
    ) =>
      request<Neighborhood>(config, 'GET', `/concepts/${entityId}/neighborhood`, { query: params }),
    buildConcepts: (data: ConceptBuildInput) =>
      request<{ job_id: string }>(config, 'POST', '/concepts/build', { body: data }),
    listConceptBuilds: () =>
      request<ConceptBuildRun[]>(config, 'GET', '/concepts/builds'),
    getConceptBuild: (jobId: string) =>
      request<ConceptBuildRun>(config, 'GET', `/concepts/builds/${jobId}`),
    stopConceptBuild: (jobId: string) =>
      request<{ status: 'cancellation_requested'; run_id: string; cancel_requested_at: string }>(
        config, 'POST', `/concepts/builds/${jobId}/stop`, { body: {} },
      ),
    retryConceptBuild: (jobId: string) =>
      request<{ job_id: string }>(config, 'POST', `/concepts/builds/${jobId}/retry`, { body: {} }),
    deleteConceptGraph: () =>
      request<{ status: 'reset'; backup_created: boolean; schema_status: 'rebuild_required' }>(
        config, 'DELETE', '/concepts/graph', { body: { confirm: 'DELETE_GRAPH' }, timeoutMs: 60000 },
      ),
    getConceptDuplicates: (params?: { offset?: number; limit?: number }) =>
      request<DuplicateReport>(config, 'GET', `/concepts/duplicates${buildQuery(params)}`),
    dismissConceptDuplicate: (data: DuplicatePairInput) =>
      request<ConceptReviewResult>(config, 'POST', '/concepts/duplicates/dismiss', { body: data }),
    mergeConceptDuplicate: (data: MergeDuplicateInput) =>
      request<ConceptReviewResult>(config, 'POST', '/concepts/duplicates/merge', { body: data }),
    removeConceptEntity: (entityId: number) =>
      request<ConceptReviewResult>(config, 'DELETE', `/concepts/entities/${entityId}`),

    // Runtime settings
    getRuntimeSettings: () => request<RuntimeSettings>(config, 'GET', '/settings/runtime'),
    updateRuntimeAutomation: (scope: 'graph' | 'concept', enabled: boolean) =>
      request<{ status: string; scope: 'graph' | 'concept'; enabled: boolean; effective: string }>(
        config, 'PUT', '/settings/automation', { body: { scope, enabled } },
      ),

    // Projects / code graph
    listProjects: () => request<ProjectSummary[]>(config, 'GET', '/projects'),
    indexProject: (data: ProjectIndexInput) =>
      request<{ job_id: string }>(config, 'POST', '/projects/index', { body: data }),
    getIndexJob: (jobId: string) =>
      request<IndexJob>(config, 'GET', `/projects/jobs/${jobId}`),
    getProjectStatus: (project: string) =>
      request<ProjectStatus>(config, 'GET', `/projects/${encodeURIComponent(project)}/status`),
    getProjectCoverage: (project: string) =>
      request<ProjectCoverage>(config, 'GET', `/projects/${encodeURIComponent(project)}/coverage`),
    queryProjectGraph: (project: string, data: GraphQueryInput) =>
      request<GraphQueryResult>(config, 'POST', `/projects/${encodeURIComponent(project)}/query`, { body: data }),
    getProjectAdr: (project: string) =>
      request<ProjectAdr>(config, 'GET', `/projects/${encodeURIComponent(project)}/adr`),
    updateProjectAdr: (project: string, content: string) =>
      request<ProjectAdr>(config, 'PUT', `/projects/${encodeURIComponent(project)}/adr`, { body: { content } }),
    ingestProjectRuntimeTraces: (project: string, traces: RuntimeTrace[]) =>
      request<{ status: string; ingested?: number }>(config, 'POST', `/projects/${encodeURIComponent(project)}/runtime-traces`, { body: { traces } }),
    getProjectArchitecture: (project: string) =>
      request<ProjectArchitecture>(config, 'GET', `/projects/${encodeURIComponent(project)}/architecture`),
    getProjectCodeUnits: (project: string) =>
      request<CodeUnits>(config, 'GET', `/projects/${encodeURIComponent(project)}/code-units`),
    searchProjectCode: (project: string, data: CodeSearchInput) =>
      request<CodeSearchResult[]>(config, 'POST', `/projects/${encodeURIComponent(project)}/search`, { body: data }),
    traceProject: (project: string, data: TraceInput) =>
      request<TraceResult>(config, 'POST', `/projects/${encodeURIComponent(project)}/trace`, { body: data }),
    projectImpact: (project: string, data: ImpactInput) =>
      request<ImpactResult>(config, 'POST', `/projects/${encodeURIComponent(project)}/impact`, { body: data }),
    deleteProject: (project: string, name: string) =>
      request<void>(config, 'DELETE', `/projects/${encodeURIComponent(project)}`, {
        body: { name, confirm: true },
      }),
  };
}

export type MarmClient = ReturnType<typeof createMarmClient>;
