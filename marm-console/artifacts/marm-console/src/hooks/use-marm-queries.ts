import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useMarmClient } from '@/lib/use-marm-client';
import { useConnection } from '@/lib/marm-connection';
import type { 
  MemoryListParams, MemoryInput, MemoryId, LogListParams, NotebookInput,
  CompactionAction, ConceptSearchParams, ConceptBuildInput, 
  ProjectIndexInput, CodeSearchInput, TraceInput, ImpactInput
} from '@/lib/marm-types';
import { MarmApiError } from '@/lib/marm-api';

export const queryKeys = {
  overview: (baseUrl: string) => ['overview', baseUrl],
  filters: (baseUrl: string) => ['filters', baseUrl],
  memories: (baseUrl: string, params?: MemoryListParams) => ['memories', baseUrl, params],
  memory: (baseUrl: string, id: MemoryId) => ['memory', baseUrl, id],
  sessions: (baseUrl: string) => ['sessions', baseUrl],
  logs: (baseUrl: string, params?: LogListParams) => ['logs', baseUrl, params],
  notebook: (baseUrl: string, params?: any) => ['notebook', baseUrl, params],
  summary: (baseUrl: string, session: string) => ['summary', baseUrl, session],
  compaction: (baseUrl: string) => ['compaction', baseUrl],
  conceptsSummary: (baseUrl: string) => ['conceptsSummary', baseUrl],
  conceptsGraph: (baseUrl: string, params?: { limit?: number }) => ['conceptsGraph', baseUrl, params],
  conceptsSearch: (baseUrl: string, params?: ConceptSearchParams) => ['conceptsSearch', baseUrl, params],
  concept: (baseUrl: string, id: number) => ['concept', baseUrl, id],
  neighborhood: (baseUrl: string, id: number, params?: any) => ['neighborhood', baseUrl, id, params],
  conceptBuild: (baseUrl: string, id: string) => ['conceptBuild', baseUrl, id],
  duplicates: (baseUrl: string) => ['duplicates', baseUrl],
  projects: (baseUrl: string) => ['projects', baseUrl],
  indexJob: (baseUrl: string, id: string) => ['indexJob', baseUrl, id],
  projectStatus: (baseUrl: string, project: string) => ['projectStatus', baseUrl, project],
  projectArchitecture: (baseUrl: string, project: string) => ['projectArchitecture', baseUrl, project],
};

// Global config hook
export function useMarmConfig() {
  const { baseUrl } = useConnection();
  return { baseUrl, client: useMarmClient() };
}

// Check auth errors specifically
export function isAuthError(err: unknown) {
  return err instanceof MarmApiError && (err.status === 401 || err.status === 403);
}

// --- Overview ---
export function useOverview() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: queryKeys.overview(baseUrl),
    queryFn: client.getOverview,
    refetchInterval: (query) => query.state.error ? 15000 : 5000,
    retry: false
  });
}

export function useFilters() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.filters(baseUrl), queryFn: client.getFilters });
}

// --- Memory ---
export function useMemories(params?: MemoryListParams) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.memories(baseUrl, params), queryFn: () => client.listMemories(params) });
}

export function useMemory(id: MemoryId) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.memory(baseUrl, id), queryFn: () => client.getMemory(id), enabled: !!id });
}

export function useCreateMemory() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: MemoryInput) => client.createMemory(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memories', baseUrl] });
      qc.invalidateQueries({ queryKey: queryKeys.overview(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.filters(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.sessions(baseUrl) });
    }
  });
}

