// Thin typed fetch client for the external MARM dashboard REST API.
// The backend is NOT part of this workspace — it is the user's own
// marm-mcp-server / marm-dashboard process running locally (default
// http://127.0.0.1:8002, configurable in Settings). Every call here targets
// `${baseUrl}/api/...` per the documented contract. Until that backend is
// wired up and reachable, calls will fail — callers must render loading /
// error / empty states rather than assuming data exists.

import type {
  CodeSearchInput,
  CodeSearchResult,
  CompactionAction,
  CompactionCandidate,
  ConceptBuildInput,
  ConceptBuildRun,
  ConceptDetail,
  ConceptEntity,
  ConceptSearchParams,
  ConceptsSummary,
  DuplicateCandidate,
  Filters,
  ImpactInput,
  ImpactResult,
  IndexJob,
  LogEntry,
  LogListParams,
  Memory,
  MemoryId,
  MemoryInput,
  MemoryListParams,
  MemoryListResponse,
  Neighborhood,
  NotebookEntry,
  NotebookInput,
  Overview,
  ProjectArchitecture,
  ProjectIndexInput,
  ProjectStatus,
  ProjectSummary,
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
  opts?: { query?: object; body?: unknown },
): Promise<T> {
  const url = `${config.baseUrl}/api${path}${buildQuery(opts?.query)}`;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (opts?.body !== undefined) headers['Content-Type'] = 'application/json';
  if (config.apiKey) headers.Authorization = `Bearer ${config.apiKey}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: opts?.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new MarmApiError(0, 'Request to MARM server timed out after 30s');
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
    updateMemory: (id: MemoryId, data: Partial<MemoryInput>) =>
      request<Memory>(config, 'PUT', `/memories/${id}`, { body: data }),
    deleteMemory: (id: MemoryId) => request<void>(config, 'DELETE', `/memories/${id}`),
    bulkDeleteMemories: (ids: MemoryId[]) =>
      request<void>(config, 'POST', '/memories/bulk-delete', { body: { ids, confirm: true } }),

    // Sessions / logs / notebook / summary
    listSessions: () => request<Session[]>(config, 'GET', '/sessions'),
    listLogs: (params?: LogListParams) =>
      request<LogEntry[]>(config, 'GET', '/logs', { query: params }),
    listNotebook: (params?: { q?: string; project?: string; platform?: string }) =>
      request<NotebookEntry[]>(config, 'GET', '/notebook', { query: params }),
    upsertNotebook: (data: NotebookInput) =>
      request<NotebookEntry>(config, 'POST', '/notebook', { body: data }),
    deleteNotebookEntry: (name: string, params?: { project?: string; platform?: string }) =>
      request<void>(config, 'DELETE', `/notebook/${encodeURIComponent(name)}`, { query: params }),
    getSummary: (session: string) =>
      request<SessionSummary>(config, 'GET', `/summaries/${encodeURIComponent(session)}`),

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
    getConceptGraph: (params?: { limit?: number }) =>
      request<Neighborhood>(config, 'GET', '/concepts/graph', { query: params }),
    getConceptNeighborhood: (
      entityId: number,
      params?: { depth?: number; direction?: string; predicate?: string },
    ) =>
      request<Neighborhood>(config, 'GET', `/concepts/${entityId}/neighborhood`, { query: params }),
    buildConcepts: (data: ConceptBuildInput) =>
      request<{ job_id: string }>(config, 'POST', '/concepts/build', { body: data }),
    getConceptBuild: (jobId: string) =>
      request<ConceptBuildRun>(config, 'GET', `/concepts/builds/${jobId}`),
    getConceptDuplicates: () =>
      request<DuplicateCandidate[]>(config, 'GET', '/concepts/duplicates'),

    // Projects / code graph
    listProjects: () => request<ProjectSummary[]>(config, 'GET', '/projects'),
    indexProject: (data: ProjectIndexInput) =>
      request<{ job_id: string }>(config, 'POST', '/projects/index', { body: data }),
    getIndexJob: (jobId: string) =>
      request<IndexJob>(config, 'GET', `/projects/jobs/${jobId}`),
    getProjectStatus: (project: string) =>
      request<ProjectStatus>(config, 'GET', `/projects/${encodeURIComponent(project)}/status`),
    getProjectArchitecture: (project: string) =>
      request<ProjectArchitecture>(config, 'GET', `/projects/${encodeURIComponent(project)}/architecture`),
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
