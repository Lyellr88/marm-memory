import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { AnalystProfileName, RuntimeProfile, DockerConfig } from '@/lib/marm-types';
import { queryKeys, useMarmConfig } from './marm-query-core';

export function useRuntimeSettings(enabled = true) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: queryKeys.runtimeSettings(baseUrl),
    queryFn: client.getRuntimeSettings,
    enabled,
    refetchInterval: enabled ? 5000 : false,
    retry: false,
  });
}

export function useUpdateRuntimeAutomation() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ scope, enabled }: { scope: 'graph' | 'concept'; enabled: boolean }) =>
      client.updateRuntimeAutomation(scope, enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.runtimeSettings(baseUrl) }),
  });
}

export function useUpdateRuntimeProfile() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ profile, rateLimitRpm }: { profile: RuntimeProfile; rateLimitRpm?: number | null }) =>
      client.updateRuntimeProfile(profile, rateLimitRpm),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.runtimeSettings(baseUrl) }),
  });
}

/** What the runtime serves and what else is installed on this machine.
 *
 *  Not polled. The disk scan is cheap warm (35 ms against a 62 GB LM Studio
 *  tree) but it is still directory I/O, and the answer only changes when
 *  somebody downloads a model -- so it refetches on demand, not on a timer
 *  like the health panes above.
 */
/** Which local model servers are running. Scanned on demand, not polled:
 *  a loopback sweep is 6ms but it is still nine connect attempts. */
export function useLlmServers(enabled = true) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: ['llm-servers', baseUrl],
    queryFn: () => client.getLlmServers(false),
    enabled,
    retry: false,
  });
}

export function useLlmModels(enabled = true) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: ['llm-models', baseUrl],
    queryFn: () => client.getLlmModels(false),
    enabled,
    retry: false,
  });
}

export function useBrowseLlmModels(path: string | null, enabled = true) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: ['llm-browse', baseUrl, path],
    queryFn: () => client.browseLlmModels(path),
    enabled,
    retry: false,
  });
}

export function useUpdateLlmSettings() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      enabled?: boolean;
      model?: string;
      endpoint?: string;
      profile?: AnalystProfileName | '';
      auto_apply?: boolean | '';
    }) =>
      client.updateLlmSettings(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.runtimeSettings(baseUrl) });
      qc.invalidateQueries({ queryKey: ['llm-models', baseUrl] });
      qc.invalidateQueries({ queryKey: ['llm-servers', baseUrl] });
    },
  });
}

export function useUpdateLlmRoots() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ path, remove }: { path: string; remove?: boolean }) =>
      client.updateLlmRoots(path, remove ?? false),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['llm-models', baseUrl] });
      // A new root changes what Browse may look inside, so every cached
      // listing is now answering with the wrong set of allowed roots.
      qc.invalidateQueries({ queryKey: ['llm-browse', baseUrl] });
    },
  });
}

export function useMaintenance(enabled = true) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: ['maintenance', baseUrl], queryFn: client.getMaintenance, enabled, retry: false });
}

export function useDoctor(enabled = true) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: ['doctor', baseUrl], queryFn: client.getDoctor, enabled, retry: false });
}

export function useRuntimeLogs(lines: number, enabled = true) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: ['runtime-logs', baseUrl, lines],
    queryFn: () => client.getRuntimeLogs(lines),
    enabled,
    retry: false,
    refetchInterval: enabled ? 5000 : false,
  });
}

export function useUpgradeCheck(enabled = false) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: ['upgrade-check', baseUrl], queryFn: client.getUpgradeCheck, enabled, retry: false });
}

export function useBackups(enabled = true) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: ['backups', baseUrl], queryFn: client.getBackups, enabled, retry: false });
}

export function useCreateBackup() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: client.createBackup,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['backups', baseUrl] }),
  });
}

export function useDeleteBackup() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => client.deleteBackup(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['backups', baseUrl] }),
  });
}

export function useStartReloadDocs() {
  const { client } = useMarmConfig();
  return useMutation({ mutationFn: client.startReloadDocs });
}

export function useReloadDocsJob(jobId: string | null) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: ['reload-docs', baseUrl, jobId],
    queryFn: () => client.getReloadDocs(jobId as string),
    enabled: Boolean(jobId),
    retry: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? 1000 : false;
    },
  });
}

export function useStartCompactionDryRun() {
  const { client } = useMarmConfig();
  return useMutation({ mutationFn: (sessionName: string) => client.startCompactionDryRun(sessionName) });
}

export function useCompactionDryRunJob(jobId: string | null) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: ['compaction-dry-run', baseUrl, jobId],
    queryFn: () => client.getCompactionDryRun(jobId as string),
    enabled: Boolean(jobId),
    retry: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? 1000 : false;
    },
  });
}

export function useStartRuntimeRestart() {
  const { client } = useMarmConfig();
  return useMutation({ mutationFn: client.startRuntimeRestart });
}

export function useRuntimeRestartJob(jobId: string | null) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: ['runtime-restart', baseUrl, jobId],
    queryFn: () => client.getRuntimeRestartJob(jobId as string),
    enabled: Boolean(jobId),
    retry: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? 1000 : false;
    },
  });
}

export function useDocker() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.docker(baseUrl), queryFn: client.getDocker, refetchInterval: 5000, retry: false });
}

export function useUpdateDockerConfig() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DockerConfig) => client.updateDockerConfig(body),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.docker(baseUrl), data);
      qc.invalidateQueries({ queryKey: ['agents', baseUrl] });
      qc.invalidateQueries({ queryKey: ['agent-scope', baseUrl] });
    },
  });
}

export function useDockerAction(action: 'pull' | 'start' | 'recreate') {
  const { client } = useMarmConfig();
  const call = { pull: client.dockerPull, start: client.dockerStart, recreate: client.dockerRecreate }[action];
  return useMutation({ mutationFn: () => call() });
}

export function useDockerControl(action: 'stop' | 'restart') {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  const call = { stop: client.dockerStop, restart: client.dockerRestart }[action];
  return useMutation({
    mutationFn: () => call(),
    onSuccess: (data) => qc.setQueryData(queryKeys.docker(baseUrl), data),
  });
}

export function useDockerJob(jobId: string | null) {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useQuery({
    queryKey: ['docker-job', baseUrl, jobId],
    queryFn: async () => {
      const job = await client.getDockerJob(jobId as string);
      if (job.status === 'done' || job.status === 'error') qc.invalidateQueries({ queryKey: queryKeys.docker(baseUrl) });
      return job;
    },
    enabled: Boolean(jobId),
    retry: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? 1000 : false;
    },
  });
}

export function useDockerLogs(enabled: boolean, lines = 200) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: ['docker-logs', baseUrl, lines], queryFn: () => client.getDockerLogs(lines), enabled, retry: false });
}

export function useDockerCompose(enabled: boolean) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: ['docker-compose', baseUrl], queryFn: client.getDockerCompose, enabled, retry: false });
}

export function useWriteDockerCompose() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (overwrite: boolean) => client.writeDockerCompose(overwrite),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['docker-compose', baseUrl] }),
  });
}