export function useUpdateMemory() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: MemoryId, data: MemoryInput }) => client.updateMemory(id, data),
    onSuccess: (res, vars) => {
      qc.invalidateQueries({ queryKey: ['memories', baseUrl] });
      qc.invalidateQueries({ queryKey: queryKeys.memory(baseUrl, vars.id) });
      qc.invalidateQueries({ queryKey: queryKeys.overview(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.filters(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.sessions(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.compaction(baseUrl) });
      qc.invalidateQueries({ queryKey: ['conceptsSummary', baseUrl] });
      qc.invalidateQueries({ queryKey: ['conceptsGraph', baseUrl] });
      qc.invalidateQueries({ queryKey: ['conceptsSearch', baseUrl] });
      qc.invalidateQueries({ queryKey: queryKeys.duplicates(baseUrl) });
    }
  });
}

export function useDeleteMemory() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: MemoryId) => client.deleteMemory(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memories', baseUrl] });
      qc.invalidateQueries({ queryKey: queryKeys.overview(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.filters(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.sessions(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.compaction(baseUrl) });
      qc.invalidateQueries({ queryKey: ['conceptsSummary', baseUrl] });
      qc.invalidateQueries({ queryKey: ['conceptsGraph', baseUrl] });
      qc.invalidateQueries({ queryKey: ['conceptsSearch', baseUrl] });
      qc.invalidateQueries({ queryKey: ['duplicates', baseUrl] });
    }
  });
}

export function useBulkDeleteMemories() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: MemoryId[]) => client.bulkDeleteMemories(ids),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memories', baseUrl] });
      qc.invalidateQueries({ queryKey: queryKeys.overview(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.filters(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.sessions(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.compaction(baseUrl) });
      qc.invalidateQueries({ queryKey: ['conceptsSummary', baseUrl] });
      qc.invalidateQueries({ queryKey: ['conceptsGraph', baseUrl] });
      qc.invalidateQueries({ queryKey: ['conceptsSearch', baseUrl] });
      qc.invalidateQueries({ queryKey: ['duplicates', baseUrl] });
    }
  });
}

// --- Sessions & Logs ---
export function useSessions() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.sessions(baseUrl), queryFn: client.listSessions });
}

export function useCreateSession() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => client.createSession(name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.sessions(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.filters(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.overview(baseUrl) });
    },
  });
}

export function useDeleteSession() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: queryKeys.sessions(baseUrl) });
    qc.invalidateQueries({ queryKey: ['logs', baseUrl] });
    qc.invalidateQueries({ queryKey: ['memories', baseUrl] });
    qc.invalidateQueries({ queryKey: queryKeys.filters(baseUrl) });
    qc.invalidateQueries({ queryKey: queryKeys.overview(baseUrl) });
  };
  return useMutation({
    mutationFn: (name: string) => client.deleteSession(name),
    onSuccess: invalidate,
  });
}

export function useDeleteAllSessions() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => client.deleteAllSessions(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.sessions(baseUrl) });
      qc.invalidateQueries({ queryKey: ['logs', baseUrl] });
      qc.invalidateQueries({ queryKey: ['memories', baseUrl] });
      qc.invalidateQueries({ queryKey: queryKeys.filters(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.overview(baseUrl) });
    },
  });
}

export function useLogs(params?: LogListParams) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.logs(baseUrl, params), queryFn: () => client.listLogs(params) });
}

export function useDeleteLog() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['logs', baseUrl] });
    qc.invalidateQueries({ queryKey: ['memories', baseUrl] });
    qc.invalidateQueries({ queryKey: queryKeys.sessions(baseUrl) });
    qc.invalidateQueries({ queryKey: queryKeys.overview(baseUrl) });
  };
  return useMutation({
    mutationFn: ({ id, sessionName }: { id: number; sessionName: string }) => client.deleteLog(id, sessionName),
    onSuccess: invalidate,
  });
}

export function useDeleteAllLogs() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => client.deleteAllLogs(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['logs', baseUrl] });
      qc.invalidateQueries({ queryKey: ['memories', baseUrl] });
      qc.invalidateQueries({ queryKey: queryKeys.sessions(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.overview(baseUrl) });
    },
  });
}

export function useSummary(session: string) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.summary(baseUrl, session), queryFn: () => client.getSummary(session), enabled: !!session });
}

