import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { ProjectIndexInput, CodeSearchInput, CodeContextInput, DistillInput, TraceInput, ImpactInput } from '@/lib/marm-types';
import { IDLE_ANSWER, applyAnswerEvent, applyStreamEnd, type AnswerStreamState } from '@/lib/answer-stream';
import { queryKeys, useMarmConfig } from './marm-query-core';

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

export function useProjectCoverage(project: string) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: ['project-coverage', baseUrl, project], queryFn: () => client.getProjectCoverage(project), enabled: !!project });
}

export function useProjectArchitecture(project: string) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.projectArchitecture(baseUrl, project), queryFn: () => client.getProjectArchitecture(project), enabled: !!project });
}

export function useProjectCodeUnits(project: string) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.projectCodeUnits(baseUrl, project), queryFn: () => client.getProjectCodeUnits(project), enabled: !!project });
}

export function useProjectGraph(project: string, enabled = true) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: queryKeys.projectGraph(baseUrl, project),
    queryFn: () => client.getProjectGraph(project),
    enabled: !!project && enabled,
    // The bounded snapshot is immutable until MARM indexes the project again.
    // Index completion explicitly invalidates this key, so avoid rereading the
    // same graph whenever its tab remounts during one Console session.
    staleTime: Infinity,
  });
}

export function useProjectGraphNeighborhood(project: string, nodeId: string | null, enabled = true) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: queryKeys.projectGraphNeighborhood(baseUrl, project, nodeId || ''),
    queryFn: () => client.getProjectGraphNeighborhood(project, nodeId || ''),
    enabled: !!project && !!nodeId && enabled,
  });
}

export function useProjectCodeUnitEdges(project: string, unit: string | null, enabled = true) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: queryKeys.projectCodeUnitEdges(baseUrl, project, unit || ''),
    queryFn: () => client.getProjectCodeUnitEdges(project, unit || ''),
    enabled: !!project && !!unit && enabled,
  });
}

export function useProjectMemoryLinking(project: string) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: queryKeys.projectMemoryLinking(baseUrl, project),
    queryFn: () => client.getProjectMemoryLinking(project),
    enabled: !!project,
    refetchInterval: (query) => {
      const state = query.state.data?.refresh?.state;
      return state === 'pending' || state === 'leased' ? 3000 : false;
    },
  });
}

export function useProjectMemoryLinks(project: string, refreshPending = false) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: queryKeys.projectMemoryLinks(baseUrl, project),
    queryFn: () => client.getProjectMemoryLinks(project),
    enabled: !!project,
    refetchInterval: refreshPending ? 3000 : false,
  });
}

export function useConfirmProjectMemoryLinking() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, memoryProject }: { project: string; memoryProject: string }) =>
      client.confirmProjectMemoryLinking(project, memoryProject),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.projectMemoryLinking(baseUrl, variables.project) });
      qc.invalidateQueries({ queryKey: queryKeys.projectMemoryLinks(baseUrl, variables.project) });
      qc.invalidateQueries({ queryKey: queryKeys.conceptsGraph(baseUrl) });
    },
  });
}

export function useBuildCodeContext() {
  const { client } = useMarmConfig();
  return useMutation({ mutationFn: (data: CodeContextInput) => client.buildCodeContext(data) });
}

/** The review queue. Separate from the propose mutation on purpose: a reviewer
 *  arriving at the page has proposals waiting from an agent's own distil runs,
 *  and should not have to paste a transcript to see them. */
export function useDistillPending(sessionName?: string | null, enabled = true) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: queryKeys.distillPending(baseUrl, sessionName),
    queryFn: () => client.distill({ action: 'review', session_name: sessionName ?? null, limit: 200 }),
    enabled,
  });
}

export function useDistillPropose() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: DistillInput) => client.distill({ ...data, action: 'propose' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['distill-pending', baseUrl] }),
  });
}

/** Applying writes a memory, so the memory lists and counts are stale too --
 *  invalidating only the queue would leave the rest of the Console showing a
 *  store that no longer exists. */
export function useDistillApply() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (proposalId: string) => client.distill({ action: 'apply', proposal_id: proposalId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['distill-pending', baseUrl] });
      qc.invalidateQueries({ queryKey: ['memories', baseUrl] });
      qc.invalidateQueries({ queryKey: queryKeys.overview(baseUrl) });
    },
  });
}

export function useDistillDiscard() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (proposalId: string) => client.distill({ action: 'discard', proposal_id: proposalId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['distill-pending', baseUrl] }),
  });
}

/** A grounded answer, streamed.
 *
 *  Deliberately not react-query: this is not a request whose result is cached,
 *  it is a response that arrives over seconds and is rendered as it goes.
 *  Modelling it as a query would mean either caching a partial answer or
 *  re-fetching a finished one, and neither is what a reader wants.
 */
export function useStreamingAnswer() {
  const { client } = useMarmConfig();
  const [state, setState] = useState<AnswerStreamState>(IDLE_ANSWER);
  const active = useRef<{ abort: () => void } | null>(null);

  // A reader who leaves the page should not keep a model busy on their behalf.
  useEffect(() => () => active.current?.abort(), []);

  const start = useCallback(
    (data: CodeContextInput) => {
      active.current?.abort();
      setState({ ...IDLE_ANSWER, status: 'streaming' });
      const handle = client.streamCodeContextAnswer(data, (name, payload) => {
        setState((prev) => applyAnswerEvent(prev, name, payload));
      });
      active.current = handle;
      handle.done
        .then(() => {
          // A newer request owns the state now; this one's ending is not news.
          if (active.current !== handle) return;
          setState(applyStreamEnd);
        })
        .catch((error: unknown) => {
          // An abort is the caller's own doing, not a failure to report.
          if (error instanceof DOMException && error.name === 'AbortError') return;
          setState((prev) => ({
            ...prev,
            status: 'error',
            message: 'The answer stream failed.',
          }));
        });
    },
    [client],
  );

  const reset = useCallback(() => {
    active.current?.abort();
    setState(IDLE_ANSWER);
  }, []);

  return { ...state, start, reset };
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

export function useProjectAdr(project: string) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: ['project-adr', baseUrl, project], queryFn: () => client.getProjectAdr(project), enabled: !!project });
}

export function useUpdateProjectAdr() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, content }: { project: string, content: string }) => client.updateProjectAdr(project, content),
    onSuccess: (_data, variables) => qc.invalidateQueries({ queryKey: ['project-adr', baseUrl, variables.project] }),
  });
}

export function useIngestProjectRuntimeTraces() {
  const { client } = useMarmConfig();
  return useMutation({ mutationFn: ({ project, traces }: { project: string, traces: import('@/lib/marm-types').RuntimeTrace[] }) => client.ingestProjectRuntimeTraces(project, traces) });
}

export function useDeleteProject() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, name }: { project: string, name: string }) => client.deleteProject(project, name),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['projects', baseUrl] });
      qc.removeQueries({ queryKey: queryKeys.projectGraph(baseUrl, variables.project) });
      qc.removeQueries({ queryKey: ['projectGraphNeighborhood', baseUrl, variables.project] });
    }
  });
}
