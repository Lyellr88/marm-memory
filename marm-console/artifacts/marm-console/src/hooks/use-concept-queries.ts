import { useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { QueryClient } from '@tanstack/react-query';
import type { ConceptSearchParams, ConceptBuildInput, ConceptGraphParams, DuplicatePairInput, MergeDuplicateInput } from '@/lib/marm-types';
import { queryKeys, useMarmConfig } from './marm-query-core';

// --- Knowledge ---
export function useConceptsSummary() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.conceptsSummary(baseUrl), queryFn: client.getConceptsSummary });
}

export function useConceptLegacyNames() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.conceptLegacyNames(baseUrl), queryFn: client.getConceptLegacyNames });
}

export function useSearchConcepts(params?: ConceptSearchParams) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.conceptsSearch(baseUrl, params), queryFn: () => client.searchConcepts(params) });
}

export function useConceptGraph(enabled = true, params?: ConceptGraphParams) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: queryKeys.conceptsGraph(baseUrl, params),
    queryFn: () => client.getConceptGraph(params),
    enabled,
  });
}

/** Polls a cheap change marker so background indexing reaches the screen
 *  without a reload. Only the marker is fetched on this interval; the atlas
 *  itself is refetched by useGraphAutoRefresh when the marker moves.
 *  refetchIntervalInBackground stays off (the default), so a hidden window
 *  stops polling on its own. */
export function useConceptGraphVersion(enabled = true, intervalMs = 5000) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: queryKeys.conceptsGraphVersion(baseUrl),
    queryFn: client.getConceptGraphVersion,
    enabled,
    refetchInterval: enabled ? intervalMs : false,
  });
}

/** Invalidates the graph views whenever the polled marker changes. Mount it
 *  in a component that is unmounted when its tab is not showing. */
export function useGraphAutoRefresh(enabled = true) {
  const { baseUrl } = useMarmConfig();
  const qc = useQueryClient();
  const { data } = useConceptGraphVersion(enabled);
  const version = data?.version;
  const seen = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!version) return;
    if (seen.current === undefined) {
      seen.current = version;
      return;
    }
    if (seen.current === version) return;
    seen.current = version;
    qc.invalidateQueries({ queryKey: ['conceptsGraph', baseUrl] });
    qc.invalidateQueries({ queryKey: ['neighborhood', baseUrl] });
    qc.invalidateQueries({ queryKey: ['conceptsSummary', baseUrl] });
  }, [version, baseUrl, qc]);
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
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ConceptBuildInput) => client.buildConcepts(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.conceptBuilds(baseUrl) }),
  });
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

export function useConceptDuplicates(params?: { offset?: number; limit?: number }) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: [...queryKeys.duplicates(baseUrl), params],
    queryFn: () => client.getConceptDuplicates(params),
    placeholderData: (previous) => previous,
  });
}

export function useConceptBuilds() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: queryKeys.conceptBuilds(baseUrl),
    queryFn: client.listConceptBuilds,
    refetchInterval: (query) => query.state.data?.some(
      (build) => build.status === 'queued' || build.status === 'running',
    ) ? 2000 : false,
  });
}

function invalidateConceptBuildLifecycle(qc: QueryClient, baseUrl: string) {
  qc.invalidateQueries({ queryKey: queryKeys.conceptBuilds(baseUrl) });
  qc.invalidateQueries({ queryKey: ['conceptBuild', baseUrl] });
  qc.invalidateQueries({ queryKey: ['conceptsGraph', baseUrl] });
  qc.invalidateQueries({ queryKey: ['conceptsSearch', baseUrl] });
  qc.invalidateQueries({ queryKey: queryKeys.conceptsSummary(baseUrl) });
  qc.invalidateQueries({ queryKey: queryKeys.conceptLegacyNames(baseUrl) });
  qc.invalidateQueries({ queryKey: queryKeys.duplicates(baseUrl) });
}

export function useStopConceptBuild() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => client.stopConceptBuild(runId),
    onSuccess: () => invalidateConceptBuildLifecycle(qc, baseUrl),
  });
}

export function useRetryConceptBuild() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => client.retryConceptBuild(runId),
    onSuccess: () => invalidateConceptBuildLifecycle(qc, baseUrl),
  });
}

export function useDeleteConceptGraph() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: client.deleteConceptGraph,
    onSuccess: () => invalidateConceptBuildLifecycle(qc, baseUrl),
  });
}

function invalidateConceptReview(qc: QueryClient, baseUrl: string) {
  qc.invalidateQueries({ queryKey: queryKeys.duplicates(baseUrl) });
  qc.invalidateQueries({ queryKey: ['conceptsGraph', baseUrl] });
  qc.invalidateQueries({ queryKey: ['conceptsSearch', baseUrl] });
  qc.invalidateQueries({ queryKey: queryKeys.conceptsSummary(baseUrl) });
}

export function useDismissConceptDuplicate() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: DuplicatePairInput) => client.dismissConceptDuplicate(data),
    onSuccess: () => invalidateConceptReview(qc, baseUrl),
  });
}

export function useMergeConceptDuplicate() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: MergeDuplicateInput) => client.mergeConceptDuplicate(data),
    onSuccess: () => invalidateConceptReview(qc, baseUrl),
  });
}

export function useRemoveConceptEntity() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (entityId: number) => client.removeConceptEntity(entityId),
    onSuccess: () => invalidateConceptReview(qc, baseUrl),
  });
}