// --- Notebook ---
export function useNotebook(params?: { q?: string; session_name?: string; project?: string; platform?: string }) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.notebook(baseUrl, params), queryFn: () => client.listNotebook(params) });
}

export function useUpsertNotebook() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: NotebookInput) => client.upsertNotebook(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notebook', baseUrl] })
  });
}

export function useDeleteNotebook() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, params }: { name: string, params?: { session_name?: string; project?: string; platform?: string } }) => client.deleteNotebookEntry(name, params),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notebook', baseUrl] })
  });
}

// --- Compaction ---
export function useCompaction() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.compaction(baseUrl), queryFn: client.listCompaction });
}

export function useRunCompactionAction() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string, action: CompactionAction }) => client.runCompactionAction(id, action),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['compaction', baseUrl] });
      qc.invalidateQueries({ queryKey: ['overview', baseUrl] });
    }
  });
}

// --- Knowledge ---
export function useConceptsSummary() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.conceptsSummary(baseUrl), queryFn: client.getConceptsSummary });
}

export function useSearchConcepts(params?: ConceptSearchParams) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.conceptsSearch(baseUrl, params), queryFn: () => client.searchConcepts(params) });
}

export function useConceptGraph(params?: { limit?: number }, enabled = true) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: queryKeys.conceptsGraph(baseUrl, params),
    queryFn: () => client.getConceptGraph(params),
    enabled,
  });
}

export function useConcept(id: number) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.concept(baseUrl, id), queryFn: () => client.getConcept(id), enabled: !!id });
}

export function useNeighborhood(id: number, params?: { depth?: number; direction?: string; predicate?: string }) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.neighborhood(baseUrl, id, params), queryFn: () => client.getConceptNeighborhood(id, params), enabled: !!id });
}

export function useBuildConcepts() {
  const { client } = useMarmConfig();
  return useMutation({ mutationFn: (data: ConceptBuildInput) => client.buildConcepts(data) });
}

export function useConceptBuild(jobId: string) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ 
    queryKey: queryKeys.conceptBuild(baseUrl, jobId), 
    queryFn: () => client.getConceptBuild(jobId), 
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return (status === 'queued' || status === 'running') ? 2000 : false;
    }
  });
}

export function useConceptDuplicates() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.duplicates(baseUrl), queryFn: client.getConceptDuplicates });
}

// --- Projects ---
export function useProjects() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.projects(baseUrl), queryFn: client.listProjects });
}

export function useIndexProject() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ProjectIndexInput) => client.indexProject(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects', baseUrl] }),
  });
}

export function useIndexJob(jobId: string) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ 
    queryKey: queryKeys.indexJob(baseUrl, jobId), 
    queryFn: () => client.getIndexJob(jobId), 
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return (status === 'queued' || status === 'running') ? 2000 : false;
    }
  });
}

export function useProjectStatus(project: string) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.projectStatus(baseUrl, project), queryFn: () => client.getProjectStatus(project), enabled: !!project });
}

export function useProjectArchitecture(project: string) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.projectArchitecture(baseUrl, project), queryFn: () => client.getProjectArchitecture(project), enabled: !!project });
}

export function useSearchProjectCode() {
  const { client } = useMarmConfig();
  return useMutation({ mutationFn: ({ project, data }: { project: string, data: CodeSearchInput }) => client.searchProjectCode(project, data) });
}

export function useTraceProject() {
  const { client } = useMarmConfig();
  return useMutation({ mutationFn: ({ project, data }: { project: string, data: TraceInput }) => client.traceProject(project, data) });
}

export function useProjectImpact() {
  const { client } = useMarmConfig();
  return useMutation({ mutationFn: ({ project, data }: { project: string, data: ImpactInput }) => client.projectImpact(project, data) });
}

export function useDeleteProject() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, name }: { project: string, name: string }) => client.deleteProject(project, name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects', baseUrl] })
  });
}
