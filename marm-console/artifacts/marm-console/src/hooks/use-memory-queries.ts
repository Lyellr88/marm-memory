import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { MemoryListParams, MemoryInput, MemoryId, LogListParams, NotebookDeleteRef, NotebookInput, CompactionAction } from '@/lib/marm-types';
import { queryKeys, useMarmConfig } from './marm-query-core';

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
export function useMemories(params?: MemoryListParams, enabled = true) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.memories(baseUrl, params), queryFn: () => client.listMemories(params), enabled });
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

export function useBulkDeleteSessions() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (names: string[]) => client.bulkDeleteSessions(names),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.sessions(baseUrl) });
      qc.invalidateQueries({ queryKey: ['logs', baseUrl] });
      qc.invalidateQueries({ queryKey: ['memories', baseUrl] });
      qc.invalidateQueries({ queryKey: queryKeys.filters(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.overview(baseUrl) });
    },
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
    mutationFn: ({ id, sessionName }: { id: string; sessionName: string }) => client.deleteLog(id, sessionName),
    onSuccess: invalidate,
  });
}

export function useBulkDeleteLogs() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (logs: Array<{ id: string; session_name: string }>) => client.bulkDeleteLogs(logs),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['logs', baseUrl] });
      qc.invalidateQueries({ queryKey: ['memories', baseUrl] });
      qc.invalidateQueries({ queryKey: queryKeys.sessions(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.overview(baseUrl) });
    },
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

export function useGenerateSummary() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (session: string) => client.generateSummary(session),
    onSuccess: (summary) => {
      qc.setQueryData(queryKeys.summary(baseUrl, summary.session_name), summary);
      qc.invalidateQueries({ queryKey: queryKeys.sessions(baseUrl) });
    },
  });
}

export function useBulkDeleteNotebook() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (entries: NotebookDeleteRef[]) => client.bulkDeleteNotebookEntries(entries),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notebook', baseUrl] }),
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
